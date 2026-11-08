from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from typing import Optional, Tuple, List
from datetime import datetime, timezone
import secrets, string
import httpx

from main import (
    get_supabase, run_sync_db_call, rate_limit, get_client_ip,
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, PRODUCTION_HOST,
    send_sendgrid_email, escape_html
)
from deps import require_role

router = APIRouter(prefix="/customers", tags=["Customers"])


class CustomerCreate(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str = Field(..., min_length=1)
    tier: str = "bronze"
    loyalty_points: int = 0
    address: Optional[str] = None


@router.get("")
async def list_customers(
    request: Request,
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    # Query the crm_customers view
    q = client.table("crm_customers").select("*", count="exact").eq("org_id", org_id)

    if search:
        q = q.or_(f"name.ilike.%{search}%,email.ilike.%{search}%,phone.ilike.%{search}%")

    res = await run_sync_db_call(q.order("created_at", desc=True).range(offset, offset + limit - 1).execute)

    return {
        "customers": res.data or [],
        "total": res.count or 0,
        "limit": limit,
        "offset": offset,
    }


@router.post("")
async def create_customer(
    request: Request,
    customer: CustomerCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data

    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=500, detail="Service role key not configured")

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as http_client:
        # ── Step 1: does a profile already exist for this email? ──
        check_url = f"{SUPABASE_URL}/rest/v1/profiles?select=id&email=eq.{customer.email}"
        check_resp = await http_client.get(check_url, headers=headers)
        existing_profiles = check_resp.json() if check_resp.status_code == 200 else []

        if existing_profiles:
            user_id = existing_profiles[0]["id"]
            created_new_user = False

            # ── Step 1a: refuse if already a member of THIS org ──
            #
            # Without this, the subsequent org_members insert fails with
            # a raw 23505 unique-constraint error that surfaces as a
            # 500 to the operator with no actionable message.
            member_check_url = (
                f"{SUPABASE_URL}/rest/v1/org_members"
                f"?select=user_id&user_id=eq.{user_id}&org_id=eq.{org_id}"
            )
            member_resp = await http_client.get(member_check_url, headers=headers)
            if member_resp.status_code == 200 and member_resp.json():
                raise HTTPException(
                    status_code=409,
                    detail="This email is already a customer of this organisation.",
                )
        else:
            # ── Step 2: create a fresh auth user + profile ──
            temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
            admin_url = f"{SUPABASE_URL}/auth/v1/admin/users"
            admin_payload = {
                "email": customer.email,
                "password": temp_password,
                "email_confirm": True,
                "user_metadata": {
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "phone": customer.phone,
                },
            }
            admin_resp = await http_client.post(admin_url, json=admin_payload, headers=headers)
            if admin_resp.status_code != 200:
                raise HTTPException(status_code=500, detail=f"Failed to create auth user: {admin_resp.text}")

            user_id = admin_resp.json().get("id")
            if not user_id:
                raise HTTPException(status_code=500, detail="Auth user created but no id returned")
            created_new_user = True

            # ── Step 2a: create the identity-only profile ──
            #
            # IMPORTANT: profiles is identity-only now. Loyalty state
            # (current_points, tier, membership_id) lives on org_leads.
            # Writing loyalty columns here silently fails with a 400
            # from PostgREST ("column does not exist"), and the profile
            # is never created — the customer then has an auth user and
            # org_members row but no profile, which breaks every
            # profile-dependent read.
            now_iso = datetime.now(timezone.utc).isoformat()
            profile_data = {
                "id": user_id,
                "email": customer.email,
                "first_name": customer.first_name,
                "last_name": customer.last_name,
                "phone": customer.phone,
                "status": "active",
                "address": customer.address,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            profile_resp = await http_client.post(
                f"{SUPABASE_URL}/rest/v1/profiles",
                json=profile_data,
                headers=headers,
            )
            if profile_resp.status_code not in (200, 201):
                # Roll back the auth user so we don't leave an orphan.
                await http_client.delete(
                    f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
                    headers=headers,
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create profile: {profile_resp.text}",
                )

        # ── Step 3: add to org_members (role: customer) ──
        member_data = {
            "user_id": user_id,
            "org_id": org_id,
            "role": "customer",
            "joined_at": datetime.now(timezone.utc).isoformat(),
        }
        member_resp = await http_client.post(
            f"{SUPABASE_URL}/rest/v1/org_members",
            json=member_data,
            headers=headers,
        )
        if member_resp.status_code not in (200, 201):
            # Roll back the newly-created auth user and profile if the
            # membership couldn't be created. Leaving orphans behind is
            # worse than failing loudly.
            if created_new_user:
                await http_client.delete(
                    f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}",
                    headers=headers,
                )
                await http_client.delete(
                    f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
                    headers=headers,
                )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to add customer to organisation: {member_resp.text}",
            )

        # ── Step 4: upsert org_leads (source of truth for crm_customers) ──
        #
        # Loyalty state goes here — current_points and tier belong on
        # org_leads, not profiles. The crm_customers view is built on
        # this table.
        client = get_supabase()
        await run_sync_db_call(
            client.table("org_leads").upsert({
                "org_id": org_id,
                "profile_id": user_id,
                "name": f"{customer.first_name} {customer.last_name}".strip(),
                "email": customer.email,
                "phone": customer.phone,
                "status": "active",
                "tier": customer.tier,
                "current_points": customer.loyalty_points,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="org_id,profile_id").execute()
        )

    # ── Step 5: welcome email with credentials for new accounts ──
    if created_new_user:
        login_link = f"{PRODUCTION_HOST}/kdsiginin"
        html = f"""
        <h2>Welcome to Kevs Digital!</h2>
        <p>Hello {escape_html(customer.first_name)},</p>
        <p>Your customer account has been created. Use the credentials below to log in:</p>
        <p><strong>Email:</strong> {customer.email}<br>
        <strong>Temporary Password:</strong> <code>{temp_password}</code></p>
        <p><a href="{login_link}">Click here to log in</a> and change your password.</p>
        """
        await send_sendgrid_email(customer.email, "Your customer account has been created", html)

    return {
        "message": "Customer processed successfully",
        "user_id": user_id,
        "created": created_new_user,
    }
