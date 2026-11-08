# tracking.py
import os
import json
import asyncio
from datetime import datetime, timezone

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from fastapi import APIRouter, Depends, HTTPException, Request

from deps import (
    logger,
    get_supabase,
    run_sync_db_call,
    fetch_one,
    require_role,
    rate_limit,
    get_client_ip,
)


router = APIRouter(prefix="/delivery/track", tags=["Live Tracking"])

AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")
AWS_TRACKER_NAME = os.environ.get("AWS_TRACKER_NAME")
AWS_GEOFENCE_COLLECTION_NAME = os.environ.get("AWS_GEOFENCE_COLLECTION_NAME")
AWS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET = os.environ.get("AWS_SECRET_ACCESS_KEY")
GEOFENCE_WEBHOOK_SECRET = os.environ.get("GEOFENCE_WEBHOOK_SECRET")


# Dispatch state machine — driver role is constrained to these
# transitions. owner / admin / logistics retain override authority
# (they still hit the status whitelist in advance_status).
VALID_DRIVER_TRANSITIONS = {
    "confirmed":  ["picked", "cancelled"],
    "dispatched": ["picked", "cancelled"],
    "picked":     ["in_transit", "cancelled"],
    "in_transit": ["delivered", "failed"],
}


async def fire_aws_geofence_event(driver_id: str, lat: float, lng: float, accuracy: float, timestamp: str):
    """Push a driver position to AWS Tracker so geofences evaluate instantly."""
    if not AWS_TRACKER_NAME:
        return
    url = f"https://tracking.geo.{AWS_REGION}.amazonaws.com/tracking/v0/trackers/{AWS_TRACKER_NAME}/positions"
    payload = {
        "Updates": [{
            "DeviceId": driver_id,
            "Position": [lng, lat],
            "SampleTime": timestamp,
            "Accuracy": {"Horizontal": accuracy} if accuracy else {},
        }]
    }
    try:
        req = AWSRequest(
            method="POST", url=url, data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        SigV4Auth(boto3.Session().get_credentials(), "geo", AWS_REGION).add_auth(req)
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, data=req.body, headers=dict(req.headers))
    except Exception as e:
        logger.error(f"AWS Tracker sync failed for {driver_id}: {e}")


