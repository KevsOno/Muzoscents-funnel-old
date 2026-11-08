"""
Expense entry module.
Register at the bottom of main.py:
    from expenses import router as expenses_router
    app.include_router(expenses_router)
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from typing import Optional, Tuple, Literal, List
from datetime import date, datetime, timezone
from uuid import UUID

# These live in main.py today. The bottom-of-file include
# ensures this import resolves.
from main import (           # noqa: E402
    get_supabase,
    run_sync_db_call,
    rate_limit,
    get_client_ip,
    resolve_branch_for_write,
    resolve_request_branch,
    create_journal_entry,
    _log_audit_event,
)
from deps import require_feature, require_role

router = APIRouter(prefix="/expenses", tags=["Expenses"])


# ─── Models ──────────────────────────────────────────────────────────

class ExpenseCreate(BaseModel):
    expense_date:   date
    category:       str = Field(..., min_length=1, max_length=100)
    account_id:     Optional[UUID] = None
    vendor:         Optional[str] = Field(None, max_length=200)
    description:    Optional[str] = Field(None, max_length=1000)
    amount:         float = Field(..., gt=0)
    payment_method: Literal["cash", "bank_transfer", "card", "cheque", "credit"] = "cash"
    reference:      Optional[str] = Field(None, max_length=100)
    receipt_url:    Optional[str] = Field(None, max_length=500)


class ExpenseUpdate(BaseModel):
    expense_date:   Optional[date] = None
    category:       Optional[str] = Field(None, min_length=1, max_length=100)
    account_id:     Optional[UUID] = None
    vendor:         Optional[str] = Field(None, max_length=200)
    description:    Optional[str] = Field(None, max_length=1000)
    amount:         Optional[float] = Field(None, gt=0)
    payment_method: Optional[Literal["cash", "bank_transfer", "card", "cheque", "credit"]] = None
    reference:      Optional[str] = Field(None, max_length=100)
    receipt_url:    Optional[str] = Field(None, max_length=500)


# ─── Helpers ─────────────────────────────────────────────────────────

async def _resolve_cash_account(client, org_id: str) -> Optional[str]:
    """Prefer a cash account, fall back to any asset account."""
    res = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "asset")
        .ilike("name", "%cash%")
        .limit(1)
        .execute
    )
    if res.data:
        return res.data[0]["id"]

    res = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "asset")
        .limit(1)
        .execute
    )
    return res.data[0]["id"] if res.data else None


async def _resolve_expense_account(client, org_id: str) -> Optional[str]:
    """Fall back to any expense-type account."""
    res = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "expense")
        .limit(1)
        .execute
    )
    return res.data[0]["id"] if res.data else None


# ─── Endpoints ───────────────────────────────────────────────────────

@router.post("")
async def create_expense(
    request: Request,
    payload: ExpenseCreate,
    user_data: Tuple[str, str, str] = Depends(
        require_feature("accounting", allowed_roles=["owner", "admin", "finance"])
    ),
):
    """
    Create an expense. Also posts a balanced journal entry:
        Debit  Expense account      amount
        Credit Cash (or AP)         amount

    If `payment_method == 'credit'`, the credit side goes to an A/P
    account; otherwise to a cash account.
    """
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    # Validate the category
    if not payload.category.strip():
        raise HTTPException(status_code=400, detail="Category is required")

    # Resolve accounts
    expense_account_id = str(payload.account_id) if payload.account_id else await _resolve_expense_account(client, org_id)
    if not expense_account_id:
        raise HTTPException(
            status_code=400,
            detail="No expense-type account exists in chart_of_accounts for this org. Create one first.",
        )

    if payload.payment_method == "credit":
        ap_res = await run_sync_db_call(
            client.table("chart_of_accounts")
            .select("id")
            .eq("org_id", org_id)
            .eq("type", "liability")
            .ilike("name", "%accounts payable%")
            .limit(1)
            .execute
        )
        credit_account_id = ap_res.data[0]["id"] if ap_res.data else None
    else:
        credit_account_id = await _resolve_cash_account(client, org_id)

    if not credit_account_id:
        raise HTTPException(
            status_code=400,
            detail="No cash/ap account available to post the credit side of the entry.",
        )

    # Insert the expense row
    branch_id = await resolve_branch_for_write(org_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    insert_res = await run_sync_db_call(
        client.table("expenses").insert({
            "org_id":         org_id,
            "branch_id":      branch_id,
            "expense_date":   payload.expense_date.isoformat(),
            "category":       payload.category.strip(),
            "account_id":     expense_account_id,
            "vendor":         payload.vendor,
            "description":    payload.description,
            "amount":         payload.amount,
            "payment_method": payload.payment_method,
            "reference":      payload.reference,
            "receipt_url":    payload.receipt_url,
            "status":         "posted",
            "created_by":     user_id,
            "created_at":     now_iso,
            "updated_at":     now_iso,
        }).execute
    )
    if not insert_res.data:
        raise HTTPException(status_code=500, detail="Failed to record expense")

    expense = insert_res.data[0]

    # Journal entry
    try:
        journal = await create_journal_entry(
            org_id=org_id,
            entry_date=payload.expense_date,
            description=f"Expense: {payload.category}"
                        + (f" — {payload.vendor}" if payload.vendor else ""),
            lines=[
                {"account_id": expense_account_id, "debit": payload.amount, "credit": 0},
                {"account_id": credit_account_id, "debit": 0, "credit": payload.amount},
            ],
            reference=payload.reference or f"EXP-{str(expense['id'])[:8]}",
            created_by=user_id,
            status="posted",
        )
        # Link the journal back to the expense
        await run_sync_db_call(
            client.table("expenses")
            .update({"journal_entry_id": journal["id"]})
            .eq("id", expense["id"])
            .execute
        )
        expense["journal_entry_id"] = journal["id"]
    except Exception as e:
        # Journal failure should not roll back the expense record itself;
        # surface it so the operator can fix the chart_of_accounts.
        raise HTTPException(
            status_code=500,
            detail=f"Expense saved but journal posting failed: {e}",
        )

    await _log_audit_event(org_id, user_id, "expenses", "create", UUID(expense["id"]), None, expense)

    return {"expense": expense}


@router.get("")
async def list_expenses(
    request: Request,
    from_date: Optional[date] = Query(None, description="Filter: expense_date >= from_date (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, description="Filter: expense_date <= to_date (YYYY-MM-DD)"),
    category: Optional[str] = Query(None),
    payment_method: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    user_data: Tuple[str, str, str] = Depends(
        require_feature("accounting", allowed_roles=["owner", "admin", "finance", "auditor"])
    ),
):
    """
    List expenses. Filters by date range (expense_date), category,
    payment method, and — when the caller has picked a branch — by
    branch. `total` is the exact number of matching rows from
    `count="exact"`, independent of the limit/offset slice.
    """
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()

    # Branch scoping. Owners with no branch header see all branches;
    # everyone else sees their selected branch (or their single
    # branch if they only have one).
    selected_branch = await resolve_request_branch(request, user_id, org_id, role)

    q = client.table("expenses").select("*", count="exact").eq("org_id", org_id)

    if selected_branch:
        q = q.eq("branch_id", selected_branch)

    if from_date:
        q = q.gte("expense_date", from_date.isoformat())
    if to_date:
        q = q.lte("expense_date", to_date.isoformat())
    if category:
        q = q.eq("category", category)
    if payment_method:
        q = q.eq("payment_method", payment_method)

    res = await run_sync_db_call(
        q.order("expense_date", desc=True).range(offset, offset + limit - 1).execute
    )
    return {
        "expenses": res.data or [],
        "total": res.count or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/summary")
async def expenses_summary(
    request: Request,
    from_date: date = Query(...),
    to_date: date = Query(...),
    user_data: Tuple[str, str, str] = Depends(
        require_feature("accounting", allowed_roles=["owner", "admin", "finance", "auditor"])
    ),
):
    """
    Totals grouped by category, plus a daily series for charting.
    Branch-scoped: if the caller has selected a branch, the totals
    match the list endpoint for that same branch.
    """
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()

    selected_branch = await resolve_request_branch(request, user_id, org_id, role)

    q = (
        client.table("expenses")
        .select("expense_date, category, amount, payment_method")
        .eq("org_id", org_id)
        .gte("expense_date", from_date.isoformat())
        .lte("expense_date", to_date.isoformat())
        .eq("status", "posted")
    )
    if selected_branch:
        q = q.eq("branch_id", selected_branch)

    res = await run_sync_db_call(q.execute)
    rows = res.data or []

    by_category: dict = {}
    by_day: dict = {}
    by_method: dict = {}
    total = 0.0

    for r in rows:
        amt = float(r.get("amount") or 0)
        total += amt

        cat = r.get("category") or "Uncategorised"
        by_category[cat] = by_category.get(cat, 0.0) + amt

        day = r.get("expense_date")
        by_day[day] = by_day.get(day, 0.0) + amt

        m = r.get("payment_method") or "unknown"
        by_method[m] = by_method.get(m, 0.0) + amt

    return {
        "period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
        "total": round(total, 2),
        "by_category": [
            {"category": k, "amount": round(v, 2)}
            for k, v in sorted(by_category.items(), key=lambda x: -x[1])
        ],
        "by_payment_method": [
            {"method": k, "amount": round(v, 2)}
            for k, v in sorted(by_method.items(), key=lambda x: -x[1])
        ],
        "daily_series": [
            {"date": k, "amount": round(v, 2)}
            for k, v in sorted(by_day.items())
        ],
    }


@router.delete("/{expense_id}")
async def delete_expense(
    request: Request,
    expense_id: UUID,
    user_data: Tuple[str, str, str] = Depends(
        require_feature("accounting", allowed_roles=["owner", "admin", "finance"])
    ),
):
    """
    Soft-delete: sets status='void'. The journal entry is left in place
    so the audit trail stays intact. To truly reverse the accounting,
    create a reversing journal entry manually.
    """
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    existing = await run_sync_db_call(
        client.table("expenses")
        .select("id, status")
        .eq("id", str(expense_id))
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Expense not found")
    if existing.data.get("status") == "void":
        return {"message": "Already void"}

    await run_sync_db_call(
        client.table("expenses")
        .update({
            "status": "void",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", str(expense_id))
        .eq("org_id", org_id)
        .execute
    )

    await _log_audit_event(
        org_id, user_id, "expenses", "void",
        expense_id, existing.data, {"status": "void"},
    )
    return {"message": "Expense voided"}
