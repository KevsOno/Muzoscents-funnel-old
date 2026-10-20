# deps.py
"""
Shared dependencies and primitives for all Kevs Digital modules.

This module is the leaf of the import graph: it imports only from
external packages, never from main.py, tracking.py, delivery_zones.py,
or geo.py. That guarantees no circular imports when any of those
import from here.

Single source of truth for:
  - Environment configuration
  - Logging
  - Supabase clients (cached service role, fresh admin, fresh user)
  - Async DB helper, single-row fetcher
  - Rate limiting
  - Auth pipeline (JWT -> user_id, org_id, role)
  - Feature gates (plan tiers, overrides, suspension)
  - FastAPI dependencies (require_role, require_feature, require_feature_any)
"""

import os
import asyncio
from datetime import datetime, timezone
from typing import Optional, Tuple, List, Dict, Any
import logging

import httpx
import structlog
from fastapi import Header, HTTPException, Request, Depends
from supabase import create_client, Client


# ============================================================
# LOGGING
# ============================================================
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

if os.environ.get("STRUCTLOG_JSON", "true").lower() == "true":
    renderer = structlog.processors.JSONRenderer()
else:
    renderer = structlog.dev.ConsoleRenderer()

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        renderer,
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger()


# ============================================================
# ENVIRONMENT
# ============================================================
SUPABASE_URL                = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY           = os.environ.get("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY   = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

PUBLIC_STORE_ORG_ID = os.environ.get("PUBLIC_STORE_ORG_ID")
PRODUCTION_HOST     = os.environ.get("PRODUCTION_HOST", "https://kevsono-kevs-digital-bos.hf.space")
ADMIN_SECRET_KEY    = os.environ.get("ADMIN_SECRET_KEY", "change_this_in_production")

RATE_LIMIT_ENABLED  = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW   = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))

ENFORCE_FEATURES  = os.environ.get("ENFORCE_FEATURES", "false").lower() == "true"
ORG_SCOPE_CANARY  = os.environ.get("ORG_SCOPE_CANARY", "false").lower() == "true"


# ============================================================
# REQUEST IDENTITY
# ============================================================
def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ============================================================
# SUPABASE CLIENTS
# ============================================================
_ORG_SCOPED_TABLES = frozenset({
    "alert_log", "stock_limits", "transfer_suggestions", "products",
    "inventory", "inventory_batches", "sales", "sale_items",
    "locations", "location_stocks", "stock_transfers", "branches",
    "suppliers", "purchase_orders", "purchase_order_items", "grn", "grn_items",
    "org_leads", "support_tickets", "ticket_messages", "chat_sessions",
    "chat_messages", "general_knowledge", "knowledge_audit",
    "chart_of_accounts", "journal_entries", "journal_lines",
    "accounts_receivable", "accounts_payable", "profit_loss_summary",
    "hr_departments", "hr_employees", "hr_attendance", "hr_leave_requests",
    "hr_leave_balances", "hr_payroll",
    "system_logs", "webhook_events", "admin_audit", "audit_events",
    "delivery_areas", "delivery_fee_rules", "delivery_peak_settings",
    "delivery_loyalty_settings", "delivery_item_surcharge_rules",
    "driver_locations", "geofences", "geofence_events", "sale_events",
})

_AUTH_MUTATORS = frozenset({
    "sign_in", "sign_in_with_password", "sign_in_with_otp", "sign_up",
    "sign_out", "refresh_session", "set_session", "verify_otp",
    "reauthenticate", "reset_password_for_email",
})


class _GuardedAuth:
    __slots__ = ("_inner",)
    def __init__(self, inner):
        self._inner = inner
    def __getattr__(self, name):
        if name in _AUTH_MUTATORS:
            raise RuntimeError(
                f"auth.{name}() mutates the shared Supabase client. "
                f"Use get_user_supabase() for authentication calls."
            )
        return getattr(self._inner, name)


