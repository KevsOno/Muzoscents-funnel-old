# delivery_zones.py
from fastapi import APIRouter, Depends, HTTPException, Request
from datetime import datetime, timezone

from deps import (
    get_supabase,
    run_sync_db_call,
    require_role,
    rate_limit,
    get_client_ip,
    PUBLIC_STORE_ORG_ID,
)
from geo import proxy_aws_places, calculate_intelligent_fee, resolve_delivery_coords


router = APIRouter(prefix="/api/delivery", tags=["Delivery & Zones"])


@router.post("/places/{endpoint}")
async def handle_places_proxy(endpoint: str, body: dict, request: Request):
    # Public endpoint (guest checkout must geocode). Protected only by
    # IP rate limit. Aggressive limit protects the AWS quota.
    await rate_limit(get_client_ip(request), request=request)

    if endpoint not in {"autocomplete", "geocode", "reverse-geocode"}:
        raise HTTPException(400, "Invalid endpoint")

    try:
        return await proxy_aws_places(endpoint, body)
    except ValueError as e:
        raise HTTPException(502, str(e))


@router.get("/areas")
async def get_zones(user_data = Depends(require_role(["owner", "admin", "logistics"]))):
    _, org_id, _ = user_data
    client = get_supabase()
    res = await run_sync_db_call(
        client.rpc("get_delivery_areas_geojson", {"p_org_id": org_id}).execute
    )
    return {"areas": res.data or []}


@router.post("/areas")
async def create_zone(payload: dict, user_data = Depends(require_role(["owner", "admin"]))):
    _, org_id, _ = user_data
    client = get_supabase()
    res = await run_sync_db_call(
        client.rpc("insert_delivery_area", {
            "p_org_id": org_id,
            "p_name": payload["name"],
            "p_fee": int(payload["fee"]),
            "p_geojson": payload["polygon"],
        }).execute
    )
    if not res.data:
        raise HTTPException(500, "Failed to create zone")
    return res.data[0]


@router.delete("/areas/{area_id}")
async def delete_zone(area_id: int, user_data = Depends(require_role(["owner", "admin"]))):
    """
    Delete a delivery area by id. Org-scoped: a caller can only delete
    an area belonging to their own organisation. Returns 404 when the
    id does not exist OR belongs to a different tenant — the two cases
    are indistinguishable to the caller, so this endpoint does not leak
    the existence of another tenant's area ids.

    No FK in the schema references delivery_areas, so the delete has
    no cascade side effects. Historical orders that were priced against
    this zone keep their recorded fee; the zone is only removed from
    future estimates and checkouts.
    """
    _, org_id, _ = user_data
    client = get_supabase()
    res = await run_sync_db_call(
        client.table("delivery_areas")
        .delete()
        .eq("id", area_id)
        .eq("org_id", org_id)
        .execute
    )
    if not res.data:
        raise HTTPException(404, "Area not found")
    return {"deleted": area_id}


@router.post("/estimate")
async def estimate_fee(payload: dict, request: Request):
    await rate_limit(get_client_ip(request), request=request)

    org_id = payload.get("org_id") or PUBLIC_STORE_ORG_ID
    if not org_id:
        raise HTTPException(400, "org_id is required")

    # FIX: Resolve coordinates dynamically using AWS Geocoding
    coords = await resolve_delivery_coords(
        address=payload.get("address"),
        client_lat=payload.get("lat"),
        client_lng=payload.get("lng"),
        customer_email=payload.get("customer_email")
    )

    if not coords:
        return {"covered": False, "message": "Address not found. Please check and try again."}

    lat, lng = coords
    client = get_supabase()

    zone_res = await run_sync_db_call(
        client.rpc("find_delivery_area", {
            "p_org_id": org_id,
            "p_lat": lat,
            "p_lng": lng,
        }).execute
    )
    if not zone_res.data:
        return {"covered": False, "message": "Address is outside our delivery area."}

    area = zone_res.data[0]

    fee_calc = await calculate_intelligent_fee(
        org_id=org_id,
        base_fee=area["fee"],
        order_value=int(payload.get("order_total", 0)),
        items=payload.get("items", []),
        # FIX: Timezone-aware datetime
        order_time=datetime.now(timezone.utc),
        customer_email=payload.get("customer_email"),
        db_client=client,
    )

    return {"covered": True, "area_name": area["name"], **fee_calc}
