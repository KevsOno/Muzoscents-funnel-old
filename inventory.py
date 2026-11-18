from fastapi import APIRouter, Depends, HTTPException, Request, Query, File, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime, timezone, date, timedelta
import uuid
import csv
import io
import re

from deps import (
    logger, get_supabase, get_admin_supabase, run_sync_db_call,
    get_client_ip, rate_limit, require_role, require_feature,
    resolve_request_branch, resolve_request_branch_for_write,
    check_org_feature, _assert_storefront_live,
    get_location_for_channel, get_active_sale_prices,
    fetch_inventory_scoped_to_location,
    resolve_store_org,
)

router = APIRouter(tags=["Inventory"])

# ==========================================
# MODELS & HELPERS
# ==========================================
class InventoryItem(BaseModel):
    item_code: Optional[str] = None
    description: str
    product_group: Optional[str] = None
    price_naira: float
    current_qty: Optional[int] = 0
    image_url: Optional[str] = None
    cost_price_naira: Optional[float] = 0.0
    weight_kg: Optional[float] = 0.0
    size_factor: Optional[float] = 1.0
    handling_category: Optional[str] = "standard"

    expiry_date: Optional[str] = None
    batch_number: Optional[str] = None
    lot_number: Optional[str] = None
    manufacture_date: Optional[str] = None
    supplier_name: Optional[str] = None
    supplier_invoice: Optional[str] = None

    @validator('handling_category')
    def validate_handling_category(cls, v):
        allowed = {"standard", "fragile", "bulky", "hazardous"}
        if v and v not in allowed:
            raise ValueError(f"handling_category must be one of {allowed}")
        return v


# ------------------------------------------------------------------
# OPTIMIZED STREAMING EXPORT (Backend CSV Generation)
# ------------------------------------------------------------------
@router.get("/inventory/export-csv")
async def export_inventory_csv(
    request: Request,
    location_id: Optional[str] = None,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    _, org_id, _ = user_data
    client = get_supabase()

    async def generate_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow(["SKU", "Description", "Category", "Price (NGN)", "Cost (NGN)", "Current Stock", "Handling Category", "Weight (kg)", "Expiry Date"])
        yield output.getvalue()
        output.seek(0); output.truncate(0)

        last_id = 0
        chunk_size = 2000
        
        while True:
            if location_id:
                query = client.table("inventory") \
                    .select("id, item_code, description, product_group, price_naira, cost_price_naira, handling_category, weight_kg, expiry_date, location_stocks!inner(quantity)") \
                    .eq("org_id", org_id) \
                    .eq("location_stocks.location_id", location_id) \
                    .gt("id", last_id) \
                    .order("id", desc=False) \
                    .limit(chunk_size)
            else:
                query = client.table("inventory") \
                    .select("id, item_code, description, product_group, price_naira, cost_price_naira, current_qty, handling_category, weight_kg, expiry_date") \
                    .eq("org_id", org_id) \
                    .gt("id", last_id) \
                    .order("id", desc=False) \
                    .limit(chunk_size)

            res = await run_sync_db_call(query.execute)
            rows = res.data or []
            if not rows: break

            for row in rows:
                qty = row.get("current_qty", 0) if not location_id else sum(int(s.get("quantity") or 0) for s in (row.get("location_stocks") or []))
                writer.writerow([
                    row.get("item_code", ""), row.get("description", ""), row.get("product_group", ""),
                    row.get("price_naira", 0), row.get("cost_price_naira", 0), qty,
                    row.get("handling_category", "standard"), row.get("weight_kg", 0), row.get("expiry_date", "")
                ])
            
            last_id = rows[-1]["id"]
            yield output.getvalue()
            output.seek(0); output.truncate(0)

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=inventory_export_{datetime.now().date()}.csv"}
    )