class _CanaryBuilder:
    __slots__ = ("_inner", "_table")
    def __init__(self, inner, table):
        self._inner = inner
        self._table = table
    def execute(self, *args, **kwargs):
        self._maybe_warn()
        return self._inner.execute(*args, **kwargs)
    def _maybe_warn(self):
        if not ORG_SCOPE_CANARY:
            return
        if self._table not in _ORG_SCOPED_TABLES:
            return
        params = getattr(self._inner, "params", None)
        if params is None:
            return
        try:
            keys = list(params.keys())
        except Exception:
            return
        for k in keys:
            if k == "org_id" or k.endswith(".org_id"):
                return
        logger.warning("org_scope_canary", table=self._table)
    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr
        def wrapped(*args, **kwargs):
            result = attr(*args, **kwargs)
            if hasattr(result, "execute"):
                return _CanaryBuilder(result, self._table)
            return result
        return wrapped


class _GuardedClient:
    __slots__ = ("_inner",)
    def __init__(self, inner):
        self._inner = inner
    def __getattr__(self, name):
        if name == "auth":
            return _GuardedAuth(self._inner.auth)
        if name == "table":
            def wrapped_table(table_name):
                builder = self._inner.table(table_name)
                if ORG_SCOPE_CANARY:
                    return _CanaryBuilder(builder, table_name)
                return builder
            return wrapped_table
        return getattr(self._inner, name)


def _force_clear_auth_session(client: Client) -> None:
    try:
        auth = client.auth
    except Exception:
        return
    for attr in ("_current_session", "_current_user"):
        try:
            if hasattr(auth, attr):
                setattr(auth, attr, None)
        except Exception:
            pass
    try:
        storage = getattr(auth, "_storage", None)
        if storage is not None:
            url = (SUPABASE_URL or "").rstrip("/")
            for key in ("supabase.auth.token", f"sb-{url}-auth-token", "gotrue.auth.token"):
                try:
                    storage.remove_item(key)
                except Exception:
                    pass
    except Exception:
        pass


supabase_client: Optional[Client] = None
last_client_check = None


def get_supabase():
    global supabase_client, last_client_check
    now = datetime.now(timezone.utc)
    if supabase_client is None or (last_client_check and (now - last_client_check).seconds > 3600):
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            if SUPABASE_ANON_KEY:
                logger.warning("SUPABASE_SERVICE_ROLE_KEY missing – falling back to anon (RLS may block)")
                raw = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
            else:
                raise RuntimeError("No Supabase credentials")
        else:
            raw = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
            logger.info("Supabase client created with SERVICE ROLE KEY (RLS bypassed)")
        _force_clear_auth_session(raw)
        supabase_client = _GuardedClient(raw)
        last_client_check = now
    return supabase_client


def get_admin_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Missing service role key for admin client")
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    _force_clear_auth_session(client)
    return client


def get_user_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("Missing anon key for user auth client")
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    _force_clear_auth_session(client)
    return client


# ============================================================
# ASYNC DB HELPERS
# ============================================================
async def run_sync_db_call(sync_func, *args, **kwargs):
    return await asyncio.to_thread(sync_func, *args, **kwargs)


async def fetch_one(query) -> Optional[Dict]:
    try:
        res = await run_sync_db_call(query.execute)
    except Exception as e:
        msg = str(e)
        if "PGRST116" in msg or "JSON object requested" in msg:
            return None
        raise
    if res is None:
        return None
    data = getattr(res, "data", None)
    if data is None:
        return None
    if isinstance(data, list):
        return data[0] if data else None
    return data


