"""
procurement.py — Procurement routes.

Extracted from main.py to keep the monolith from growing further.
Currently hosts /restock-hub. The remaining procurement endpoints
(/suppliers, /purchase-orders, /grn) will migrate here incrementally
once their dependencies on main.py helpers (create_ap_from_po,
post_grn's A/P linkage, etc.) are resolved.
"""
from fastapi import APIRouter, Depends, Request
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone

from deps import (
    logger,
    get_supabase,
    run_sync_db_call,
    rate_limit,
    get_client_ip,
    require_feature,
)

router = APIRouter(tags=["Procurement"])


@router.get("/restock-hub")
async def get_restock_hub(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(
        require_feature(
            "procurement",
            allowed_roles=["owner", "admin", "inventory_manager"],
        )
    )
):
    """
    Aggregated procurement intelligence for the Restock Hub tab.

    Combines stock_limits (per-location reorder points / max stock)
    with active OUT_OF_STOCK alerts (for the "out for N days" figure)
    into a single list of items that need replenishment.

    Gated on `procurement` because this endpoint exists only to feed
    the Restock Hub — a procurement surface. The shared inventory
    endpoints (`/stock-limits`, `/alerts`) remain on their own feature
    gates and are not affected.
    """
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    # ── 1. Fetch stock limits for the org ──
    try:
        limits_res = await run_sync_db_call(
            client.table("stock_limits")
            .select(
                "inventory_id, location_id, avg_daily_demand, "
                "reorder_point, max_stock"
            )
            .eq("org_id", org_id)
            .execute
        )
        limits = limits_res.data or []
    except Exception as e:
        logger.error(f"restock-hub: stock_limits read failed: {e}")
        return {
            "items": [],
            "summary": {"out_of_stock": 0, "low_stock": 0, "estimated_value": 0.0},
        }

    inventory_ids = {l["inventory_id"] for l in limits if l.get("inventory_id")}
    if not inventory_ids:
        return {
            "items": [],
            "summary": {"out_of_stock": 0, "low_stock": 0, "estimated_value": 0.0},
        }

    # ── 2. Fetch inventory details (name, sku, current_qty, cost) ──
    try:
        inv_res = await run_sync_db_call(
            client.table("inventory")
            .select("id, description, item_code, current_qty, cost_price_naira")
            .eq("org_id", org_id)
            .in_("id", list(inventory_ids))
            .execute
        )
        inv_map = {p["id"]: p for p in (inv_res.data or [])}
    except Exception as e:
        logger.error(f"restock-hub: inventory read failed: {e}")
        inv_map = {}

    # ── 3. Fetch active OUT_OF_STOCK alerts (for "out for N days") ──
    out_since_map: Dict[int, str] = {}
    try:
        alerts_res = await run_sync_db_call(
            client.table("alert_log")
            .select("inventory_id, created_at")
            .eq("org_id", org_id)
            .eq("alert_type", "OUT_OF_STOCK")
            .is_("action_taken", "null")
            .order("created_at", desc=False)
            .execute
        )
        for a in (alerts_res.data or []):
            inv_id = a.get("inventory_id")
            if inv_id and inv_id not in out_since_map:
                out_since_map[inv_id] = a.get("created_at")
    except Exception as e:
        logger.warning(f"restock-hub: alerts read failed: {e}")

    # ── 4. Aggregate stock limits by inventory_id ──
    aggregated: Dict[int, Dict] = {}
    for l in limits:
        inv_id = l.get("inventory_id")
        if not inv_id:
            continue
        if inv_id not in aggregated:
            aggregated[inv_id] = {
                "total_reorder": 0,
                "total_max":     0,
                "total_demand":  0.0,
            }
        aggregated[inv_id]["total_reorder"] += int(l.get("reorder_point") or 0)
        aggregated[inv_id]["total_max"]     += int(l.get("max_stock") or 0)
        aggregated[inv_id]["total_demand"]  += float(l.get("avg_daily_demand") or 0)

    # ── 5. Build the restock list ──
    now = datetime.now(timezone.utc)
    items: List[Dict] = []
    out_of_stock_count = 0
    low_stock_count = 0
    estimated_value = 0.0

    for inv_id, agg in aggregated.items():
        product = inv_map.get(inv_id)
        if not product:
            continue
        current_qty = int(product.get("current_qty") or 0)

        if current_qty > agg["total_reorder"] and current_qty > 0:
            continue

        if current_qty <= 0:
            out_of_stock_count += 1
            out_since = out_since_map.get(inv_id)
            if out_since:
                try:
                    out_dt = datetime.fromisoformat(out_since.replace("Z", "+00:00"))
                    if out_dt.tzinfo is None:
                        out_dt = out_dt.replace(tzinfo=timezone.utc)
                    days_out = max(0, (now - out_dt).days)
                    days_left_display = f"Out for {days_out} days"
                except Exception:
                    days_left_display = "Out of stock"
            else:
                days_left_display = "Out of stock"
        else:
            low_stock_count += 1
            if agg["total_demand"] > 0:
                days_left = round(current_qty / agg["total_demand"])
                days_left_display = f"{days_left} days"
            else:
                days_left_display = "∞"

        suggested_order = (
            max(0, agg["total_max"] - current_qty)
            if agg["total_max"] > 0 else 10
        )
        cost = float(product.get("cost_price_naira") or 0)
        estimated_value += suggested_order * cost

        items.append({
            "inventory_id":      inv_id,
            "name":              product.get("description") or "Unknown",
            "sku":               product.get("item_code") or "N/A",
            "current_qty":       current_qty,
            "total_reorder":     agg["total_reorder"],
            "total_max":         agg["total_max"],
            "days_left_display": days_left_display,
            "suggested_order":   suggested_order,
            "is_out_of_stock":   current_qty <= 0,
        })

    items.sort(key=lambda x: (not x["is_out_of_stock"], x["current_qty"]))

    return {
        "items": items,
        "summary": {
            "out_of_stock":    out_of_stock_count,
            "low_stock":       low_stock_count,
            "estimated_value": round(estimated_value, 2),
        },
    }
