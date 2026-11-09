# ====================================================================
# pos_transfers.py
#
# Bank-transfer tracking for the POS terminal.
#
# WHY THIS MODULE EXISTS
# ----------------------
# In Nigeria, the majority of in-person POS transactions are bank
# transfers: the customer opens their banking app and sends money to one
# of the merchant's Opay / Moniepoint / Palmpay / GTB / Access / etc.
# accounts. The existing `payment_method='transfer'` enum value exists
# in the sales table, but nothing records WHICH account the money landed
# in. Reconciling the POS against the bank statement therefore requires
# manually eyeballing receipt amounts and timestamps.
#
# This module adds:
#
#   1. org_payment_accounts — a per-org registry of receiving accounts
#      (label, provider, account_number, account_name, is_default).
#
#   2. Four new columns on sales:
#         payment_account_id         UUID  → FK to org_payment_accounts
#         payment_transfer_reference TEXT  → the bank's own txn ref
#         payment_confirmed_at       TIMESTAMPTZ
#         payment_confirmed_by       UUID  → cashier who confirmed
#
#   3. CRUD endpoints under /payment-accounts.
#
#   4. Audit endpoints:
#         GET /payment-accounts/summary   → per-account totals
#         GET /payment-accounts/transfers → filterable transfer log
#
# The POS checkout flow is patched in main.py to REQUIRE an account id
# when payment_method='transfer', and to stamp the sale with all four
# columns immediately after the RPC creates it.
# ====================================================================
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Tuple, Literal, Any
from datetime import datetime, date, timezone
from uuid import UUID
from collections import defaultdict
import httpx
import os

from deps import (
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
    SUPABASE_SERVICE_ROLE_KEY,
    logger,
    get_supabase,
    run_sync_db_call,
    get_current_user_with_role,
    require_role,
    rate_limit,
    get_client_ip,
)


# ─────────────────────────────────────────────────────────────────────
# Migration
# ─────────────────────────────────────────────────────────────────────

async def ensure_payment_accounts_schema() -> None:
    """
    Idempotent. Safe on every boot.
    """
    sql = """
    CREATE TABLE IF NOT EXISTS public.org_payment_accounts (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id          UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        label           TEXT NOT NULL,
        provider        TEXT NOT NULL,
        account_number  TEXT NOT NULL,
        account_name    TEXT NOT NULL,
        is_active       BOOLEAN NOT NULL DEFAULT TRUE,
        is_default      BOOLEAN NOT NULL DEFAULT FALSE,
        sort_order      INTEGER NOT NULL DEFAULT 0,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (org_id, provider, account_number)
    );

    CREATE INDEX IF NOT EXISTS idx_org_payment_accounts_org
        ON public.org_payment_accounts(org_id, is_active);

    CREATE UNIQUE INDEX IF NOT EXISTS idx_org_payment_accounts_default
        ON public.org_payment_accounts(org_id)
        WHERE is_default = TRUE;

    ALTER TABLE public.sales
        ADD COLUMN IF NOT EXISTS payment_account_id          UUID,
        ADD COLUMN IF NOT EXISTS payment_transfer_reference  TEXT,
        ADD COLUMN IF NOT EXISTS payment_confirmed_at        TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS payment_confirmed_by        UUID;

    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
              FROM pg_constraint c
              JOIN pg_attribute a
                ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
             WHERE c.conrelid = 'public.sales'::regclass
               AND c.contype  = 'f'
               AND a.attname  = 'payment_account_id'
        ) THEN
            ALTER TABLE public.sales
                ADD CONSTRAINT sales_payment_account_id_fkey
                FOREIGN KEY (payment_account_id)
                REFERENCES public.org_payment_accounts(id)
                ON DELETE SET NULL;
        END IF;

        IF NOT EXISTS (
            SELECT 1
              FROM pg_constraint c
              JOIN pg_attribute a
                ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
             WHERE c.conrelid = 'public.sales'::regclass
               AND c.contype  = 'f'
               AND a.attname  = 'payment_confirmed_by'
        ) THEN
            ALTER TABLE public.sales
                ADD CONSTRAINT sales_payment_confirmed_by_fkey
                FOREIGN KEY (payment_confirmed_by)
                REFERENCES public.profiles(id)
                ON DELETE SET NULL;
        END IF;
    END $$;

    CREATE INDEX IF NOT EXISTS idx_sales_payment_account
        ON public.sales(payment_account_id, created_at DESC)
        WHERE payment_account_id IS NOT NULL;
    """
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
            json={"query": sql},
            headers=headers,
        )
    if resp.status_code not in (200, 204):
        logger.error(f"org_payment_accounts migration failed: {resp.text}")
        raise RuntimeError(f"org_payment_accounts migration failed: {resp.text}")
    logger.info("org_payment_accounts schema installed (or already present)")