# ============================================================
# RATE LIMITING
# ============================================================
async def rate_limit(client_id: str, org_id: Optional[str] = None, request: Optional[Request] = None):
    if not RATE_LIMIT_ENABLED:
        return
    if request and request.headers.get("X-Load-Test") == "true":
        return

    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    window_start = datetime.fromtimestamp(
        (now.timestamp() // RATE_LIMIT_WINDOW) * RATE_LIMIT_WINDOW, tz=timezone.utc
    )
    try:
        query = supabase.table("rate_limits").select("request_count").eq("client_id", client_id).eq("window_start", window_start.isoformat())
        if org_id is not None:
            query = query.eq("org_id", org_id)
        existing = await run_sync_db_call(query.execute)

        if existing.data and len(existing.data) > 0:
            new_count = existing.data[0]["request_count"] + 1
            update_query = supabase.table("rate_limits").update({"request_count": new_count}).eq("client_id", client_id).eq("window_start", window_start.isoformat())
            if org_id is not None:
                update_query = update_query.eq("org_id", org_id)
            await run_sync_db_call(update_query.execute)
        else:
            insert_data = {"client_id": client_id, "window_start": window_start.isoformat(), "request_count": 1}
            if org_id is not None:
                insert_data["org_id"] = org_id
            await run_sync_db_call(supabase.table("rate_limits").insert(insert_data).execute)
            new_count = 1

        if new_count > RATE_LIMIT_REQUESTS:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rate limit error: {e}")


# ============================================================
# PLAN TIERS
# ============================================================
PLAN_TIERS: Dict[str, Dict] = {
    # ── Retail ───────────────────────────────────────────────────
    "convenience": {
        "label":         "Convenience Store",
        "vertical":      "retail",
        "monthly_naira": 150_000,
        "setup_base":    200_000,
        "max_skus":      1_500,
        "max_locations": 1,
        "features": {
            "ecommerce":       True,
            "offline_pos":     True,
            "multi_location":  False,
            "expiry_tracking": False,
            "accounting":      True,
            "hr_module":       False,
            "procurement":     True,
            "ai_assistant":    False,
            "loyalty":         True,
            "fulfillment":     False,
            "mobile_apps":     False,
            "kitchen_display": False,
            "live_dispatch":   False,
        },
    },
    "pharmacy_indie": {
        "label":         "Independent Pharmacy",
        "vertical":      "retail",
        "monthly_naira": 250_000,
        "setup_base":    200_000,
        "max_skus":      3_000,
        "max_locations": 1,
        "features": {
            "ecommerce":       True,
            "offline_pos":     True,
            "multi_location":  False,
            "expiry_tracking": True,
            "accounting":      True,
            "hr_module":       False,
            "procurement":     True,
            "ai_assistant":    False,
            "loyalty":         True,
            "fulfillment":     False,
            "mobile_apps":     False,
            "kitchen_display": False,
            "live_dispatch":   False,
        },
    },
    "pharmacy_chain": {
        "label":         "Pharmacy Chain",
        "vertical":      "retail",
        "monthly_naira": 350_000,
        "setup_base":    200_000,
        "max_skus":      5_000,
        "max_locations": 10,
        "features": {
            "ecommerce":       True,
            "offline_pos":     True,
            "multi_location":  True,
            "expiry_tracking": True,
            "accounting":      True,
            "hr_module":       True,
            "procurement":     True,
            "ai_assistant":    False,
            "loyalty":         True,
            "fulfillment":     False,
            "mobile_apps":     False,
            "kitchen_display": False,
            "live_dispatch":   False,
        },
    },
    "supermarket_med": {
        "label":         "Supermarket (Medium)",
        "vertical":      "retail",
        "monthly_naira": 400_000,
        "setup_base":    200_000,
        "max_skus":      15_000,
        "max_locations": 5,
        "features": {
            "ecommerce":       True,
            "offline_pos":     True,
            "multi_location":  True,
            "expiry_tracking": True,
            "accounting":      True,
            "hr_module":       True,
            "procurement":     True,
            "ai_assistant":    True,
            "loyalty":         True,
            "fulfillment":     True,
            "mobile_apps":     True,
            "kitchen_display": False,
            "live_dispatch":   False,
        },
    },
    "supermarket_large": {
        "label":         "Supermarket (Large)",
        "vertical":      "retail",
        "monthly_naira": 500_000,
        "setup_base":    200_000,
        "max_skus":      None,
        "max_locations": None,
        "features": {
            "ecommerce":       True,
            "offline_pos":     True,
            "multi_location":  True,
            "expiry_tracking": True,
            "accounting":      True,
            "hr_module":       True,
            "procurement":     True,
            "ai_assistant":    True,
            "loyalty":         True,
            "fulfillment":     True,
            "mobile_apps":     True,
            "kitchen_display": False,
            "live_dispatch":   False,
        },
    },

    # ── Food & Beverage ─────────────────────────────────────────
    "fb_express": {
        "label":         "F&B Express",
        "vertical":      "food",
        "monthly_naira": 220_000,
        "setup_base":    750_000,
        "max_skus":      500,
        "max_locations": 1,
        "features": {
            "ecommerce":       True,
            "offline_pos":     True,
            "multi_location":  False,
            "expiry_tracking": True,
            "accounting":      True,
            "hr_module":       False,
            "procurement":     True,
            "ai_assistant":    False,
            "loyalty":         True,
            "fulfillment":     False,
            "mobile_apps":     False,
            "kitchen_display": True,
            "live_dispatch":   False,
        },
    },
    "fb_multi": {
        "label":         "F&B Multi-Chain",
        "vertical":      "food",
        "monthly_naira": 350_000,
        "setup_base":    1_200_000,
        "max_skus":      2_000,
        "max_locations": 20,
        "features": {
            "ecommerce":       True,
            "offline_pos":     True,
            "multi_location":  True,
            "expiry_tracking": True,
            "accounting":      True,
            "hr_module":       True,
            "procurement":     True,
            "ai_assistant":    True,
            "loyalty":         True,
            "fulfillment":     True,
            "mobile_apps":     True,
            "kitchen_display": True,
            "live_dispatch":   True,
        },
    },
    "qsr_enterprise": {
        "label":         "QSR Enterprise AI",
        "vertical":      "food",
        "monthly_naira": 500_000,
        "setup_base":    1_800_000,
        "max_skus":      None,
        "max_locations": None,
        "features": {
            "ecommerce":       True,
            "offline_pos":     True,
            "multi_location":  True,
            "expiry_tracking": True,
            "accounting":      True,
            "hr_module":       True,
            "procurement":     True,
            "ai_assistant":    True,
            "loyalty":         True,
            "fulfillment":     True,
            "mobile_apps":     True,
            "kitchen_display": True,
            "live_dispatch":   True,
        },
    },

    # ── Service ─────────────────────────────────────────────────
    "service_basic": {
        "label":         "Service Business",
        "vertical":      "service",
        "monthly_naira": 150_000,
        "setup_base":    200_000,
        "max_skus":      None,
        "max_locations": None,
        "features": {
            "ecommerce":       True,
            "offline_pos":     True,
            "multi_location":  False,
            "expiry_tracking": False,
            "accounting":      True,
            "hr_module":       True,
            "procurement":     False,
            "ai_assistant":    True,
            "loyalty":         True,
            "fulfillment":     False,
            "mobile_apps":     False,
            "kitchen_display": False,
            "live_dispatch":   False,
        },
    },
}


FEATURE_CATALOG: Dict[str, Dict[str, str]] = {
    "ecommerce":       {"label": "Public storefront",        "category": "commerce"},
    "offline_pos":     {"label": "Offline POS",              "category": "sales"},
    "multi_location":  {"label": "Multi-location stock",     "category": "inventory"},
    "expiry_tracking": {"label": "Expiry & batch tracking",  "category": "inventory"},
    "accounting":      {"label": "Accounting module",        "category": "finance"},
    "hr_module":       {"label": "HR & payroll",             "category": "operations"},
    "procurement":     {"label": "Purchase orders & GRN",    "category": "operations"},
    "ai_assistant":    {"label": "AI customer assistant",    "category": "ai"},
    "loyalty":         {"label": "Loyalty points",           "category": "commerce"},
    "fulfillment":     {"label": "Fulfillment dashboard",    "category": "logistics"},
    "mobile_apps":     {"label": "iOS + Android apps",       "category": "mobile"},
    "kitchen_display": {"label": "KDS + tableside QR",       "category": "food"},
    "live_dispatch":   {"label": "Live spatial dispatch",    "category": "food"},
}


METRIC_CATALOG: Dict[str, Dict[str, str]] = {
    "skus":            {"label": "SKUs",             "unit": "count"},
    "members":         {"label": "Team members",     "unit": "count"},
    "locations":       {"label": "Locations",        "unit": "count"},
    "orders_30d":      {"label": "Orders (30d)",     "unit": "count"},
    "gmv_30d":         {"label": "GMV (30d)",        "unit": "naira"},
    "ai_queries_30d":  {"label": "AI queries (30d)", "unit": "count"},
    "storage_mb":      {"label": "Storage",          "unit": "MB"},
    "active_users_7d": {"label": "Active users (7d)","unit": "count"},
}


def effective_features(org: Dict) -> Dict[str, bool]:
    status = (org or {}).get("status") or "active"
    if status in ("suspended", "churned"):
        return {k: False for k in FEATURE_CATALOG}
    tier = PLAN_TIERS.get((org or {}).get("plan_tier") or "", {})
    base = dict(tier.get("features") or {})
    base.update((org or {}).get("feature_overrides") or {})
    for key in FEATURE_CATALOG:
        base.setdefault(key, False)
    return base


def effective_limit(org: Dict, metric: str):
    overrides = (org or {}).get("limits_overrides") or {}
    if metric in overrides:
        return overrides[metric]
    tier = PLAN_TIERS.get((org or {}).get("plan_tier") or "", {})
    return tier.get(f"max_{metric}")


# ============================================================
# FEATURE GATES
# ============================================================
async def fetch_org_flags(org_id: str) -> Optional[Dict]:
    if not org_id:
        return None
    client = get_admin_supabase()
    try:
        res = await run_sync_db_call(
            client.table("organisations")
            .select("id, status, plan_tier, feature_overrides, limits_overrides")
            .eq("id", org_id)
            .maybe_single()
            .execute
        )
        return res.data if res else None
    except Exception as e:
        logger.error("fetch_org_flags failed", org_id=org_id, error=str(e))
        return None


async def check_org_feature(org_id: str, feature_key: str) -> None:
    if not ENFORCE_FEATURES:
        return
    org = await fetch_org_flags(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    if (org.get("status") or "active") in ("suspended", "churned"):
        raise HTTPException(status_code=402, detail="Organisation suspended. Contact support to reactivate.")
    features = effective_features(org)
    if not features.get(feature_key, False):
        raise HTTPException(
            status_code=402,
            detail=f"Feature '{feature_key}' is not enabled for this organisation. "
                   f"Contact support to upgrade your plan.",
        )


# ============================================================
# AUTH PIPELINE
# ============================================================
async def get_current_user(authorization: str = Header(None)) -> Optional[Tuple[str, str]]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ")[1]
    try:
        auth_client = get_user_supabase()
        user = await run_sync_db_call(auth_client.auth.get_user, token)
        if user and user.user:
            email = getattr(user.user, "email", None)
            logger.info("get_current_user", user_id=user.user.id, email=email)
            return user.user.id, email
        logger.warning("get_current_user: no user from token")
        return None
    except Exception as e:
        logger.warning(f"get_current_user: invalid token - {e}")
        return None


async def _pick_default_org(client, org_rows: List[Dict]) -> Optional[Dict]:
    if not org_rows:
        return None
    org_ids = [r["org_id"] for r in org_rows]
    status_by_id: Dict[str, str] = {}
    try:
        status_res = await run_sync_db_call(
            client.table("organisations")
            .select("id, status")
            .in_("id", org_ids)
            .execute
        )
        status_by_id = {o["id"]: (o.get("status") or "active") for o in (status_res.data or [])}
    except Exception as e:
        logger.warning(f"_pick_default_org: status lookup failed: {e}")

    _prio = {"owner": 0, "admin": 1}

    def sort_key(r):
        role_rank = _prio.get(r.get("role"), 2)
        status = status_by_id.get(r["org_id"], "active")
        status_rank = 1 if status in ("suspended", "churned") else 0
        return (role_rank, status_rank, r.get("org_id") or "")

    return sorted(org_rows, key=sort_key)[0]


async def get_current_org(
    authorization: str = Header(None),
    x_selected_org_id: Optional[str] = Header(None, alias="X-Selected-Org-Id"),
) -> Tuple[str, str]:
    user_info = await get_current_user(authorization)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token_user_id, email = user_info

    client = get_supabase()
    resolved_user_id = token_user_id

    try:
        res = await run_sync_db_call(
            client.table("org_members")
            .select("org_id, role")
            .eq("user_id", token_user_id)
            .order("org_id", desc=False)
            .execute
        )
        org_rows = getattr(res, "data", []) or []

        if x_selected_org_id:
            user_role_in_tenant = next(
                (org.get("role") for org in org_rows if str(org.get("org_id")) == str(x_selected_org_id)),
                None,
            )
            if not user_role_in_tenant:
                raise HTTPException(status_code=403, detail="You are not a member of the requested organisation")
            return token_user_id, x_selected_org_id
        elif org_rows:
            chosen = await _pick_default_org(client, org_rows)
            return token_user_id, chosen["org_id"]
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Direct org lookup failed: {e}", exc_info=True)

    if email:
        try:
            profile_res = await run_sync_db_call(
                client.table("profiles").select("id").eq("email", email).maybe_single().execute
            )
            if profile_res and profile_res.data:
                resolved_user_id = profile_res.data["id"]
                res2 = await run_sync_db_call(
                    client.table("org_members").select("org_id, role").eq("user_id", resolved_user_id).execute
                )
                org_rows = getattr(res2, "data", []) or []
                if x_selected_org_id:
                    user_role_in_tenant = next(
                        (org.get("role") for org in org_rows if str(org.get("org_id")) == str(x_selected_org_id)),
                        None,
                    )
                    if not user_role_in_tenant:
                        raise HTTPException(status_code=403, detail="You are not a member of the requested organisation")
                    return resolved_user_id, x_selected_org_id
                elif org_rows:
                    chosen = await _pick_default_org(client, org_rows)
                    return resolved_user_id, chosen["org_id"]
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Email fallback lookup failed: {e}", exc_info=True)

    raise HTTPException(
        status_code=403,
        detail="Workspace Access Denied. Your credentials match, but you have not been assigned to an organization profile yet.",
    )


async def get_current_user_with_role(
    authorization: str = Header(None),
    x_selected_org_id: Optional[str] = Header(None, alias="X-Selected-Org-Id"),
) -> Tuple[str, str, str]:
    user_id, org_id = await get_current_org(authorization, x_selected_org_id)
    client = get_supabase()
    member = await run_sync_db_call(
        client.table("org_members")
        .select("role")
        .eq("user_id", user_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    role = member.data["role"] if member and member.data else "customer"
    return user_id, org_id, role


async def _assert_org_not_suspended(org_id: str) -> None:
    if not org_id:
        return
    client = get_admin_supabase()
    try:
        res = await run_sync_db_call(
            client.table("organisations").select("status").eq("id", org_id).maybe_single().execute
        )
    except Exception as e:
        logger.error("_assert_org_not_suspended: status read failed", org_id=org_id, error=str(e))
        return
    if res and res.data and res.data.get("status") in ("suspended", "churned"):
        raise HTTPException(status_code=402, detail="Organisation suspended. Contact support to reactivate.")


# ============================================================
# FASTAPI DEPENDENCIES
# ============================================================
def require_role(allowed_roles: List[str]):
    async def role_checker(user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
        user_id, org_id, role = user_data
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Access denied. Required role: {allowed_roles}")
        await _assert_org_not_suspended(org_id)
        return user_data
    return role_checker


def require_feature(feature_key: str, allowed_roles: Optional[List[str]] = None):
    async def check(user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
        user_id, org_id, role = user_data
        if allowed_roles is not None and role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Access denied. Required role: {allowed_roles}")
        await _assert_org_not_suspended(org_id)
        await check_org_feature(org_id, feature_key)
        return user_data
    return check


def require_feature_any(*feature_keys: str, allowed_roles: Optional[List[str]] = None):
    async def check(user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
        user_id, org_id, role = user_data
        if allowed_roles is not None and role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Access denied. Required role: {allowed_roles}")
        await _assert_org_not_suspended(org_id)
        if not ENFORCE_FEATURES:
            return user_data
        org = await fetch_org_flags(org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        features = effective_features(org)
        if not any(features.get(k, False) for k in feature_keys):
            raise HTTPException(status_code=402, detail=f"None of {list(feature_keys)} is enabled for this organisation.")
        return user_data
    return check


# ============================================================
# JWT ENRICHMENT
# ============================================================
async def _admin_set_app_metadata(user_id: str, metadata: dict) -> bool:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        logger.warning("_admin_set_app_metadata: missing service role credentials")
        return False
    url = f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.put(url, json={"app_metadata": metadata}, headers=headers)
        if resp.status_code not in (200, 201):
            logger.error("_admin_set_app_metadata failed", user_id=user_id, status=resp.status_code, body=resp.text[:300])
            return False
        logger.info("_admin_set_app_metadata ok", user_id=user_id, keys=list(metadata.keys()))
        return True
    except Exception as e:
        logger.error("_admin_set_app_metadata exception", user_id=user_id, error=str(e))
        return False
