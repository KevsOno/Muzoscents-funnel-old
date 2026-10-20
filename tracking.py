# tracking.py
import os
import httpx
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from fastapi import APIRouter, Depends, HTTPException, Request
from datetime import datetime, timezone

router = APIRouter(prefix="/delivery/track", tags=["Live Tracking"])

AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")
AWS_TRACKER_NAME = os.environ.get("AWS_TRACKER_NAME")
AWS_GEOFENCE_COLLECTION_NAME = os.environ.get("AWS_GEOFENCE_COLLECTION_NAME")
AWS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET = os.environ.get("AWS_SECRET_ACCESS_KEY")

async def fire_aws_geofence_event(driver_id: str, lat: float, lng: float, accuracy: float, timestamp: str):
    """Asynchronously sync position to AWS Tracker so geofences evaluate instantly."""
    if not AWS_TRACKER_NAME: return
    
    url = f"https://tracking.geo.{AWS_REGION}.amazonaws.com/tracking/v0/trackers/{AWS_TRACKER_NAME}/positions"
    payload = {
        "Updates": [{
            "DeviceId": driver_id,
            "Position": [lng, lat], # AWS requires [lng, lat]
            "SampleTime": timestamp,
            "Accuracy": {"Horizontal": accuracy} if accuracy else {}
        }]
    }
    
    req = AWSRequest(method="POST", url=url, data=json.dumps(payload), headers={"Content-Type": "application/json"})
    SigV4Auth(boto3.Session().get_credentials(), "geo", AWS_REGION).add_auth(req)
    
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, data=req.body, headers=dict(req.headers))
        except Exception as e:
            logger.error(f"AWS Tracker sync failed for {driver_id}: {e}")

@router.post("/location")
async def push_location(payload: dict, user_data = Depends(require_role(["driver", "logistics"]))):
    """Replaces LogiFlow's upsert_driver_location RPC"""
    user_id, org_id, role = user_data
    client = get_supabase()
    
    # In bOS, the user_id is the auth ID, we need the profile ID for driver_id
    # Depending on your schema, you might use user_id directly or query profiles.
    # Assuming user_id maps directly to driver_id for Dispatch profiles.
    driver_id = user_id
    
    lat, lng = payload["lat"], payload["lng"]
    acc = payload.get("accuracy")
    bat = payload.get("battery")
    chg = payload.get("is_charging")
    now = datetime.now(timezone.utc).isoformat()

    # 1. Upsert to Postgres
    await run_sync_db_call(
        client.table("driver_locations").upsert({
            "org_id": org_id, "driver_id": driver_id, "lat": lat, "lng": lng,
            "accuracy": acc, "battery": bat, "is_charging": chg, "updated_at": now
        }, on_conflict="org_id, driver_id").execute
    )

    # 2. Fire-and-forget to AWS (non-blocking)
    import asyncio
    asyncio.create_task(fire_aws_geofence_event(driver_id, lat, lng, acc, now))
    
    return {"status": "ok"}

@router.get("/public/{tracking_code}")
async def public_track(tracking_code: str, request: Request):
    """Replaces LogiFlow's track_order RPC"""
    await rate_limit(get_client_ip(request))
    client = get_supabase()

    # Fetch Order
    res = await run_sync_db_call(
        client.table("sales").select(
            "status, delivery_address, created_at, dispatched_at, delivered_at, assigned_driver_id, branches(name), profiles(full_name, phone), driver_locations(lat, lng, updated_at)"
        ).eq("receipt_number", tracking_code).execute()
    )
    if not res.data:
        raise HTTPException(404, "Order not found")
        
    order = res.data[0]
    driver_loc = order.get("driver_locations")
    
    return {
        "tracking_code": tracking_code,
        "status": order["status"],
        "delivery_address": order["delivery_address"],
        "created_at": order["created_at"],
        "driver": {
            "name": order.get("profiles", {}).get("full_name"),
            "phone": order.get("profiles", {}).get("phone"),
        } if order.get("profiles") else None,
        "position": {
            "lat": driver_loc["lat"],
            "lng": driver_loc["lng"],
            "updated_at": driver_loc["updated_at"]
        } if driver_loc else None
    }

@router.patch("/status/{sale_id}")
async def advance_status(sale_id: str, payload: dict, user_data = Depends(require_role(["driver", "owner", "admin", "logistics"]))):
    """Replaces LogiFlow's advance_order_status RPC"""
    user_id, org_id, role = user_data
    next_status = payload.get("status")
    
    if next_status not in ["picked", "in_transit", "delivered", "cancelled", "failed"]:
        raise HTTPException(400, "Invalid status")

    client = get_supabase()
    
    # Verify driver ownership
    sale = await fetch_one(client.table("sales").select("status, assigned_driver_id").eq("id", sale_id).eq("org_id", org_id).maybe_single())
    if not sale: raise HTTPException(404, "Sale not found")
    
    if role == "driver" and sale["assigned_driver_id"] != user_id:
        raise HTTPException(403, "Not your order")

    # Map timestamps
    upd = {"status": next_status, "updated_at": datetime.now(timezone.utc).isoformat()}
    if next_status == "picked": upd["picked_at"] = upd["updated_at"]
    if next_status == "in_transit": upd["dispatched_at"] = upd["updated_at"]
    if next_status == "delivered": upd["delivered_at"] = upd["updated_at"]

    await run_sync_db_call(
        client.table("sales").update(upd).eq("id", sale_id).execute()
    )
    
    # Audit log
    await run_sync_db_call(
        client.table("sale_events").insert({
            "org_id": org_id, "sale_id": sale_id, 
            "from_status": sale["status"], "to_status": next_status, "changed_by": user_id
        }).execute()
    )
    
    return {"status": next_status}