# ─────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────

ALLOWED_PROVIDERS = {
    "opay", "moniepoint", "palmpay", "kuda", "palmpay", "pocketapp",
    "gtb", "access", "zenith", "uba", "first_bank", "union",
    "fidelity", "sterling", "wema", "polaris", "fcmb", "stanbic",
    "ecobank", "heritage", "keystone", "providus", "unity", "suntrust",
    "other",
}


class PaymentAccountCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    provider: str = Field(..., min_length=1, max_length=50)
    account_number: str = Field(..., min_length=10, max_length=20)
    account_name: str = Field(..., min_length=1, max_length=200)
    is_default: bool = False
    sort_order: int = 0

    @validator("provider")
    def _provider_ok(cls, v):
        v = (v or "").strip().lower()
        if v not in ALLOWED_PROVIDERS:
            raise ValueError(f"provider must be one of {sorted(ALLOWED_PROVIDERS)}")
        return v

    @validator("account_number")
    def _account_number_ok(cls, v):
        v = (v or "").strip()
        if not v.isdigit() or not (10 <= len(v) <= 20):
            raise ValueError("account_number must be 10-20 digits")
        return v


class PaymentAccountUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=100)
    provider: Optional[str] = Field(None, min_length=1, max_length=50)
    account_number: Optional[str] = Field(None, min_length=10, max_length=20)
    account_name: Optional[str] = Field(None, min_length=1, max_length=200)
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    sort_order: Optional[int] = None

    @validator("provider")
    def _provider_ok(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        if v not in ALLOWED_PROVIDERS:
            raise ValueError(f"provider must be one of {sorted(ALLOWED_PROVIDERS)}")
        return v

    @validator("account_number")
    def _account_number_ok(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v.isdigit() or not (10 <= len(v) <= 20):
            raise ValueError("account_number must be 10-20 digits")
        return v


# ─────────────────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/payment-accounts", tags=["Payment Accounts"])


def _serialize_account(row: Dict) -> Dict:
    return {
        "id":             row.get("id"),
        "label":          row.get("label"),
        "provider":       row.get("provider"),
        "account_number": row.get("account_number"),
        "account_name":   row.get("account_name"),
        "is_active":      bool(row.get("is_active", True)),
        "is_default":     bool(row.get("is_default", False)),
        "sort_order":     int(row.get("sort_order") or 0),
        "created_at":     row.get("created_at"),
        "updated_at":     row.get("updated_at"),
    }


@router.get("")
async def list_payment_accounts(
    request: Request,
    include_inactive: bool = Query(False),
    include_totals: bool = Query(False, description="Attach per-account transfer stats"),
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "sales_rep", "finance", "inventory_manager"])
    ),
):
    """
    List the org's registered receiving accounts.

    `include_totals=true` attaches a `stats` object to each account:
        { count, total, today_count, today_total, mtd_count, mtd_total }

    Filterable flags:
      - include_inactive=false (default) → only `is_active=TRUE`
    """
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    query = (
        client.table("org_payment_accounts")
        .select("*")
        .eq("org_id", org_id)
        .order("is_default", desc=True)
        .order("sort_order", desc=False)
        .order("label", desc=False)
    )
    if not include_inactive:
        query = query.eq("is_active", True)

    res = await run_sync_db_call(query.execute)
    accounts = [_serialize_account(r) for r in (res.data or [])]

    if include_totals and accounts:
        stats_by_account = await _compute_transfer_stats(org_id, [a["id"] for a in accounts])
        for acc in accounts:
            acc["stats"] = stats_by_account.get(
                acc["id"],
                {"count": 0, "total": 0.0,
                 "today_count": 0, "today_total": 0.0,
                 "mtd_count": 0, "mtd_total": 0.0},
            )

    return {"accounts": accounts, "total": len(accounts)}


async def _compute_transfer_stats(org_id: str, account_ids: List[str]) -> Dict[str, Dict]:
    """
    Group transfer sales by payment_account_id.

    Single full scan of the org's transfer sales, aggregated in Python.
    At 10k transfers/org/month this is a ~50ms query. If a shop ever
    exceeds that, promote to a materialized view; the aggregation logic
    below is the authoritative shape.
    """
    client = get_supabase()
    res = await run_sync_db_call(
        client.table("sales")
        .select("payment_account_id, total_amount, created_at")
        .eq("org_id", org_id)
        .eq("payment_method", "transfer")
        .not_.is_("payment_account_id", "null")
        .execute
    )

    today = date.today()
    month_start = today.replace(day=1)
    today_iso = today.isoformat()
    month_iso = month_start.isoformat()

    bucket: Dict[str, Dict] = defaultdict(
        lambda: {"count": 0, "total": 0.0,
                 "today_count": 0, "today_total": 0.0,
                 "mtd_count": 0, "mtd_total": 0.0}
    )

    wanted = set(account_ids)
    for row in (res.data or []):
        acc_id = row.get("payment_account_id")
        if acc_id not in wanted:
            continue
        amt = float(row.get("total_amount") or 0)
        b = bucket[acc_id]
        b["count"] += 1
        b["total"] += amt
        created = (row.get("created_at") or "")[:10]
        if created == today_iso:
            b["today_count"] += 1
            b["today_total"] += amt
        if created and created >= month_iso:
            b["mtd_count"] += 1
            b["mtd_total"] += amt

    return dict(bucket)


