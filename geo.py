# geo.py
import os
import math
import httpx
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Africa/Lagos")
AWS_LOCATION_API_KEY = os.environ.get("AWS_LOCATION_API_KEY")
AWS_LOCATION_REGION = os.environ.get("AWS_LOCATION_REGION", "eu-west-1")

def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.asin(math.sqrt(a))

def is_peak_hour(order_time: datetime, peak_settings: list) -> bool:
    if not order_time:
        order_time = datetime.now(LOCAL_TZ)
    elif order_time.tzinfo is None:
        order_time = order_time.replace(tzinfo=LOCAL_TZ)
    else:
        order_time = order_time.astimezone(LOCAL_TZ)

    dow = order_time.weekday()
    hour_min = order_time.strftime("%H:%M")
    
    for setting in peak_settings:
        if setting.get("day_of_week") is not None and setting["day_of_week"] != dow:
            continue
        start = setting.get("start_time")
        end = setting.get("end_time")
        if start and end:
            if str(start)[:5] <= hour_min <= str(end)[:5]:
                return True
    return False

async def proxy_aws_places(endpoint: str, body: dict) -> dict:
    if not AWS_LOCATION_API_KEY:
        raise ValueError("AWS Location not configured")
    url = f"https://places.geo.{AWS_LOCATION_REGION}.amazonaws.com/v2/{endpoint}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, params={"key": AWS_LOCATION_API_KEY}, json=body)
    if resp.status_code != 200:
        logger.error(f"AWS Places error: {resp.text}")
        raise ValueError(f"Places API error: {resp.status_code}")
    return resp.json()

async def calculate_intelligent_fee(
    org_id: str, base_fee: int, order_value: int, items: list, 
    order_time: datetime, customer_email: str, db_client
) -> dict:
    """Ported from Hot Portion, adapted for bOS org-scoping"""
    fee = base_fee
    value_discount = 0
    item_surcharge = 0
    peak_surcharge = 0
    loyalty_discount = 0
    volume_surcharge = 0
    minimum_fee = 500

    # 1. Fetch product details for weight/bulky logic
    inv_ids = [i.get("inventory_id") for i in items if i.get("inventory_id")]
    prod_map = {}
    if inv_ids:
        res = await db_client.table("inventory").select("id, weight_kg, handling_category").in_("id", inv_ids).execute()
        prod_map = {p["id"]: p for p in (res.data or [])}

    main_count, total_weight, bulky_count = 0, 0.0, 0
    total_items = sum(i.get("quantity", 1) for i in items)

    for item in items:
        prod = prod_map.get(item.get("inventory_id", 0), {})
        main_count += item.get("quantity", 1)
        total_weight += float(prod.get("weight_kg") or 0.5) * item.get("quantity", 1)
        if prod.get("handling_category") == "bulky":
            bulky_count += item.get("quantity", 1)

    # 2. Volume/Weight Surcharges
    if total_items >= 10: volume_surcharge += 500
    elif total_items >= 6: volume_surcharge += 300
    elif total_items >= 4: volume_surcharge += 150
    
    if total_weight > 5.0:
        volume_surcharge += int((total_weight - 5.0) * 100)
    if bulky_count > 0:
        volume_surcharge += bulky_count * 200

    # 3. Item Surcharge Rules
    rules_res = await db_client.table("delivery_item_surcharge_rules").select("*").eq("org_id", org_id).execute()
    for rule in (rules_res.data or []):
        min_i, max_i = rule.get("min_main_items"), rule.get("max_main_items")
        if (min_i is None or main_count >= min_i) and (max_i is None or main_count <= max_i):
            item_surcharge += rule.get("surcharge_amount", 0)
            break

    # 4. Peak Settings
    peak_res = await db_client.table("delivery_peak_settings").select("*").eq("org_id", org_id).eq("is_active", True).execute()
    if is_peak_hour(order_time, peak_res.data or []):
        peak_surcharge = 200

    # 5. Loyalty Discount
    if customer_email:
        loy_res = await db_client.table("delivery_loyalty_settings").select("*").eq("org_id", org_id).eq("is_active", True).limit(1).execute()
        if loy_res.data:
            setting = loy_res.data[0]
            orders_res = await db_client.table("sales").select("id", count="exact").eq("org_id", org_id).eq("customer_email", customer_email).in_("status", ["paid", "confirmed", "completed"]).execute()
            if (orders_res.count or 0) >= setting.get("min_orders", 5):
                disc_pct = min(setting.get("discount_percentage", 20), 15)
                loyalty_discount = int(fee * disc_pct / 100)
                fee -= loyalty_discount

    fee += volume_surcharge + item_surcharge + peak_surcharge

    # 6. Value Discounts
    val_res = await db_client.table("delivery_fee_rules").select("*").eq("org_id", org_id).order("min_order_value").execute()
    for rule in (val_res.data or []):
        min_v, max_v = rule.get("min_order_value", 0), rule.get("max_order_value")
        if order_value >= min_v and (max_v is None or order_value <= max_v):
            if rule.get("free_delivery"):
                value_discount = fee
                fee = 0
            else:
                new_fee = fee * rule.get("fee_multiplier", 1.0) - rule.get("fee_discount", 0)
                value_discount = fee - new_fee
                fee = max(0, new_fee)
            break

    if fee > 0 and fee < minimum_fee:
        fee = minimum_fee

    return {
        "base_fee": base_fee,
        "volume_surcharge": volume_surcharge,
        "item_surcharge": item_surcharge,
        "peak_surcharge": peak_surcharge,
        "loyalty_discount": loyalty_discount,
        "value_discount": value_discount,
        "final_fee": round(fee),
        "breakdown": {
            "base": base_fee,
            "volume_surcharge": volume_surcharge,
            "item_surcharge": item_surcharge,
            "peak_surcharge": peak_surcharge,
            "loyalty_discount": -loyalty_discount,
            "value_discount": -value_discount,
            "final": round(fee)
        }
    }