@router.get("/inventory")
async def get_inventory(request: Request, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "sales_rep", "finance"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    result = await run_sync_db_call(client.table("inventory").select("*").eq("org_id", org_id).order("id", desc=False).execute)
    return result.data

@router.post("/inventory")
async def create_inventory_item(
    request: Request,
    item: InventoryItem,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    data = item.dict()
    data["org_id"] = org_id
    data["created_by"]  = user_id
    data["created_via"] = "inventory_manual"
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Deprecated columns: strip from the inventory payload before insert.
    # The batch table (inventory_batches) is the authoritative home for
    # expiry and batch identity. Existing clients still send these on the
    # Pydantic model; the values are read into locals below and routed
    # into the batch resolver, but never written to inventory.
    expiry_date  = data.pop("expiry_date", None)
    batch_number = data.pop("batch_number", None)
    lot_number   = data.get("lot_number")

    if expiry_date and not batch_number:
        batch_number = await get_next_auto_batch_number()
        if not lot_number:
            lot_number = "LEGACY-IMPORT"
            data["lot_number"] = lot_number

    inv_result = await run_sync_db_call(client.table("inventory").insert(data).execute)
    if not inv_result.data:
        raise HTTPException(status_code=500, detail="Failed to create inventory item")
    new_inv = inv_result.data[0]

    # ── Resolve or create the batch ──
    batch_row = await _resolve_or_create_batch(
        client=client,
        inventory_id=new_inv["id"],
        batch_number=batch_number,
        expiry_date=expiry_date,
        lot_number=data.get("lot_number"),
        manufacture_date=data.get("manufacture_date"),
        cost_price_naira=data.get("cost_price_naira"),
        supplier_name=data.get("supplier_name"),
        supplier_invoice=data.get("supplier_invoice"),
        received_quantity=int(data.get("current_qty") or 0),
    )

    # ── Write the location_stocks row through the shared helper ──
    try:
        main_location = await run_sync_db_call(
            client.table("locations")
            .select("id")
            .eq("org_id", org_id)
            .eq("is_warehouse", True)
            .maybe_single()
            .execute
        )
        if main_location and main_location.data:
            await _write_location_stock(
                client=client,
                location_id=main_location.data["id"],
                inventory_id=new_inv["id"],
                batch_id=batch_row["id"],
                quantity_delta=int(data.get("current_qty") or 0),
            )
    except Exception as loc_err:
        logger.error(f"Failed to create location stock for inv={new_inv['id']}: {loc_err}")

    return new_inv

@router.put("/inventory/{item_id}")
async def update_inventory(
    request: Request,
    item_id: int,
    item: InventoryItem,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    existing = await run_sync_db_call(
        client.table("inventory")
        .select("id, current_qty")
        .eq("id", item_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )

    if not existing.data:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    update_data = {k: v for k, v in item.dict().items() if v is not None}
    # Deprecated columns: never write them back to inventory. The batch
    # table is authoritative. Existing clients still send them; the
    # values are read from the Pydantic model directly and routed into
    # the batch resolver.
    update_data.pop("expiry_date", None)
    update_data.pop("batch_number", None)
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    new_expiry = item.expiry_date
    new_batch  = item.batch_number
    new_lot    = item.lot_number

    old_qty = int(existing.data.get("current_qty") or 0)
    new_qty = int(item.current_qty if item.current_qty is not None else old_qty)

    # ── Determine which batch the location_stocks delta applies to. ──
    # Precedence: caller-named batch > earliest-expiring existing batch
    # for this inventory. Replaces the deprecated inventory.batch_number
    # read with a lookup against the authoritative inventory_batches.
    target_batch_number = new_batch
    resolved_expiry     = new_expiry
    if not target_batch_number:
        current_batch_res = await run_sync_db_call(
            client.table("inventory_batches")
            .select("batch_number, expiry_date")
            .eq("inventory_id", item_id)
            .order("expiry_date", desc=False)
            .limit(1)
            .execute
        )
        if current_batch_res and current_batch_res.data:
            target_batch_number = current_batch_res.data[0].get("batch_number")
            if not resolved_expiry:
                resolved_expiry = current_batch_res.data[0].get("expiry_date")

    # ── Resolve or create the batch through the shared helper. ──
    batch_row = await _resolve_or_create_batch(
        client=client,
        inventory_id=item_id,
        batch_number=target_batch_number,
        expiry_date=resolved_expiry,
        lot_number=new_lot,
        manufacture_date=item.manufacture_date,
        cost_price_naira=item.cost_price_naira,
        supplier_name=item.supplier_name,
        supplier_invoice=item.supplier_invoice,
        received_quantity=0,
    )

    # ── Apply the location_stocks delta FIRST. ──
    delta = new_qty - old_qty
    if delta != 0:
        try:
            main_location = await run_sync_db_call(
                client.table("locations")
                .select("id")
                .eq("org_id", org_id)
                .eq("is_warehouse", True)
                .maybe_single()
                .execute
            )
            if main_location and main_location.data:
                await _write_location_stock(
                    client=client,
                    location_id=main_location.data["id"],
                    inventory_id=item_id,
                    batch_id=batch_row["id"],
                    quantity_delta=delta,
                )
            else:
                logger.warning(
                    f"update_inventory: no warehouse location for org {org_id}, "
                    f"location_stocks not reconciled for inv {item_id} (delta={delta})"
                )
        except HTTPException:
            raise
        except Exception as loc_err:
            logger.error(
                f"update_inventory: failed to reconcile location_stocks "
                f"for inv {item_id}: {loc_err}"
            )

    result = await run_sync_db_call(
        client.table("inventory")
        .update(update_data)
        .eq("id", item_id)
        .eq("org_id", org_id)
        .execute
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    return result.data[0]

@router.delete("/inventory/{item_id}")
async def delete_inventory(request: Request, item_id: int, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    result = await run_sync_db_call(client.table("inventory").delete().eq("id", item_id).eq("org_id", org_id).execute)
    if not result.data:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return {"message": "Deleted successfully"}

# ------------------------------------------------------------------
# PUBLIC INVENTORY ENDPOINTS (no authentication required)
# ------------------------------------------------------------------

@router.get("/inventory/public-list")
async def public_inventory(
    request: Request,
    org_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    sort_by: str = Query("newest"),
):
    await rate_limit(get_client_ip(request))

    resolved_org_id = await resolve_store_org(request, org_id=org_id)
    if not resolved_org_id:
        raise HTTPException(status_code=400, detail="Organisation not specified")

    # Suspension is unconditional. A suspended org's storefront data
    # endpoints are dark regardless of ENFORCE_FEATURES. 404, not 402,
    # so a visitor cannot probe billing status.
    await _assert_storefront_live(resolved_org_id)
    await check_org_feature(resolved_org_id, "ecommerce")

    online_location_id = await get_location_for_channel(resolved_org_id, "online")

    if not online_location_id:
        logger.warning(
            f"/inventory/public-list: no online location for org "
            f"{resolved_org_id}, falling back to legacy global read"
        )
        client = get_supabase()
        query = client.table("inventory").select("*", count="exact") \
            .eq("org_id", resolved_org_id).gt("current_qty", 0)
        if q:
            query = query.ilike("description", f"%{q}%")
        if category:
            query = query.eq("product_group", category)
        query = query.range(offset, offset + limit - 1)
        fallback = await run_sync_db_call(query.execute)
        items = fallback.data or []

        # ── Flash-sale price override ──
        sale_map = await get_active_sale_prices(
            resolved_org_id, [it["id"] for it in items]
        )
        for it in items:
            s = sale_map.get(it["id"])
            if s:
                it["base_price_naira"]    = it.get("price_naira")
                it["price_naira"]         = s["sale_price"]
                it["on_sale"]             = True
                it["sale_name"]           = s["sale_name"]
                it["sale_ends_at"]        = s["ends_at"]
                it["discount_pct"]        = (
                    round(((s["original_price"] - s["sale_price"]) / s["original_price"]) * 100, 1)
                    if s["original_price"] > 0 else 0
                )
            else:
                it["on_sale"] = False

        return {
            "items": items,
            "total": fallback.count or 0,
            "location_id": None,
            "org_id": resolved_org_id,
        }

    items, total = await fetch_inventory_scoped_to_location(
        org_id=resolved_org_id,
        location_id=str(online_location_id),
        limit=limit,
        offset=offset,
        q=q,
        category=category,
        sort_by=sort_by,
        require_positive_stock=True,
    )

    # ── Flash-sale price override ──
    sale_map = await get_active_sale_prices(
        resolved_org_id, [it["id"] for it in items]
    )
    for it in items:
        s = sale_map.get(it["id"])
        if s:
            it["base_price_naira"]    = it.get("price_naira")
            it["price_naira"]         = s["sale_price"]
            it["on_sale"]             = True
            it["sale_name"]           = s["sale_name"]
            it["sale_ends_at"]        = s["ends_at"]
            it["discount_pct"]        = (
                round(((s["original_price"] - s["sale_price"]) / s["original_price"]) * 100, 1)
                if s["original_price"] > 0 else 0
            )
        else:
            it["on_sale"] = False

    return {
        "items": items,
        "total": total,
        "location_id": str(online_location_id),
        "org_id": resolved_org_id,
    }


@router.get("/inventory/public-categories")
async def public_categories(
    request: Request,
    org_id: Optional[str] = Query(None),
):
    await rate_limit(get_client_ip(request))
    resolved_org_id = await resolve_store_org(request, org_id=org_id)
    if not resolved_org_id:
        raise HTTPException(status_code=400, detail="Organisation not specified")

    # Suspension is unconditional — see _assert_storefront_live.
    await _assert_storefront_live(resolved_org_id)
    await check_org_feature(resolved_org_id, "ecommerce")

    online_location_id = await get_location_for_channel(resolved_org_id, "online")
    client = get_supabase()

    if not online_location_id:
        result = await run_sync_db_call(
            client.table("inventory")
            .select("product_group")
            .eq("org_id", resolved_org_id)
            .gt("current_qty", 0)
            .execute
        )
        groups = {row["product_group"] for row in result.data if row.get("product_group")}
        return {"categories": sorted(list(groups)), "location_id": None, "org_id": resolved_org_id}

    ls_result = await run_sync_db_call(
        client.table("location_stocks")
        .select("quantity, inventory:inventory_id(product_group, org_id)")
        .eq("location_id", str(online_location_id))
        .gt("quantity", 0)
        .execute
    )
    groups = set()
    for row in (ls_result.data or []):
        inv = row.get("inventory") or {}
        if inv.get("org_id") and str(inv["org_id"]) != str(resolved_org_id):
            continue
        pg = inv.get("product_group")
        if pg:
            groups.add(pg)
    return {
        "categories": sorted(groups),
        "location_id": str(online_location_id),
        "org_id": resolved_org_id,
    }


@router.get("/inventory/pos")
async def pos_inventory(
    request: Request,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None, description="Override the POS channel's default location"),
    skip_count: bool = Query(
        False,
        description=(
            "Skip COUNT(*). Use on pages > 0 during a full catalog sync — "
            "the sync loop terminates on an empty page, so only page 0 "
            "needs the total. Saves one COUNT per page on 15k+ SKU catalogs."
        ),
    ),
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data

    resolved_location_id = location_id
    if not resolved_location_id:
        resolved_location_id = await get_location_for_channel(org_id, "pos")

    # ── Fallback: no POS location resolved ──
    if not resolved_location_id:
        logger.warning(f"/inventory/pos: no location resolved for org {org_id}, falling back to global inventory")
        client = get_supabase()
        query = client.table("inventory").select(
            "*",
            count="planned" if not skip_count else None,
        ).eq("org_id", org_id)
        if q:
            or_condition = f"description.ilike.%{q}%,item_code.ilike.%{q}%,product_group.ilike.%{q}%"
            inner = getattr(query, "_inner", query)
            inner.params = inner.params.set("or", f"({or_condition})")
        result = await run_sync_db_call(query.range(offset, offset + limit - 1).execute)
        return {
            "items": result.data or [],
            "total": (result.count or 0) if not skip_count else len(result.data or []),
            "location_id": None,
        }

    # ── Primary path: location-scoped read ──
    #
    # include_count semantics:
    #   skip_count=False → include_count=True  → PostgREST issues COUNT(*),
    #                     result.count is populated, `total` is accurate.
    #                     Required on page 0 (populates CATALOG_EXPECTED_KEY)
    #                     and on every search page (drives infinite scroll).
    #   skip_count=True  → include_count=False → no COUNT(*). `total` is 0.
    #                     Safe only on sync pages 1+ where the loop
    #                     terminates on `pageItems.length === 0`.
    items, total = await fetch_inventory_scoped_to_location(
        org_id=org_id,
        location_id=str(resolved_location_id),
        limit=limit,
        offset=offset,
        q=q,
        sort_by="newest",
        require_positive_stock=False,
        include_count=not skip_count,
    )

    sale_map = await get_active_sale_prices(org_id, [it["id"] for it in items])
    for it in items:
        s = sale_map.get(it["id"])
        if s:
            it["base_price_naira"] = it.get("price_naira")
            it["price_naira"]      = s["sale_price"]
            it["on_sale"]          = True
            it["sale_name"]        = s["sale_name"]
            it["sale_ends_at"]     = s["ends_at"]
        else:
            it["on_sale"] = False

    return {"items": items, "total": total, "location_id": str(resolved_location_id)}

# ------------------------------------------------------------------
# PUBLIC STOREFRONT ENDPOINTS
# ------------------------------------------------------------------