@router.post("/location")
async def push_location(
    payload: dict,
    user_data = Depends(require_role(["driver", "logistics"])),
):
    user_id, org_id, role = user_data
    client = get_supabase()

    try:
        lat = float(payload["lat"])
        lng = float(payload["lng"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "lat and lng are required numeric fields")

    acc = payload.get("accuracy")
    bat = payload.get("battery")
    chg = payload.get("is_charging")
    now = datetime.now(timezone.utc).isoformat()
    driver_id = user_id

    await run_sync_db_call(
        client.table("driver_locations").upsert({
            "org_id": org_id,
            "driver_id": driver_id,
            "lat": lat,
            "lng": lng,
            "accuracy": acc,
            "battery": bat,
            "is_charging": chg,
            "updated_at": now,
        }, on_conflict="org_id,driver_id").execute
    )

    asyncio.create_task(fire_aws_geofence_event(driver_id, lat, lng, acc, now))

    return {"status": "ok"}


@router.get("/public/{tracking_code}")
async def public_track(tracking_code: str, request: Request):
    await rate_limit(get_client_ip(request), request=request)
    client = get_supabase()

    # driver_locations has no FK path from sales, so we do it in two
    # queries rather than rely on PostgREST embed inference.
    sale_res = await run_sync_db_call(
        client.table("sales").select(
            "id, status, shipping_address, created_at, assigned_driver_id, "
            "profiles!assigned_driver_id(first_name, last_name, phone)"
        ).eq("receipt_number", tracking_code).maybe_single().execute
    )
    if not sale_res or not sale_res.data:
        raise HTTPException(404, "Order not found")

    order = sale_res.data
    driver = order.get("profiles") or {}
    driver_loc = None

    if order.get("assigned_driver_id"):
        loc_res = await run_sync_db_call(
            client.table("driver_locations")
            .select("lat, lng, updated_at")
            .eq("driver_id", order["assigned_driver_id"])
            .maybe_single()
            .execute
        )
        if loc_res and loc_res.data:
            driver_loc = loc_res.data

    driver_name = None
    if driver:
        first = driver.get("first_name") or ""
        last = driver.get("last_name") or ""
        driver_name = f"{first} {last}".strip() or None

    return {
        "tracking_code": tracking_code,
        "status": order["status"],
        "delivery_address": order.get("shipping_address"),
        "created_at": order.get("created_at"),
        "driver": {"name": driver_name, "phone": driver.get("phone")} if driver else None,
        "position": driver_loc,
    }


@router.patch("/status/{sale_id}")
async def advance_status(
    request: Request,
    sale_id: str,
    payload: dict,
    user_data = Depends(require_role(["driver", "owner", "admin", "logistics"])),
):
    # Local import — tracking.py is imported at the top of main.py, so
    # main is only partially loaded at module-import time.
    # resolve_request_branch is defined later in main.py, so we defer
    # the import to request time when main is fully loaded.
    from main import resolve_request_branch  # noqa: E402

    user_id, org_id, role = user_data
    next_status = payload.get("status")

    if next_status not in ["picked", "in_transit", "delivered", "cancelled", "failed"]:
        raise HTTPException(400, "Invalid status")

    # Branch scope for non-driver roles only. Drivers are already
    # gated by assigned_driver_id — that's stricter than branch, and a
    # driver may legitimately be assigned to a branch's order without
    # being a member of that branch.
    selected_branch = None
    if role in ("owner", "admin", "logistics"):
        selected_branch = await resolve_request_branch(request, user_id, org_id, role)

    client = get_supabase()

    q = (
        client.table("sales")
        .select("status, assigned_driver_id")
        .eq("id", sale_id)
        .eq("org_id", org_id)
    )
    if selected_branch:
        q = q.eq("branch_id", selected_branch)

    sale = await fetch_one(q.maybe_single())
    if not sale:
        # 404, not 403 — a wrong-branch sale and a nonexistent sale
        # are indistinguishable to the caller. No cross-tenant info leak.
        raise HTTPException(404, "Sale not found")

    if role == "driver" and sale["assigned_driver_id"] != user_id:
        raise HTTPException(403, "Not your order")

    current = sale["status"]
    if role == "driver":
        allowed = VALID_DRIVER_TRANSITIONS.get(current, [])
        if next_status not in allowed:
            raise HTTPException(400, f"Invalid transition from {current} to {next_status}")

    now = datetime.now(timezone.utc).isoformat()
    upd = {"status": next_status, "updated_at": now}
    if next_status == "picked":     upd["picked_at"] = now
    if next_status == "in_transit": upd["dispatched_at"] = now
    if next_status == "delivered":  upd["delivered_at"] = now

    await run_sync_db_call(
        client.table("sales").update(upd).eq("id", sale_id).execute
    )

    await run_sync_db_call(
        client.table("sale_events").insert({
            "org_id": org_id,
            "sale_id": sale_id,
            "from_status": current,
            "to_status": next_status,
            "changed_by": user_id,
        }).execute
    )

    return {"status": next_status}


@router.post("/webhook/aws")
async def aws_geofence_webhook(request: Request):
    if not GEOFENCE_WEBHOOK_SECRET:
        logger.error("aws_geofence_webhook: GEOFENCE_WEBHOOK_SECRET not set — refusing all calls")
        raise HTTPException(503, "Geofence webhook not configured")
    if request.headers.get("x-webhook-secret") != GEOFENCE_WEBHOOK_SECRET:
        raise HTTPException(401, "Unauthorized")

    event = await request.json()
    detail = event.get("detail", {})

    aws_geofence_id = detail.get("GeofenceId")
    driver_id = detail.get("DeviceId")
    event_type_raw = detail.get("EventType", "")
    position = detail.get("Position")

    if not aws_geofence_id or not driver_id or not event_type_raw or not position:
        raise HTTPException(400, "Missing fields")

    event_type = event_type_raw.lower()
    if event_type not in ("enter", "exit"):
        return {"status": "ignored", "reason": f"unknown event type: {event_type_raw}"}

    try:
        lng, lat = position
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid position payload")

    client = get_supabase()

    fence = await fetch_one(
        client.table("geofences")
        .select("id, org_id")
        .eq("aws_geofence_id", aws_geofence_id)
        .maybe_single()
    )
    if not fence:
        return {"status": "ignored", "reason": "unknown geofence"}

    try:
        await run_sync_db_call(
            client.table("geofence_events").insert({
                "org_id": fence["org_id"],
                "geofence_id": fence["id"],
                "driver_id": driver_id,
                "event_type": event_type,
                "lat": lat,
                "lng": lng,
                "aws_event_id": detail.get("EventId"),
                "occurred_at": detail.get("SampleTime") or datetime.now(timezone.utc).isoformat(),
            }).execute
        )
    except Exception as e:
        if "23505" in str(e) or "duplicate" in str(e).lower():
            return {"status": "duplicate"}
        logger.error(f"AWS geofence webhook insert failed: {e}")
        raise HTTPException(500, "Insert failed")

    return {"status": "ok"}