@router.post("")
async def create_payment_account(
    request: Request,
    payload: PaymentAccountCreate,
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "finance"])
    ),
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    # If this is being made the default, unset any existing default first.
    if payload.is_default:
        await run_sync_db_call(
            client.table("org_payment_accounts")
            .update({"is_default": False, "updated_at": now})
            .eq("org_id", org_id)
            .eq("is_default", True)
            .execute
        )

    insert_data = {
        "org_id":         org_id,
        "label":          payload.label.strip(),
        "provider":       payload.provider,
        "account_number": payload.account_number,
        "account_name":   payload.account_name.strip(),
        "is_active":      True,
        "is_default":     payload.is_default,
        "sort_order":     payload.sort_order,
        "created_at":     now,
        "updated_at":     now,
    }

    try:
        ins = await run_sync_db_call(
            client.table("org_payment_accounts").insert(insert_data).execute
        )
    except Exception as e:
        msg = str(e)
        if "duplicate key" in msg or "23505" in msg:
            raise HTTPException(
                status_code=409,
                detail="An account with this provider and account number already exists",
            )
        raise HTTPException(status_code=500, detail=f"Failed to create account: {msg}")

    if not ins.data:
        raise HTTPException(status_code=500, detail="Failed to create account")
    return {"account": _serialize_account(ins.data[0])}


@router.patch("/{account_id}")
async def update_payment_account(
    request: Request,
    account_id: UUID,
    payload: PaymentAccountUpdate,
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "finance"])
    ),
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    existing = await run_sync_db_call(
        client.table("org_payment_accounts")
        .select("id, is_default")
        .eq("id", str(account_id))
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Payment account not found")

    updates = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    # Becoming default: unset any other default first.
    if updates.get("is_default") is True:
        await run_sync_db_call(
            client.table("org_payment_accounts")
            .update({"is_default": False, "updated_at": now})
            .eq("org_id", org_id)
            .eq("is_default", True)
            .neq("id", str(account_id))
            .execute
        )

    updates["updated_at"] = now

    try:
        res = await run_sync_db_call(
            client.table("org_payment_accounts")
            .update(updates)
            .eq("id", str(account_id))
            .eq("org_id", org_id)
            .execute
        )
    except Exception as e:
        msg = str(e)
        if "duplicate key" in msg or "23505" in msg:
            raise HTTPException(
                status_code=409,
                detail="An account with this provider and account number already exists",
            )
        raise HTTPException(status_code=500, detail=f"Failed to update account: {msg}")

    if not res.data:
        raise HTTPException(status_code=404, detail="Payment account not found")
    return {"account": _serialize_account(res.data[0])}


@router.delete("/{account_id}")
async def delete_payment_account(
    request: Request,
    account_id: UUID,
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin"])
    ),
):
    """
    Soft-delete by setting is_active=FALSE.

    We never hard-delete an account because historical sales point at it
    via payment_account_id. Keeping the row lets the audit view resolve
    the label for old transfers. If the admin really wants it gone, they
    can deactivate (this endpoint) — the POS dropdown will hide it but
    historical reports stay correct.
    """
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    res = await run_sync_db_call(
        client.table("org_payment_accounts")
        .update({
            "is_active": False,
            "is_default": False,
            "updated_at": now,
        })
        .eq("id", str(account_id))
        .eq("org_id", org_id)
        .execute
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Payment account not found")
    return {"deactivated": True, "account_id": str(account_id)}


@router.get("/summary")
async def payment_accounts_summary(
    request: Request,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "finance", "auditor"])
    ),
):
    """
    Per-account totals for the accounting dashboard.

    Returns one row per active account: total received, count of transfers,
    average ticket, and last transfer timestamp. Optionally scoped to a
    date range.
    """
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    accounts_res = await run_sync_db_call(
        client.table("org_payment_accounts")
        .select("id, label, provider, account_number, account_name, is_default")
        .eq("org_id", org_id)
        .eq("is_active", True)
        .order("is_default", desc=True)
        .order("label", desc=False)
        .execute
    )
    accounts = accounts_res.data or []

    if not accounts:
        return {"accounts": [], "period": {"from": None, "to": None}}

    query = (
        client.table("sales")
        .select("payment_account_id, total_amount, created_at")
        .eq("org_id", org_id)
        .eq("payment_method", "transfer")
        .not_.is_("payment_account_id", "null")
    )
    if from_date:
        query = query.gte("created_at", f"{from_date.isoformat()}T00:00:00")
    if to_date:
        query = query.lte("created_at", f"{to_date.isoformat()}T23:59:59")

    sales_res = await run_sync_db_call(query.execute)
    sales_rows = sales_res.data or []

    by_id: Dict[str, List[Dict]] = defaultdict(list)
    for row in sales_rows:
        by_id[row.get("payment_account_id")].append(row)

    out = []
    for acc in accounts:
        rows = by_id.get(acc["id"], [])
        total = sum(float(r.get("total_amount") or 0) for r in rows)
        count = len(rows)
        last = max((r.get("created_at") for r in rows), default=None)
        out.append({
            **_serialize_account(acc),
            "transfer_count": count,
            "total_received": round(total, 2),
            "average_ticket":  round(total / count, 2) if count else 0.0,
            "last_transfer_at": last,
        })

    return {
        "accounts": out,
        "period": {
            "from": from_date.isoformat() if from_date else None,
            "to":   to_date.isoformat() if to_date else None,
        },
    }


