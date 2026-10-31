"""
Extended executive dashboard — profitability view.
"""
from fastapi import APIRouter, Depends, Request, Query
from typing import Tuple
from datetime import date, datetime, timezone, timedelta

from main import (
    get_supabase,
    run_sync_db_call,
    rate_limit,
    get_client_ip,
)
from deps import require_feature, require_role

router = APIRouter(prefix="/dashboard", tags=["Executive Dashboard"])


@router.get("/profitability")
async def profitability(
    request: Request,
    from_date: date = Query(...),
    to_date: date = Query(...),
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "finance"])
    ),
):
    """
    One-shot profitability analysis for a date range.

    Returns:
      - revenue, cogs, gross_profit, expenses, net_income, margins
      - top COGS products (what costs you the most)
      - top expense categories
      - expired/waste value (stock that expired during the range)
      - uncollected AR within the range
      - month-by-month breakdown of the range
    """
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    from_iso = from_date.isoformat()
    to_iso = to_date.isoformat()

    # ── 1. Revenue & COGS from sales ──────────────────────────────
    sales_res = await run_sync_db_call(
        client.table("sales")
        .select("id, total_amount, created_at")
        .eq("org_id", org_id)
        .eq("status", "completed")
        .gte("created_at", f"{from_iso}T00:00:00")
        .lte("created_at", f"{to_iso}T23:59:59")
        .execute
    )
    sales_rows = sales_res.data or []
    revenue = sum(float(s.get("total_amount") or 0) for s in sales_rows)
    sales_ids = [s["id"] for s in sales_rows]

    # COGS = sum(quantity × cost_price_naira) for sale_items in range
    cogs = 0.0
    cogs_by_product: dict = {}
    if sales_ids:
        si_res = await run_sync_db_call(
            client.table("sale_items")
            .select("inventory_id, product_name, quantity, subtotal")
            .in_("sale_id", sales_ids)
            .execute
        )
        si_rows = si_res.data or []
        inv_ids = list({r["inventory_id"] for r in si_rows if r.get("inventory_id")})
        cost_map = {}
        if inv_ids:
            inv_res = await run_sync_db_call(
                client.table("inventory")
                .select("id, cost_price_naira")
                .eq("org_id", org_id)
                .in_("id", inv_ids)
                .execute
            )
            cost_map = {r["id"]: float(r.get("cost_price_naira") or 0) for r in (inv_res.data or [])}

        for si in si_rows:
            unit_cost = cost_map.get(si["inventory_id"], 0)
            line_cogs = unit_cost * int(si["quantity"] or 0)
            cogs += line_cogs
            name = si.get("product_name") or f"Item {si['inventory_id']}"
            cogs_by_product[name] = cogs_by_product.get(name, 0.0) + line_cogs

    gross_profit = revenue - cogs

    # ── 2. Operating expenses ────────────────────────────────────
    exp_res = await run_sync_db_call(
        client.table("expenses")
        .select("category, amount")
        .eq("org_id", org_id)
        .eq("status", "posted")
        .gte("expense_date", from_iso)
        .lte("expense_date", to_iso)
        .execute
    )
    exp_rows = exp_res.data or []
    total_expenses = sum(float(r.get("amount") or 0) for r in exp_rows)

    expense_by_cat: dict = {}
    for r in exp_rows:
        cat = r.get("category") or "Uncategorised"
        expense_by_cat[cat] = expense_by_cat.get(cat, 0.0) + float(r.get("amount") or 0)

    net_income = gross_profit - total_expenses

    # ── 3. Waste: expired batches that were written off ──────────
    # Approximation: sum of location_stocks rows whose batch expired
    # during the range, priced at cost. This is "what expired while
    # sitting on your shelf in this period".
    expired_res = await run_sync_db_call(
        client.table("inventory_batches")
        .select("quantity, cost_price_naira, expiry_date, inventory!inner(org_id)")
        .eq("inventory.org_id", org_id)
        .gte("expiry_date", from_iso)
        .lte("expiry_date", to_iso)
        .execute
    )
    waste_value = 0.0
    for b in (expired_res.data or []):
        waste_value += float(b.get("quantity") or 0) * float(b.get("cost_price_naira") or 0)

    # ── 4. Uncollected AR within the range ───────────────────────
    ar_res = await run_sync_db_call(
        client.table("accounts_receivable")
        .select("amount, paid_amount, status, due_date")
        .eq("org_id", org_id)
        .gte("due_date", from_iso)
        .lte("due_date", to_iso)
        .in_("status", ["pending", "partial", "overdue"])
        .execute
    )
    ar_rows = ar_res.data or []
    uncollected_ar = sum(
        float(r.get("amount") or 0) - float(r.get("paid_amount") or 0)
        for r in ar_rows
    )

    # ── 5. Month-by-month breakdown ──────────────────────────────
    monthly: dict = {}
    for s in sales_rows:
        m = (s.get("created_at") or "")[:7]  # YYYY-MM
        if m not in monthly:
            monthly[m] = {"revenue": 0.0}
        monthly[m]["revenue"] += float(s.get("total_amount") or 0)
    for e in exp_rows:
        m = e.get("expense_date", "")[:7]
        if m not in monthly:
            monthly[m] = {"revenue": 0.0}
        monthly[m].setdefault("expenses", 0.0)
        monthly[m]["expenses"] += float(e.get("amount") or 0)

    # ── 6. Compose response ──────────────────────────────────────
    top_cogs = [
        {"product": k, "cogs": round(v, 2)}
        for k, v in sorted(cogs_by_product.items(), key=lambda x: -x[1])[:10]
    ]
    top_expenses = [
        {"category": k, "amount": round(v, 2)}
        for k, v in sorted(expense_by_cat.items(), key=lambda x: -x[1])[:10]
    ]

    def pct(num, den):
        return round((num / den) * 100, 2) if den else 0.0

    return {
        "period": {"from": from_iso, "to": to_iso},
        "revenue": round(revenue, 2),
        "cogs": round(cogs, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_margin_pct": pct(gross_profit, revenue),
        "operating_expenses": round(total_expenses, 2),
        "net_income": round(net_income, 2),
        "net_margin_pct": pct(net_income, revenue),
        "waste_value": round(waste_value, 2),
        "uncollected_ar": round(uncollected_ar, 2),
        "top_cogs_products": top_cogs,
        "top_expense_categories": top_expenses,
        "monthly_breakdown": [
            {
                "month": m,
                "revenue": round(v.get("revenue", 0.0), 2),
                "expenses": round(v.get("expenses", 0.0), 2),
            }
            for m, v in sorted(monthly.items())
        ],
        "cost_drivers_summary": {
            "largest_cogs_product": top_cogs[0]["product"] if top_cogs else None,
            "largest_cogs_value": top_cogs[0]["cogs"] if top_cogs else 0.0,
            "largest_expense_category": top_expenses[0]["category"] if top_expenses else None,
            "largest_expense_value": top_expenses[0]["amount"] if top_expenses else 0.0,
            "waste_vs_revenue_pct": pct(waste_value, revenue),
        },
    }