@router.get("/transfers")
async def list_transfers(
    request: Request,
    account_id: Optional[UUID] = Query(None),
    provider: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    cashier_id: Optional[UUID] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "finance", "auditor"])
    ),
):
    """
    The audit trail. Every POS transfer, filterable by account / date /
    cashier. Use this to reconcile the POS against the bank statement.

    Each row carries the sale data AND the account that received it, so
    the accountant sees: receipt#, cashier, amount, which account, bank
    reference, confirmed timestamp — all in one row.
    """
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    query = (
        client.table("sales")
        .select(
            "id, receipt_number, total_amount, payment_method, "
            "payment_account_id, payment_transfer_reference, "
            "payment_confirmed_at, payment_confirmed_by, "
            "customer_name, customer_phone, created_at, user_id, "
            "org_payment_account:org_payment_accounts!payment_account_id("
            "id, label, provider, account_number, account_name)",
            count="exact",
        )
        .eq("org_id", org_id)
        .eq("payment_method", "transfer")
    )

    if account_id:
        query = query.eq("payment_account_id", str(account_id))
    if from_date:
        query = query.gte("created_at", f"{from_date.isoformat()}T00:00:00")
    if to_date:
        query = query.lte("created_at", f"{to_date.isoformat()}T23:59:59")
    if cashier_id:
        query = query.eq("user_id", str(cashier_id))

    res = await run_sync_db_call(
        query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute
    )
    rows = res.data or []

    # Provider filter applied in Python because it lives on the joined
    # account row — PostgREST cannot filter on an embedded resource
    # without a second round trip, and this is a small result set.
    if provider:
        provider = provider.strip().lower()
        rows = [
            r for r in rows
            if (r.get("org_payment_account") or {}).get("provider") == provider
        ]

    # Enrich with cashier name for the audit display.
    cashier_ids = list({r.get("user_id") for r in rows if r.get("user_id")})
    profiles_map: Dict[str, Dict] = {}
    if cashier_ids:
        prof_res = await run_sync_db_call(
            client.table("profiles")
            .select("id, first_name, last_name, email")
            .in_("id", cashier_ids)
            .execute
        )
        profiles_map = {p["id"]: p for p in (prof_res.data or [])}

    transfers: List[Dict] = []
    for r in rows:
        acc = r.get("org_payment_account") or {}
        cashier = profiles_map.get(r.get("user_id")) or {}
        cashier_name = " ".join(
            filter(None, [cashier.get("first_name"), cashier.get("last_name")])
        ).strip() or None

        transfers.append({
            "sale_id":                    r.get("id"),
            "receipt_number":             r.get("receipt_number"),
            "amount":                     float(r.get("total_amount") or 0),
            "customer_name":              r.get("customer_name"),
            "customer_phone":             r.get("customer_phone"),
            "created_at":                 r.get("created_at"),
            "payment_confirmed_at":       r.get("payment_confirmed_at"),
            "payment_transfer_reference": r.get("payment_transfer_reference"),
            "cashier_id":                 r.get("user_id"),
            "cashier_name":               cashier_name,
            "account": {
                "id":             acc.get("id"),
                "label":          acc.get("label"),
                "provider":       acc.get("provider"),
                "account_number": acc.get("account_number"),
                "account_name":   acc.get("account_name"),
            } if acc else None,
        })

    return {
        "transfers": transfers,
        "total": res.count if hasattr(res, "count") and res.count is not None else len(transfers),
        "returned": len(transfers),
        "limit": limit,
        "offset": offset,
    }
