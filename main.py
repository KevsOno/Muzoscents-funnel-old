# ====================================================================
# FULL MONOLITHIC main.py (with HR module integrated)
# ====================================================================

from fastapi import FastAPI, Header, HTTPException, Request, Response, Depends, File, UploadFile, Query, BackgroundTasks, APIRouter
from fastapi.responses import PlainTextResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Tuple, Literal, Any
from datetime import datetime, date, timedelta, timezone
from fastapi.encoders import jsonable_encoder
from enum import Enum
import csv
import io
import os
import logging
import httpx
import uuid
from uuid import UUID
import time
import structlog
from structlog.contextvars import bound_contextvars
import traceback
from decimal import Decimal
import re
import json
import hashlib
import copy

import hmac
import random
from collections import defaultdict
from supabase import create_client, Client
import google.generativeai as genai
from groq import Groq
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from abc import ABC, abstractmethod
from math import radians, sin, cos, sqrt, atan2
import secrets
import string
import uuid
import statistics
from dataclasses import dataclass, field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# FIX: Single global embedder instantiation - NO DOUBLE LOADING
from sentence_transformers import SentenceTransformer, util
SENTENCE_TRANSFORMERS_AVAILABLE = True

print("Initialising Global Vector Embedder (single instance)...")
_GLOBAL_EMBEDDER = SentenceTransformer('all-MiniLM-L6-v2', cache_folder='/root/.cache/huggingface')
print("Global embedder loaded successfully")

print("🚀🚀🚀 NEW main.py IS RUNNING (FIXED VERSION) 🚀🚀🚀")

# ------------------------------------------------------------------
# Environment variables
# ------------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "penafort_verify_2024")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID")
PRODUCTION_HOST = os.environ.get("PRODUCTION_HOST", "https://kevsono-kevs-digital-bos.hf.space")
ADMIN_SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY", "change_this_in_production")
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
FLUTTERWAVE_SECRET_KEY = os.environ.get("FLUTTERWAVE_SECRET_KEY", "")
FLUTTERWAVE_PUBLIC_KEY = os.environ.get("FLUTTERWAVE_PUBLIC_KEY", "")
FLUTTERWAVE_ENCRYPTION_KEY = os.environ.get("FLUTTERWAVE_ENCRYPTION_KEY", "")
FLUTTERWAVE_SECRET_HASH = os.environ.get("FLUTTERWAVE_SECRET_HASH", "my_secret_hash")

PUBLIC_STORE_ORG_ID = os.environ.get("PUBLIC_STORE_ORG_ID")

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@kevsdigital.com")
LOGISTICS_EMAIL = os.environ.get("LOGISTICS_EMAIL", "")

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_FROM_EMAIL = os.environ.get("BREVO_FROM_EMAIL", FROM_EMAIL)

RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))

CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if os.environ.get("CORS_ALLOWED_ORIGINS") else ["*"]

RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "8"))
RAG_THRESHOLD = float(os.environ.get("RAG_THRESHOLD", "0.4"))
RAG_MAX_TOKENS = int(os.environ.get("RAG_MAX_TOKENS", "3000"))
AI_TEMPERATURE = float(os.environ.get("AI_TEMPERATURE", "0.7"))

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
        renderer
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# ─────────────────────────────────────────────────────────────────────
# Migration suite hash
#
# Computed once at import time from the source of every ensure_* /
# backfill_* function referenced by startup_event. Stored in the
# schema_migrations table on successful completion. On next boot, if
# the stored hash matches, startup_event skips the entire suite.
#
# Change any migration function body → hash changes → suite re-runs.
# No code change → hash matches → boot skips straight past the
# migration section.
#
# Set FORCE_MIGRATIONS=true in the environment to force a full re-run
# without a code change (useful after manually altering the schema).
# ─────────────────────────────────────────────────────────────────────
def _compute_migration_suite_hash() -> str:
    import inspect
    names = [
        "ensure_branches_table",
        "ensure_location_stocks_constraints",
        "ensure_cost_price_column",
        "ensure_delivery_fee_columns",
        "ensure_org_delivery_columns",
        "ensure_role_column",
        "ensure_org_registry_schema",
        "ensure_health_check_schema",
        "ensure_knowledge_audit_table",
        "ensure_vector_support",
        "ensure_loyalty_tables",
        "ensure_stock_transfers_table",
        "ensure_stock_transfer_rpcs",
        "ensure_transfer_suggestions_last_updated_column",
        "ensure_decrement_stock_fefo",
        "ensure_finalize_online_order",
        "ensure_webhook_events",
        "ensure_stock_reconciliation",
        "ensure_sales_fulfillment_columns",
        "ensure_alert_log_table",
        "ensure_alert_log_backfill",
        "ensure_transfer_suggestions_table",
        "ensure_transfer_suggestions_backfill",
        "ensure_stock_limits_table",
        "ensure_stock_limits_backfill",
        "ensure_product_risk_view",
        "ensure_transfer_suggestions_view",
        "ensure_system_logs_table",
        "ensure_rpc_functions",
        "ensure_hr_tables",
        "ensure_accounting_tables",
        "ensure_is_cogs_column",
    ]
    h = hashlib.sha256()
    for name in names:
        fn = globals().get(name)
        if fn is None:
            h.update(f"MISSING:{name}\n".encode())
            continue
        try:
            src = inspect.getsource(fn)
        except Exception:
            src = f"UNREADABLE:{name}"
        h.update(f"{name}\n{src}\n".encode())
    return h.hexdigest()

# ====================================================================
# CONTROL CENTER — plan & feature catalog
#
# Static definitions. Never mutate a tier once released; add a new one
# with a new key. Per-org state lives on organisations.plan_tier and
# organisations.feature_overrides.
# ====================================================================

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
    """
    Merge tier defaults with per-org overrides.
    Suspended and churned orgs get nothing — the kill switch.
    Overrides win over tier in both directions (grant and revoke).
    """
    status = (org or {}).get("status") or "active"
    if status in ("suspended", "churned"):
        return {k: False for k in FEATURE_CATALOG}

    tier = PLAN_TIERS.get((org or {}).get("plan_tier") or "", {})
    base = dict(tier.get("features") or {})
    base.update((org or {}).get("feature_overrides") or {})
    # Any feature not otherwise set defaults to False
    for key in FEATURE_CATALOG:
        base.setdefault(key, False)
    return base


def effective_limit(org: Dict, metric: str):
    """
    Resolve a numeric cap for a metric.
      - per-org limits_overrides win
      - else fall back to the tier's max_<metric> (may be None = unlimited)
    """
    overrides = (org or {}).get("limits_overrides") or {}
    if metric in overrides:
        return overrides[metric]
    tier = PLAN_TIERS.get((org or {}).get("plan_tier") or "", {})
    return tier.get(f"max_{metric}")

# ====================================================================
# FEATURE ENFORCEMENT
#
# Master switch. When false, every feature check short-circuits to
# "allowed", so we can ship the plumbing without changing behaviour.
# Flip ENFORCE_FEATURES=true in the Space secrets to turn it on.
# ====================================================================

ENFORCE_FEATURES = os.environ.get("ENFORCE_FEATURES", "false").lower() == "true"

# Org-scope canary. When true, get_supabase() wraps every query builder
# so a read or write against an org-scoped table without an org_id
# filter logs a warning. Off by default — flip it on for an audit, then
# off again. Never raises, never alters query behaviour.
ORG_SCOPE_CANARY = os.environ.get("ORG_SCOPE_CANARY", "false").lower() == "true"


async def fetch_org_flags(org_id: str) -> Optional[Dict]:
    """
    Read the org row that carries plan/status/overrides. One indexed
    lookup. Returns None if the org doesn't exist.
    """
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
    """
    Raise 402 if the org is not entitled to the feature.
    No-op when ENFORCE_FEATURES is off.
    """
    if not ENFORCE_FEATURES:
        return
    org = await fetch_org_flags(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    features = effective_features(org)
    if not features.get(feature_key, False):
        raise HTTPException(
            status_code=402,
            detail=f"Feature '{feature_key}' is not enabled for this organisation. "
                   f"Contact support to upgrade your plan.",
        )


def require_feature(feature_key: str, allowed_roles: Optional[List[str]] = None):
    """
    FastAPI dependency. Resolves org_id from the caller's membership,
    optionally enforces a role list, and then checks the feature
    entitlement. Returns the (user_id, org_id, role) tuple.
    """
    async def check(user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
        user_id, org_id, role = user_data
        if allowed_roles is not None and role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Access denied. Required role: {allowed_roles}")
        await check_org_feature(org_id, feature_key)
        return user_data
    return check

def require_feature_any(*feature_keys: str, allowed_roles: Optional[List[str]] = None):
    async def check(user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
        user_id, org_id, role = user_data
        if allowed_roles is not None and role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Access denied. Required role: {allowed_roles}")
        if not ENFORCE_FEATURES:
            return user_data
        org = await fetch_org_flags(org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        features = effective_features(org)
        if not any(features.get(k, False) for k in feature_keys):
            raise HTTPException(
                status_code=402,
                detail=f"None of {list(feature_keys)} is enabled for this organisation.",
            )
        return user_data
    return check




# ------------------------------------------------------------------
# FastAPI app – MUST BE DEFINED BEFORE ANY DECORATOR
# ------------------------------------------------------------------
app = FastAPI(title="Kevs Digital bOS - Guardrailed AI")

if CORS_ALLOWED_ORIGINS == ["*"]:
    logger.warning("CORS wide open")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
import os

# after `app = FastAPI(...)` and the CORS middleware
_images_dir = os.path.join(BASE_DIR, "images")
if os.path.isdir(_images_dir):
    app.mount("/images", StaticFiles(directory=_images_dir), name="images")
    logger.info(f"Serving static images from {_images_dir}")
else:
    logger.warning(f"images/ directory not found at {_images_dir} — /images/* will 404")


# ===================== HR ROUTER (integrated) =====================
hr_router = APIRouter(prefix="/hr", tags=["Human Resources"])

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

_ORG_SCOPED_TABLES = frozenset({
    # The tables that leaked in the 2026-10 sweep
    "alert_log",
    "stock_limits",
    "transfer_suggestions",
    "products",

    # Core tenant data
    "inventory",
    "inventory_batches",
    "sales",
    "sale_items",
    "locations",
    "location_stocks",
    "stock_transfers",
    "branches",

    # Procurement
    "suppliers",
    "purchase_orders",
    "purchase_order_items",
    "grn",
    "grn_items",

    # CRM / support
    "org_leads",
    "support_tickets",
    "ticket_messages",
    "chat_sessions",
    "chat_messages",
    "general_knowledge",
    "knowledge_audit",

    # Accounting
    "chart_of_accounts",
    "journal_entries",
    "journal_lines",
    "accounts_receivable",
    "accounts_payable",
    "profit_loss_summary",

    # HR
    "hr_departments",
    "hr_employees",
    "hr_attendance",
    "hr_leave_requests",
    "hr_leave_balances",
    "hr_payroll",

    # Infrastructure
    "system_logs",
    "webhook_events",
    "admin_audit",
    "audit_events",
})

# ------------------------------------------------------------------
# Supabase clients
#
# Three distinct clients, three distinct jobs.
#
# IMPORTANT: supabase-py / gotrue-py stores the auth session in state
# that is keyed by SUPABASE_URL, not by client instance. Calling
# sign_in_with_password on ANY client created from this URL writes the
# resulting session to that shared store, and every other client built
# from the same URL then reads it back. The result: a fresh
# `create_client(SUPABASE_URL, SERVICE_ROLE_KEY)` can come out already
# "logged in" as the last person who authenticated — and its PostgREST
# requests will send that user's JWT, so RLS applies and the service
# role is silently ignored.
#
# Every client we build therefore calls _force_clear_auth_session()
# before we hand it to the caller. The guard on the cached client
# blocks the specific mutator methods; this clears the shared store
# underneath so a leak can't survive even if the guard is bypassed.
# ------------------------------------------------------------------

# Auth methods that mutate a client's session. Any call on a guarded
# client raises immediately, so a regression fails loudly at the call
# site instead of silently poisoning the process for up to an hour.
_AUTH_MUTATORS = frozenset({
    "sign_in",
    "sign_in_with_password",
    "sign_in_with_otp",
    "sign_up",
    "sign_out",
    "refresh_session",
    "set_session",
    "verify_otp",
    "reauthenticate",
    "reset_password_for_email",
})


class _GuardedAuth:
    """
    Wraps a Supabase client's `.auth` and blocks any mutator. Reads
    (get_user, get_session, get_claims) fall through untouched.
    """
    __slots__ = ("_inner",)

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        if name in _AUTH_MUTATORS:
            raise RuntimeError(
                f"auth.{name}() mutates the shared Supabase client and would "
                f"poison every subsequent request with the caller's JWT. "
                f"Use get_user_supabase() for authentication calls."
            )
        return getattr(self._inner, name)

class _CanaryBuilder:
    """
    Wraps a supabase-py request builder. On .execute(), if the target
    table is in _ORG_SCOPED_TABLES and the accumulated query params
    carry no org_id filter, logs a warning with the caller's file:line.

    Design constraints:
      - No-op unless ORG_SCOPE_CANARY is true.
      - Never raises. Never blocks. Never changes what the query does.
        The wrapped .execute() always calls through to the real one.
      - Every method on the builder chain is transparently re-wrapped,
        so the terminal .execute() is intercepted no matter how long
        the chain is or which order the filters were applied in.

    Why this is not a hard block:
      Some legitimate reads do not filter by org_id — cross-tenant
      admin paths, invitation-code lookups, webhook handlers resolving
      a tenant from the payload. The canary is an audit signal, not an
      enforcement layer. Enforcement is what the explicit .eq() calls
      in each endpoint already do.
    """
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

        # PostgREST represents a filter as param key "org_id" with value
        # "eq.<uuid>". Embedded filters on joined tables use the key
        # "table.org_id". Either shape satisfies the check.
        for k in keys:
            if k == "org_id" or k.endswith(".org_id"):
                return

        # No org_id filter on an org-scoped table. Identify the caller
        # by walking the stack for the first frame that is inside the
        # application rather than inside site-packages.
        caller = None
        try:
            for frame in reversed(traceback.extract_stack()):
                if "site-packages" in frame.filename:
                    continue
                if "/app/" in frame.filename or frame.filename.endswith("main.py"):
                    caller = f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno} {frame.name}"
                    break
        except Exception:
            pass

        logger.warning(
            "org_scope_canary",
            table=self._table,
            caller=caller,
        )

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            result = attr(*args, **kwargs)
            # Chainable builder methods return a builder (usually self).
            # Keep wrapping so the terminal .execute() is intercepted.
            if hasattr(result, "execute"):
                return _CanaryBuilder(result, self._table)
            return result

        return wrapped


class _GuardedClient:
    """
    Wraps the cached Supabase client. `.auth` returns the guarded variant.
    Every other attribute falls through unchanged, so .table(), .rpc(),
    .storage, etc. all work as before.
    """
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
    """
    Wipe any inherited auth session on a freshly-created Supabase client.

    supabase-py shares auth state per SUPABASE_URL. A sign_in on one
    client leaks into every other client from the same URL. This clears
    both the in-memory session fields and the storage layer so a fresh
    client authenticates with its apikey alone — never with whatever
    user last signed in anywhere.

    This is defence in depth: the guarded client blocks the mutator
    methods by name; this clears the state those methods would write to.
    """
    try:
        auth = client.auth
    except Exception:
        return

    # 1. In-memory session fields the PostgREST sub-client consults when
    #    it builds the Authorization header on the next request.
    for attr in ("_current_session", "_current_user"):
        try:
            if hasattr(auth, attr):
                setattr(auth, attr, None)
        except Exception:
            pass

    # 2. Storage layer. Key formats vary across gotrue versions, so try
    #    the common ones and ignore failures — step 1 is the real fix.
    try:
        storage = getattr(auth, "_storage", None)
        if storage is not None:
            url = (SUPABASE_URL or "").rstrip("/")
            for key in (
                "supabase.auth.token",
                f"sb-{url}-auth-token",
                "gotrue.auth.token",
            ):
                try:
                    storage.remove_item(key)
                except Exception:
                    pass
    except Exception:
        pass


supabase_client: Optional[Client] = None
last_client_check = None


def get_supabase():
    """
    Cached service-role client. `.auth` is guarded so it can never be
    mutated with a user session. Use get_user_supabase() for auth.
    """
    global supabase_client, last_client_check
    now = datetime.now(timezone.utc)
    if supabase_client is None or (last_client_check and (now - last_client_check).seconds > 3600):
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            if SUPABASE_ANON_KEY:
                logger.warning("SUPABASE_SERVICE_ROLE_KEY missing – falling back to anon key (RLS may block access)")
                raw = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
            else:
                raise RuntimeError("No Supabase credentials (neither service role nor anon key)")
        else:
            raw = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
            logger.info("Supabase client created with SERVICE ROLE KEY (RLS bypassed)")
        _force_clear_auth_session(raw)
        supabase_client = _GuardedClient(raw)
        last_client_check = now
    return supabase_client


def get_admin_supabase() -> Client:
    """
    Fresh service-role client, built per call. Never cached, never
    carries a user session. Use for /admin/* and one-off system ops.

    Clears any inherited auth session before returning — see
    _force_clear_auth_session for the why.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Missing service role key for admin client")
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    _force_clear_auth_session(client)
    return client


def get_user_supabase() -> Client:
    """
    Fresh anon-key client for authentication calls ONLY:
      sign_in, sign_up, refresh_session, sign_out, get_user,
      reset_password_for_email.

    Must NEVER be cached and must NEVER be used for data reads — it
    carries no service role, so RLS applies with whatever session is
    attached. Clears any inherited session first so a fresh anon client
    isn't accidentally pre-authenticated as the last person to log in.
    """
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("Missing anon key for user auth client")
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    _force_clear_auth_session(client)
    return client
# ===================== JWT ENRICHMENT =====================
async def _admin_set_app_metadata(user_id: str, metadata: dict) -> bool:
    """
    Stamp app_metadata on a Supabase auth user via the admin API.
    The next JWT issued to that user carries these claims.
    Never raises — returns False and logs on failure so callers can
    continue without breaking onboarding.
    """
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
            logger.error(
                "_admin_set_app_metadata failed",
                user_id=user_id, status=resp.status_code, body=resp.text[:300],
            )
            return False
        logger.info("_admin_set_app_metadata ok", user_id=user_id, keys=list(metadata.keys()))
        return True
    except Exception as e:
        logger.error("_admin_set_app_metadata exception", user_id=user_id, error=str(e))
        return False


# ===================== BRANCH RESOLUTION =====================

async def ensure_branches_table():
    """
    Create the branches table if it's missing, heal any columns a legacy
    copy of the table is missing, backfill NULL is_default values, and
    then create the indexes that enforce (a) one default branch per org,
    (b) fast lookup by org, (c) unique code per org.

    Idempotent and safe against a partially-migrated table: every step
    uses CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS, so a
    table created by a prior version of this migration — one that might
    lack `is_default` or any other column — gets healed in place rather
    than tripping the CREATE INDEX that follows.
    """
    sql = """
    CREATE TABLE IF NOT EXISTS public.branches (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id      UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        name        TEXT NOT NULL,
        code        TEXT,
        is_default  BOOLEAN NOT NULL DEFAULT FALSE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- Heal a legacy branches table that predates one or more columns.
    -- ADD COLUMN IF NOT EXISTS is a no-op when the column is already
    -- present, so this is safe to run on every boot.
    ALTER TABLE public.branches
        ADD COLUMN IF NOT EXISTS org_id      UUID,
        ADD COLUMN IF NOT EXISTS name        TEXT,
        ADD COLUMN IF NOT EXISTS code        TEXT,
        ADD COLUMN IF NOT EXISTS is_default  BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ADD COLUMN IF NOT EXISTS updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW();

    -- Backfill any NULL is_default values. A row that predates the
    -- column has NULL, and the partial unique index below treats NULL
    -- as "not true", which would let the org drift into having no
    -- well-defined default. Normalising to FALSE makes the state
    -- explicit; ensure_default_branch() will seed a TRUE row on the
    -- next write.
    UPDATE public.branches
       SET is_default = FALSE
     WHERE is_default IS NULL;

    CREATE INDEX IF NOT EXISTS idx_branches_org_created
        ON public.branches (org_id, created_at);

    CREATE UNIQUE INDEX IF NOT EXISTS idx_branches_org_default
        ON public.branches (org_id)
        WHERE is_default = TRUE;

    CREATE UNIQUE INDEX IF NOT EXISTS idx_branches_org_code
        ON public.branches (org_id, code)
        WHERE code IS NOT NULL;
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
        logger.error(f"branches table migration failed: {resp.text}")
        raise RuntimeError(f"branches table migration failed: {resp.text}")
    logger.info("branches table installed (or already present)")    

async def resolve_default_branch(org_id: str) -> Optional[str]:
    """
    PURE READ. Return the id of the org's default branch, or the
    oldest branch if no row is marked default. Returns None if the
    org has no branches yet. Does NOT create anything.

    Callers that need a guaranteed branch id should use
    ensure_default_branch() or resolve_branch_for_write().
    """
    if not org_id:
        return None
    client = get_admin_supabase()

    # Prefer the row explicitly flagged default.
    default_res = await run_sync_db_call(
        client.table("branches")
        .select("id")
        .eq("org_id", org_id)
        .eq("is_default", True)
        .limit(1)
        .execute
    )
    if default_res.data:
        return default_res.data[0]["id"]

    # Fall back to the oldest branch on the org.
    oldest_res = await run_sync_db_call(
        client.table("branches")
        .select("id")
        .eq("org_id", org_id)
        .order("created_at", desc=False)
        .limit(1)
        .execute
    )
    return oldest_res.data[0]["id"] if oldest_res.data else None


async def ensure_default_branch(org_id: str) -> Optional[str]:
    """
    Idempotent. Return the org's default branch id, creating a MAIN
    branch if the org has none. Safe to call concurrently — the
    partial unique index on (org_id) WHERE is_default=TRUE plus the
    follow-up select handles the race.

    Uses the admin client so this works from public checkout, webhook
    handlers, and admin paths that run without an authenticated user.
    """
    if not org_id:
        return None

    existing = await resolve_default_branch(org_id)
    if existing:
        return existing

    client = get_admin_supabase()
    now = datetime.now(timezone.utc).isoformat()
    try:
        ins = await run_sync_db_call(
            client.table("branches").insert({
                "org_id":     org_id,
                "name":       "Main",
                "code":       "MAIN",
                "is_default": True,
                "created_at": now,
                "updated_at": now,
            }).execute
        )
        if ins.data:
            logger.info("ensure_default_branch: seeded MAIN", org_id=org_id)
            return ins.data[0]["id"]
    except Exception as e:
        # Lost a race — someone else created the default. Re-read.
        logger.warning("ensure_default_branch: insert lost or failed, re-reading",
                       org_id=org_id, error=str(e)[:200])

    return await resolve_default_branch(org_id)


async def resolve_branch_for_write(
    org_id: str,
    requested: Optional[str] = None,
) -> Optional[str]:
    """
    Decide which branch_id a new row should carry.

    Resolution order:
      1. `requested` if non-empty (caller already validated ownership)
      2. The org's default branch, seeding MAIN if none exists

    Never returns None for a real org after this fix, because the
    seed path guarantees a branch.
    """
    if requested:
        return requested
    return await ensure_default_branch(org_id)
    
# ===================== ASYNC DB HELPER =====================
async def run_sync_db_call(sync_func, *args, **kwargs):
    """Run a sync supabase-py call in a thread to avoid blocking the event loop."""
    return await asyncio.to_thread(sync_func, *args, **kwargs)


async def fetch_one(query) -> Optional[Dict]:
    """
    Run a supabase query that returns 0 or 1 row. Returns the row as a dict,
    or None if no row matches.

    Use with `.maybe_single()`:
        row = await fetch_one(client.table("x").select("*").eq("id", y).maybe_single())
        if not row: raise HTTPException(404, "...")

    Handles both failure modes of supabase-py:
      - postgrest-py raises APIError(PGRST116) when 0 rows are found
      - response.data is None when 0 rows are found
    """
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




# ===================== HELPER: DEFAULT LOCATION =====================

async def get_default_location(org_id: str) -> Optional[int]:
    """
    Return the ID of the main warehouse location.
    If none, return the first location available.

    Uses the admin client so the lookup always returns the org's own
    default location regardless of who last authenticated. Called from
    /admin/reconcile-stock and other admin paths that iterate all orgs.
    """
    client = get_admin_supabase()
    result = await run_sync_db_call(
        client.table("locations")
        .select("id")
        .eq("org_id", org_id)
        .order("is_warehouse", desc=True)
        .limit(1)
        .execute
    )
    return result.data[0]["id"] if result.data else None


async def get_location_for_channel(org_id: str, channel: str) -> Optional[str]:
    """
    Resolve the fulfillment location for a sales channel.

    channel ∈ {'pos', 'online'}
      'pos'    → prefers type='store', falls back to 'warehouse'
      'online' → prefers type='online_fulfillment', falls back to 'warehouse'

    Returns None if the org has no locations at all (unreachable post-migration).

    Uses the admin client because callers include webhook handlers and
    public checkout paths that run without any authenticated user. RLS
    scoping would return nothing in those contexts. For authenticated
    callers, the explicit .eq("org_id", org_id) filter is the real
    tenant boundary; the admin client just removes a second, unreliable
    enforcement layer from the picture.
    """
    if not org_id:
        return None

    priority = {
        "pos":    ["store", "warehouse"],
        "online": ["online_fulfillment", "warehouse"],
    }.get(channel, ["warehouse"])

    client = get_admin_supabase()
    for loc_type in priority:
        result = await run_sync_db_call(
            client.table("locations")
            .select("id")
            .eq("org_id", org_id)
            .eq("type", loc_type)
            .eq("is_active", True)
            .order("created_at", desc=False)
            .limit(1)
            .execute
        )
        if result.data:
            return result.data[0]["id"]

    # Last resort: any active location (preserves behaviour on empty orgs)
    fallback = await run_sync_db_call(
        client.table("locations")
        .select("id")
        .eq("org_id", org_id)
        .eq("is_active", True)
        .order("created_at", desc=False)
        .limit(1)
        .execute
    )
    return fallback.data[0]["id"] if fallback.data else None


# ===================== LOCATION-SCOPED INVENTORY READS =====================

async def fetch_inventory_scoped_to_location(
    org_id: str,
    location_id: str,
    limit: int,
    offset: int,
    q: Optional[str] = None,
    category: Optional[str] = None,
    sort_by: str = "newest",
    require_positive_stock: bool = False,
) -> Tuple[List[Dict], int]:
    """
    Read inventory rows scoped to a single location.
    Response row = full inventory row + location-scoped overrides:
      - current_qty  : OVERRIDDEN to location-specific quantity
      - location_qty : same value, explicit
      - global_qty   : original inventory.current_qty (org-wide)
      - location_id  : the location we scoped to
    """
    client = get_supabase()

    query = (
        client.table("inventory")
        .select(
            "*, location_stocks!inner(location_id, quantity, reserved_quantity)",
            count="exact",
        )
        .eq("org_id", org_id)
        .eq("location_stocks.location_id", location_id)
    )

    if q:
        or_condition = (
            f"description.ilike.%{q}%,"
            f"item_code.ilike.%{q}%,"
            f"product_group.ilike.%{q}%"
        )
        query = query.or_(or_condition)

    if category:
        query = query.eq("product_group", category)

    if require_positive_stock:
        query = query.gt("location_stocks.quantity", 0)

    if sort_by == "price_asc":
        query = query.order("price_naira", desc=False)
    elif sort_by == "price_desc":
        query = query.order("price_naira", desc=True)
    else:
        query = query.order("id", desc=True)

    result = await run_sync_db_call(query.range(offset, offset + limit - 1).execute)
    rows = result.data or []
    total = result.count or 0

    items: List[Dict] = []
    for row in rows:
        stocks = row.pop("location_stocks", None) or []
        loc_qty = int(stocks[0].get("quantity") or 0) if stocks else 0
        global_qty = int(row.get("current_qty") or 0)
        row["current_qty"]  = loc_qty
        row["location_qty"] = loc_qty
        row["global_qty"]   = global_qty
        row["location_id"]  = location_id
        items.append(row)

    return items, total


# ===================== HELPER: decrement_stock_fefo =====================

async def decrement_stock_fefo(
    org_id: str,
    items: List[Dict],
    location_id: Optional[int],
    sale_id: Optional[str] = None,
) -> Dict:
    """
    Atomic FEFO decrement via the decrement_stock_fefo RPC.
    If sale_id is provided, the sale row is locked and flipped to
    'completed' inside the same transaction — idempotent on retry.
    Returns the RPC's response dict (contains 'skipped' and 'short').
    """
    if not items:
        return {"success": True, "skipped": False}

    payload_items = [
        {"inventory_id": int(it["inventory_id"]), "quantity": int(it["quantity"])}
        for it in items
        if int(it.get("quantity") or 0) > 0
    ]
    if not payload_items:
        return {"success": True, "skipped": False}

    try:
        resp = await run_sync_db_call(
            get_supabase().rpc("decrement_stock_fefo", {
                "p_org_id":      org_id,
                "p_items":       payload_items,
                "p_location_id": location_id,
                "p_sale_id":     sale_id,
            }).execute
        )
    except Exception as e:
        logger.error(
            f"decrement_stock_fefo RPC failed for org {org_id}: {e}",
            exc_info=True,
        )
        raise

    data = resp.data or {}
    for s in (data.get("short") or []):
        logger.warning(
            f"decrement_stock_fefo: inventory {s['inventory_id']} short by "
            f"{s['short_by']} units at location {location_id} (org {org_id})"
        )
    return data
# ------------------------------------------------------------------
# Raw SQL executor (bypasses client library)
# ------------------------------------------------------------------
async def run_sql(query: str) -> List[Dict]:
    """Execute raw SQL using the exec_sql RPC with service role key."""
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
            json={"query": query},
            headers=headers
        )
    if resp.status_code not in (200, 204):
        logger.error(f"exec_sql failed: {resp.status_code} {resp.text}")
        raise HTTPException(status_code=500, detail=f"SQL execution failed: {resp.text}")
    if resp.status_code == 204 or not resp.content:
        return []
    return resp.json()

# ------------------------------------------------------------------
# Direct REST API calls (service role key, bypasses RLS)
# ------------------------------------------------------------------
async def supabase_rest_get(
    table: str,
    select: str = "*",
    filters: Optional[Dict[str, str]] = None,
    filter_string: str = ""
) -> List[Dict]:
    url = f"{SUPABASE_URL}/rest/v1/{table}?select={select}"
    if filters:
        for key, value in filters.items():
            url += f"&{key}=eq.{value}"
    if filter_string:
        url += f"&{filter_string}"

    logger.info(f"🔍 REST GET: {url}")

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code not in (200, 204):
        logger.error(f"❌ REST query failed: {resp.status_code} {resp.text}")
        raise HTTPException(status_code=500, detail=f"Query failed: {resp.text}")
    if resp.status_code == 204 or not resp.content:
        return []
    return resp.json()

# ===================== LOYALTY POINTS ENGINE =====================
async def award_loyalty_points(user_id: str, amount_naira: float, sale_id: str, reason: str = "purchase") -> int:
    if amount_naira <= 0 or not user_id:
        return 0
    points_earned = int((amount_naira / 1000) * 10)
    if points_earned == 0:
        return 0

    client = get_supabase()
    profile = await run_sync_db_call(
        client.table("profiles").select("current_points").eq("id", user_id).maybe_single().execute
    )
    if not profile.data:
        logger.error(f"User {user_id} not found in profiles")
        return 0
    current_points = profile.data.get("current_points", 0)
    new_points = current_points + points_earned

    await run_sync_db_call(
        client.table("profiles").update({"current_points": new_points}).eq("id", user_id).execute
    )

    await run_sync_db_call(
        client.table("loyalty_transactions").insert({
            "user_id": user_id,
            "sale_id": sale_id,
            "points_delta": points_earned,
            "reason": reason,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute
    )

    logger.info(f"Awarded {points_earned} points to user {user_id} for sale {sale_id} (₦{amount_naira})")
    return points_earned

async def redeem_points_to_credit(user_id: str, points_to_redeem: int) -> float:
    if points_to_redeem <= 0:
        raise HTTPException(status_code=400, detail="Points to redeem must be positive")
    client = get_supabase()
    profile = await run_sync_db_call(
        client.table("profiles").select("current_points, credit_balance").eq("id", user_id).maybe_single().execute
    )
    if not profile.data:
        raise HTTPException(status_code=404, detail="User not found")
    current_points = profile.data.get("current_points", 0)
    if current_points < points_to_redeem:
        raise HTTPException(status_code=400, detail="Insufficient points")

    new_points = current_points - points_to_redeem
    credit_added = float(points_to_redeem)
    new_credit = (profile.data.get("credit_balance", 0.0) or 0.0) + credit_added

    await run_sync_db_call(
        client.table("profiles").update({
            "current_points": new_points,
            "credit_balance": new_credit
        }).eq("id", user_id).execute
    )

    await run_sync_db_call(
        client.table("loyalty_transactions").insert({
            "user_id": user_id,
            "points_delta": -points_to_redeem,
            "reason": "redeem_to_credit",
            "metadata": {"credit_added": credit_added},
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute
    )

    return credit_added

async def get_loyalty_balance(user_id: str) -> Dict:
    client = get_supabase()
    profile = await run_sync_db_call(
        client.table("profiles").select("current_points, credit_balance").eq("id", user_id).maybe_single().execute
    )
    if not profile.data:
        return {"points": 0, "credit": 0.0}
    return {
        "points": profile.data.get("current_points", 0),
        "credit": float(profile.data.get("credit_balance", 0.0) or 0.0)
    }

async def get_loyalty_transactions(user_id: str, limit: int = 50, offset: int = 0) -> List[Dict]:
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("loyalty_transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute
    )
    return result.data or []

# ------------------------------------------------------------------
# Database migrations
# ------------------------------------------------------------------
async def ensure_loyalty_tables():
    supabase = get_supabase()
    try:
        test = await run_sync_db_call(supabase.table("profiles").select("credit_balance").limit(1).execute)
        logger.info("credit_balance column already exists in profiles.")
    except Exception as e:
        if 'column "credit_balance" does not exist' in str(e):
            logger.warning("Adding credit_balance column to profiles...")
            sql = "ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS credit_balance NUMERIC DEFAULT 0;"
            headers = {
                "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{SUPABASE_URL}/rest/v1/rpc/exec_sql", json={"query": sql}, headers=headers)
                if resp.status_code not in (200, 204):
                    logger.error(f"Failed to add credit_balance: {resp.text}")
                else:
                    logger.info("credit_balance column added.")
    try:
        test = await run_sync_db_call(supabase.table("loyalty_transactions").select("id").limit(1).execute)
        logger.info("loyalty_transactions table exists.")
    except Exception as e:
        if 'relation "loyalty_transactions" does not exist' in str(e):
            logger.warning("Creating loyalty_transactions table...")
            sql = """
            CREATE TABLE IF NOT EXISTS public.loyalty_transactions (
                id SERIAL PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
                sale_id UUID REFERENCES public.sales(id) ON DELETE SET NULL,
                points_delta INTEGER NOT NULL,
                reason TEXT NOT NULL,
                metadata JSONB,
                created_at TIMESTAMPTZ DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_loyalty_user ON public.loyalty_transactions(user_id);
            """
            headers = {
                "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{SUPABASE_URL}/rest/v1/rpc/exec_sql", json={"query": sql}, headers=headers)
                if resp.status_code not in (200, 204):
                    logger.error(f"Failed to create loyalty_transactions: {resp.text}")
                else:
                    logger.info("loyalty_transactions table created.")
    try:
        test = await run_sync_db_call(supabase.table("customer_points_summary").select("id").limit(1).execute)
        logger.info("customer_points_summary view already exists.")
    except Exception as e:
        if 'relation "customer_points_summary" does not exist' in str(e):
            logger.warning("Creating customer_points_summary view...")
            sql = """
            CREATE OR REPLACE VIEW public.customer_points_summary AS
            SELECT 
                id,
                membership_id,
                current_points,
                tier,
                credit_balance,
                status
            FROM public.profiles;
            """
            headers = {
                "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{SUPABASE_URL}/rest/v1/rpc/exec_sql", json={"query": sql}, headers=headers)
                if resp.status_code not in (200, 204):
                    logger.error(f"Failed to create customer_points_summary view: {resp.text}")
                else:
                    logger.info("customer_points_summary view created.")
    try:
        test = await run_sync_db_call(supabase.table("profiles").select("current_points").limit(1).execute)
        logger.info("current_points column exists.")
    except Exception as e:
        if 'column "current_points" does not exist' in str(e):
            logger.warning("Adding current_points column to profiles...")
            sql = "ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS current_points INTEGER DEFAULT 0;"
            headers = {
                "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{SUPABASE_URL}/rest/v1/rpc/exec_sql", json={"query": sql}, headers=headers)
                if resp.status_code not in (200, 204):
                    logger.error(f"Failed to add current_points: {resp.text}")
                else:
                    logger.info("current_points column added.")

async def ensure_transfer_suggestions_last_updated_column():
    sql = """
    ALTER TABLE public.transfer_suggestions
        ADD COLUMN IF NOT EXISTS last_updated TIMESTAMPTZ DEFAULT NOW();
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
        logger.error(f"Failed to add last_updated: {resp.text}")
        raise RuntimeError(f"last_updated migration failed: {resp.text}")
    logger.info("transfer_suggestions.last_updated column installed")


async def ensure_sales_fulfillment_columns():
    sql = """
    ALTER TABLE public.sales
        ADD COLUMN IF NOT EXISTS fulfillment_mode  TEXT,
        ADD COLUMN IF NOT EXISTS fulfillment_notes TEXT,
        ADD COLUMN IF NOT EXISTS table_number      TEXT,
        ADD COLUMN IF NOT EXISTS pickup_time       TIMESTAMPTZ;
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
        logger.error(f"sales fulfillment migration failed: {resp.text}")
        raise RuntimeError(f"sales fulfillment migration failed: {resp.text}")
    logger.info("sales fulfillment columns installed")

async def ensure_health_check_schema():
    sql = """
    CREATE OR REPLACE FUNCTION public.health_check_schema()
    RETURNS JSONB
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = public, pg_catalog
    AS $$
    DECLARE
        v_rpcs   JSONB;
        v_tables JSONB;
    BEGIN
        SELECT COALESCE(jsonb_agg(proname ORDER BY proname), '[]'::jsonb)
          INTO v_rpcs
          FROM pg_proc
         WHERE proname IN (
            'approve_stock_transfer',
            'complete_stock_transfer',
            'decrement_stock_fefo',
            'claim_webhook_event',
            'finalize_online_order',
            'mark_webhook_event_processed',
            'release_webhook_event_claim',
            'audit_stock_drift',
            'heal_stock_drift',
            'match_knowledge_documents'
         );

        SELECT COALESCE(jsonb_agg(tablename ORDER BY tablename), '[]'::jsonb)
          INTO v_tables
          FROM pg_tables
         WHERE schemaname = 'public'
           AND tablename IN (
            'organisations','profiles','org_members',
            'inventory','locations','location_stocks','stock_transfers',
            'sales','sale_items',
            'accounts_receivable','accounts_payable',
            'webhook_events','general_knowledge','support_tickets'
         );

        RETURN jsonb_build_object('rpcs', v_rpcs, 'tables', v_tables);
    END;
    $$;

    GRANT EXECUTE ON FUNCTION public.health_check_schema() TO service_role;
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
        logger.error(f"health_check_schema migration failed: {resp.text}")
        raise RuntimeError(f"health_check_schema migration failed: {resp.text}")
    logger.info("health_check_schema RPC installed")



async def ensure_cost_price_column():
    supabase = get_supabase()
    try:
        test = await run_sync_db_call(supabase.table("inventory").select("cost_price_naira").limit(1).execute)
        logger.info("cost_price_naira column already exists.")
    except Exception as e:
        if 'column "cost_price_naira" does not exist' in str(e):
            logger.warning("cost_price_naira column missing. Adding it now...")
            try:
                sql = """
                ALTER TABLE public.inventory 
                ADD COLUMN IF NOT EXISTS cost_price_naira NUMERIC NOT NULL DEFAULT 0.0;
                UPDATE public.inventory
                SET cost_price_naira = ROUND((price_naira * 0.5)::numeric, 2)
                WHERE cost_price_naira = 0.0;
                """
                headers = {
                    "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                        json={"query": sql},
                        headers=headers
                    )
                    if resp.status_code not in (200, 204):
                        logger.error(f"Failed to run migration: {resp.text}")
                    else:
                        logger.info("Successfully added cost_price_naira column and set default values.")
            except Exception as migration_err:
                logger.error(f"Migration error: {migration_err}")
        else:
            logger.error(f"Unexpected error checking column: {e}")

async def ensure_delivery_fee_columns():
    supabase = get_supabase()
    try:
        test = await run_sync_db_call(supabase.table("sales").select("delivery_fee").limit(1).execute)
        logger.info("delivery_fee column already exists.")
    except Exception as e:
        if 'column "delivery_fee" does not exist' in str(e):
            logger.warning("delivery_fee/handling_fee columns missing. Adding them now...")
            try:
                sql = """
                ALTER TABLE public.sales 
                ADD COLUMN IF NOT EXISTS delivery_fee NUMERIC DEFAULT 0,
                ADD COLUMN IF NOT EXISTS handling_fee NUMERIC DEFAULT 0;
                """
                headers = {
                    "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                        json={"query": sql},
                        headers=headers
                    )
                    if resp.status_code not in (200, 204):
                        logger.error(f"Failed to add delivery_fee columns: {resp.text}")
                    else:
                        logger.info("Successfully added delivery_fee and handling_fee columns.")
            except Exception as migration_err:
                logger.error(f"Delivery fee column migration error: {migration_err}")
        else:
            logger.error(f"Unexpected error checking delivery_fee column: {e}")

async def ensure_org_delivery_columns():
    supabase = get_supabase()
    try:
        test = await run_sync_db_call(supabase.table("organisations").select("delivery_base_fee").limit(1).execute)
        logger.info("Organisation delivery columns already exist.")
    except Exception as e:
        if 'column "delivery_base_fee" does not exist' in str(e):
            logger.warning("Organisation delivery columns missing. Adding them now...")
            try:
                sql = """
                ALTER TABLE public.organisations 
                ADD COLUMN IF NOT EXISTS delivery_base_fee NUMERIC DEFAULT 300,
                ADD COLUMN IF NOT EXISTS delivery_per_km_rate NUMERIC DEFAULT 80,
                ADD COLUMN IF NOT EXISTS delivery_per_kg_rate NUMERIC DEFAULT 50,
                ADD COLUMN IF NOT EXISTS handling_surcharge_fragile NUMERIC DEFAULT 200,
                ADD COLUMN IF NOT EXISTS handling_surcharge_bulky NUMERIC DEFAULT 500,
                ADD COLUMN IF NOT EXISTS handling_surcharge_hazardous NUMERIC DEFAULT 1000;
                """
                headers = {
                    "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                        json={"query": sql},
                        headers=headers
                    )
                    if resp.status_code not in (200, 204):
                        logger.error(f"Failed to add organisation delivery columns: {resp.text}")
                    else:
                        logger.info("Successfully added delivery columns to organisations table.")
            except Exception as migration_err:
                logger.error(f"Organisation delivery columns migration error: {migration_err}")
        else:
            logger.error(f"Unexpected error checking organisation columns: {e}")

async def ensure_role_column():
    supabase = get_supabase()
    try:
        test = await run_sync_db_call(supabase.table("org_members").select("role").limit(1).execute)
        logger.info("role column already exists in org_members.")
    except Exception as e:
        if 'column "role" does not exist' in str(e):
            logger.warning("role column missing in org_members. Adding it now...")
            try:
                sql = """
                ALTER TABLE public.org_members 
                ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'customer';
                """
                headers = {
                    "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                        json={"query": sql},
                        headers=headers
                    )
                    if resp.status_code not in (200, 204):
                        logger.error(f"Failed to add role column: {resp.text}")
                    else:
                        logger.info("Successfully added role column to org_members.")
            except Exception as migration_err:
                logger.error(f"Role column migration error: {migration_err}")
        else:
            logger.error(f"Unexpected error checking role column: {e}")

async def ensure_knowledge_audit_table():
    supabase = get_supabase()
    try:
        test = await run_sync_db_call(supabase.table("knowledge_audit").select("id").limit(1).execute)
        logger.info("knowledge_audit table already exists.")
    except Exception as e:
        if 'relation "knowledge_audit" does not exist' in str(e):
            logger.warning("knowledge_audit table missing. Creating it now...")
            try:
                sql = """
                CREATE TABLE IF NOT EXISTS public.knowledge_audit (
                    id SERIAL PRIMARY KEY,
                    doc_id INTEGER REFERENCES public.general_knowledge(id) ON DELETE CASCADE,
                    org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
                    user_id UUID NOT NULL,
                    action TEXT NOT NULL,
                    old_content TEXT,
                    new_content TEXT,
                    changed_at TIMESTAMPTZ DEFAULT now()
                );
                """
                headers = {
                    "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                        json={"query": sql},
                        headers=headers
                    )
                    if resp.status_code not in (200, 204):
                        logger.error(f"Failed to create knowledge_audit table: {resp.text}")
                    else:
                        logger.info("Successfully created knowledge_audit table.")
            except Exception as migration_err:
                logger.error(f"Knowledge audit migration error: {migration_err}")
        else:
            logger.error(f"Unexpected error checking knowledge_audit: {e}")

async def ensure_vector_support():
    """
    Enable pgvector, add embedding column, and (re)create match_knowledge_documents
    with tenant scoping via p_org_id.

    IMPORTANT: If a prior version of this function exists without p_org_id,
    we DROP it before recreating it, because Postgres cannot change a function
    signature with CREATE OR REPLACE.
    """
    supabase = get_supabase()
    try:
        sql_ext = "CREATE EXTENSION IF NOT EXISTS vector;"
        sql_col = "ALTER TABLE public.general_knowledge ADD COLUMN IF NOT EXISTS embedding vector(384);"
        sql_drop_old = "DROP FUNCTION IF EXISTS public.match_knowledge_documents(vector, float, int);"
        sql_func = """
        CREATE OR REPLACE FUNCTION match_knowledge_documents(
            query_embedding vector(384),
            match_threshold float,
            match_count int,
            p_org_id uuid
        )
        RETURNS TABLE(
            id int,
            org_id uuid,
            title text,
            content text,
            category text,
            keywords text[],
            similarity float
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RETURN QUERY
            SELECT
                gk.id,
                gk.org_id,
                gk.title,
                gk.content,
                gk.category,
                gk.keywords,
                1 - (gk.embedding <=> query_embedding) AS similarity
            FROM general_knowledge gk
            WHERE gk.org_id = p_org_id
                AND gk.embedding IS NOT NULL
                AND 1 - (gk.embedding <=> query_embedding) > match_threshold
            ORDER BY gk.embedding <=> query_embedding
            LIMIT match_count;
        END;
        $$;
        """
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
        }
        async with httpx.AsyncClient() as client:
            # 1. Enable pgvector
            resp_ext = await client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                json={"query": sql_ext},
                headers=headers
            )
            if resp_ext.status_code not in (200, 204):
                logger.error(f"Failed to enable pgvector: {resp_ext.text}")
            else:
                logger.info("pgvector extension enabled.")

            # 2. Add embedding column
            resp_col = await client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                json={"query": sql_col},
                headers=headers
            )
            if resp_col.status_code not in (200, 204):
                logger.error(f"Failed to add embedding column: {resp_col.text}")
            else:
                logger.info("Embedding column added to general_knowledge.")

            # 3. Drop legacy 3-arg signature if it exists (safe to call even if absent)
            resp_drop = await client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                json={"query": sql_drop_old},
                headers=headers
            )
            if resp_drop.status_code not in (200, 204):
                logger.warning(f"Drop legacy function returned: {resp_drop.text}")
            else:
                logger.info("Legacy 3-arg match_knowledge_documents dropped (if it existed).")

            # 4. Create the tenant-scoped 4-arg version
            resp_func = await client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                json={"query": sql_func},
                headers=headers
            )
            if resp_func.status_code not in (200, 204):
                logger.error(f"Failed to create match function: {resp_func.text}")
            else:
                logger.info("match_knowledge_documents (tenant-scoped, 4-arg) created.")
    except Exception as e:
        logger.error(f"Vector support migration error: {e}")

async def ensure_stock_transfers_table():
    supabase = get_supabase()
    try:
        test = await run_sync_db_call(supabase.table("locations").select("id").limit(1).execute)
        logger.info("locations table already exists.")
    except Exception as e:
        if 'relation "locations" does not exist' in str(e):
            logger.warning("Creating locations table...")
            sql = """
            CREATE TABLE IF NOT EXISTS public.locations (
                id SERIAL PRIMARY KEY,
                org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
                name VARCHAR(200) NOT NULL,
                address TEXT,
                is_warehouse BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                UNIQUE(org_id, name)
            );
            
            CREATE INDEX IF NOT EXISTS idx_locations_org ON public.locations(org_id);
            
            CREATE TABLE IF NOT EXISTS public.location_stocks (
                id SERIAL PRIMARY KEY,
                location_id INTEGER NOT NULL REFERENCES public.locations(id) ON DELETE CASCADE,
                inventory_id INTEGER NOT NULL REFERENCES public.inventory(id) ON DELETE CASCADE,
                quantity INTEGER NOT NULL DEFAULT 0,
                reserved_quantity INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ DEFAULT now(),
                UNIQUE(location_id, inventory_id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_location_stocks_location ON public.location_stocks(location_id);
            CREATE INDEX IF NOT EXISTS idx_location_stocks_inventory ON public.location_stocks(inventory_id);
            
            CREATE TABLE IF NOT EXISTS public.stock_transfers (
                id SERIAL PRIMARY KEY,
                org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
                from_location_id INTEGER REFERENCES public.locations(id) ON DELETE SET NULL,
                to_location_id INTEGER NOT NULL REFERENCES public.locations(id) ON DELETE CASCADE,
                inventory_id INTEGER NOT NULL REFERENCES public.inventory(id) ON DELETE CASCADE,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                status VARCHAR(50) DEFAULT 'pending',
                requested_by UUID REFERENCES public.profiles(id),
                approved_by UUID REFERENCES public.profiles(id),
                request_notes TEXT,
                approval_notes TEXT,
                tracking_number VARCHAR(100),
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                completed_at TIMESTAMPTZ
            );
            
            CREATE INDEX IF NOT EXISTS idx_stock_transfers_org ON public.stock_transfers(org_id);
            CREATE INDEX IF NOT EXISTS idx_stock_transfers_status ON public.stock_transfers(status);
            CREATE INDEX IF NOT EXISTS idx_stock_transfers_from_location ON public.stock_transfers(from_location_id);
            CREATE INDEX IF NOT EXISTS idx_stock_transfers_to_location ON public.stock_transfers(to_location_id);
            """
            headers = {
                "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                    json={"query": sql},
                    headers=headers
                )
                if resp.status_code not in (200, 204):
                    logger.error(f"Failed to create stock transfer tables: {resp.text}")
                else:
                    logger.info("Successfully created locations, location_stocks, and stock_transfers tables.")
    except Exception as e:
        logger.error(f"Stock transfers migration error: {e}")


async def ensure_location_stocks_constraints():
    """
    Ensure location_stocks has a UNIQUE constraint on
    (location_id, inventory_id).

    ensure_stock_transfers_table() declares this constraint via
    CREATE TABLE IF NOT EXISTS. That clause is a no-op when the table
    already exists, so on any environment where location_stocks
    predates the UNIQUE clause, the constraint is missing. Every
    .upsert(..., on_conflict="location_id,inventory_id") then fails
    with Postgres error 42P10, "no unique or exclusion constraint
    matching the ON CONFLICT specification".

    Idempotent. Also merges any pre-existing (location_id,
    inventory_id) duplicates before adding the constraint, so the
    ALTER cannot fail on a table that accumulated duplicate rows
    while unconstrained.
    """
    sql = """
    DO $$
    DECLARE
        v_constraint_exists BOOLEAN;
    BEGIN
        SELECT EXISTS (
            SELECT 1
              FROM pg_constraint c
              JOIN pg_class      t ON t.oid = c.conrelid
              JOIN pg_namespace  n ON n.oid = t.relnamespace
             WHERE n.nspname = 'public'
               AND t.relname = 'location_stocks'
               AND c.contype IN ('u', 'p')
               AND (
                   SELECT array_agg(a.attname::text ORDER BY a.attname)
                     FROM unnest(c.conkey) AS k
                     JOIN pg_attribute a
                       ON a.attrelid = c.conrelid
                      AND a.attnum   = k
               ) = ARRAY['inventory_id', 'location_id']
        ) INTO v_constraint_exists;

        IF NOT v_constraint_exists THEN
            -- Merge quantities across duplicate (location_id,
            -- inventory_id) pairs into the row with the lowest id.
            -- Preserves the running total rather than discarding rows,
            -- because the table is a balance, not an append log.
            WITH merged AS (
                SELECT
                    location_id,
                    inventory_id,
                    MIN(id)                                       AS keep_id,
                    SUM(COALESCE(quantity, 0))::integer           AS total_quantity,
                    SUM(COALESCE(reserved_quantity, 0))::integer  AS total_reserved
                  FROM public.location_stocks
                 GROUP BY location_id, inventory_id
                HAVING COUNT(*) > 1
            )
            UPDATE public.location_stocks ls
               SET quantity          = m.total_quantity,
                   reserved_quantity = m.total_reserved,
                   updated_at        = NOW()
              FROM merged m
             WHERE ls.id = m.keep_id;

            -- Delete the non-keeper rows.
            DELETE FROM public.location_stocks ls
             USING (
                SELECT
                    location_id,
                    inventory_id,
                    MIN(id) AS keep_id
                  FROM public.location_stocks
                 GROUP BY location_id, inventory_id
                HAVING COUNT(*) > 1
             ) dup
             WHERE ls.location_id  = dup.location_id
               AND ls.inventory_id = dup.inventory_id
               AND ls.id          <> dup.keep_id;

            ALTER TABLE public.location_stocks
                ADD CONSTRAINT location_stocks_location_id_inventory_id_key
                UNIQUE (location_id, inventory_id);
        END IF;
    END $$;
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
        logger.error(f"location_stocks constraint migration failed: {resp.text}")
        raise RuntimeError(f"location_stocks constraint migration failed: {resp.text}")
    logger.info("location_stocks UNIQUE(location_id, inventory_id) installed (or already present)")


async def ensure_stock_transfer_rpcs():
    """
    Install the approve/complete RPCs the /stock-transfers/{id}/status
    endpoint already calls. Without these the endpoint 500s on every
    approve/complete and stock never moves.
    """
    sql = """
DROP FUNCTION IF EXISTS public.approve_stock_transfer(INTEGER, UUID, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.complete_stock_transfer(INTEGER, UUID, TEXT, TEXT);

CREATE OR REPLACE FUNCTION public.approve_stock_transfer(
    p_transfer_id     INTEGER,
    p_user_id         UUID,
    p_notes           TEXT DEFAULT NULL,
    p_tracking_number TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_transfer RECORD;
BEGIN
    SELECT * INTO v_transfer
      FROM stock_transfers
     WHERE id = p_transfer_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Transfer % not found', p_transfer_id;
    END IF;

    IF v_transfer.status = 'completed' THEN
        RAISE EXCEPTION 'Transfer % already completed', p_transfer_id;
    END IF;

    IF v_transfer.status = 'rejected' THEN
        RAISE EXCEPTION 'Cannot approve a rejected transfer %', p_transfer_id;
    END IF;

    IF v_transfer.status = 'approved' THEN
        RETURN jsonb_build_object(
            'success',     TRUE,
            'status',      'approved',
            'transfer_id', p_transfer_id,
            'message',     'Already approved'
        );
    END IF;

    UPDATE stock_transfers
       SET status           = 'approved',
           approved_by      = p_user_id,
           approval_notes   = COALESCE(p_notes,           approval_notes),
           tracking_number  = COALESCE(p_tracking_number, tracking_number),
           updated_at       = NOW()
     WHERE id = p_transfer_id;

    RETURN jsonb_build_object(
        'success',     TRUE,
        'status',      'approved',
        'transfer_id', p_transfer_id
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.complete_stock_transfer(
    p_transfer_id     INTEGER,
    p_user_id         UUID,
    p_notes           TEXT DEFAULT NULL,
    p_tracking_number TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_transfer     RECORD;
    v_available    INTEGER;
    v_remaining    INTEGER;
    v_batch        RECORD;
    v_take         INTEGER;
    v_dest_row_id  INTEGER;
BEGIN
    SELECT * INTO v_transfer
      FROM stock_transfers
     WHERE id = p_transfer_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Transfer % not found', p_transfer_id;
    END IF;

    IF v_transfer.status = 'completed' THEN
        RAISE EXCEPTION 'Transfer % already completed', p_transfer_id;
    END IF;

    IF v_transfer.status = 'rejected' THEN
        RAISE EXCEPTION 'Cannot complete a rejected transfer %', p_transfer_id;
    END IF;

    IF v_transfer.from_location_id IS NOT NULL THEN
        SELECT COALESCE(SUM(quantity), 0) INTO v_available
          FROM location_stocks
         WHERE location_id  = v_transfer.from_location_id
           AND inventory_id = v_transfer.inventory_id;

        IF v_available < v_transfer.quantity THEN
            RAISE EXCEPTION
                'Insufficient stock at source location. Available: %, requested: %',
                v_available, v_transfer.quantity;
        END IF;

        v_remaining := v_transfer.quantity;

        FOR v_batch IN
            SELECT id, quantity
              FROM location_stocks
             WHERE location_id  = v_transfer.from_location_id
               AND inventory_id = v_transfer.inventory_id
               AND quantity     > 0
             ORDER BY expiry_date ASC NULLS LAST, id ASC
               FOR UPDATE
        LOOP
            EXIT WHEN v_remaining <= 0;

            v_take := LEAST(v_batch.quantity, v_remaining);

            IF v_take = v_batch.quantity THEN
                DELETE FROM location_stocks WHERE id = v_batch.id;
            ELSE
                UPDATE location_stocks
                   SET quantity   = quantity - v_take,
                       updated_at = NOW()
                 WHERE id = v_batch.id;
            END IF;

            v_remaining := v_remaining - v_take;
        END LOOP;
    ELSE
        UPDATE inventory
           SET current_qty = COALESCE(current_qty, 0) + v_transfer.quantity,
               updated_at  = NOW()
         WHERE id = v_transfer.inventory_id;
    END IF;

    SELECT id INTO v_dest_row_id
      FROM location_stocks
     WHERE location_id  = v_transfer.to_location_id
       AND inventory_id = v_transfer.inventory_id
     LIMIT 1;

    IF v_dest_row_id IS NOT NULL THEN
        UPDATE location_stocks
           SET quantity   = quantity + v_transfer.quantity,
               updated_at = NOW()
         WHERE id = v_dest_row_id;
    ELSE
        INSERT INTO location_stocks
            (location_id, inventory_id, quantity, reserved_quantity, updated_at)
        VALUES
            (v_transfer.to_location_id,
             v_transfer.inventory_id,
             v_transfer.quantity,
             0,
             NOW());
    END IF;

    UPDATE stock_transfers
       SET status           = 'completed',
           approved_by      = COALESCE(v_transfer.approved_by, p_user_id),
           approval_notes   = COALESCE(p_notes,           approval_notes),
           tracking_number  = COALESCE(p_tracking_number, tracking_number),
           completed_at     = NOW(),
           updated_at       = NOW()
     WHERE id = p_transfer_id;

    RETURN jsonb_build_object(
        'success',     TRUE,
        'status',      'completed',
        'transfer_id', p_transfer_id
    );
END;
$$;

GRANT EXECUTE ON FUNCTION public.approve_stock_transfer (INTEGER, UUID, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.complete_stock_transfer(INTEGER, UUID, TEXT, TEXT) TO service_role;
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
        logger.error(f"Failed to install stock transfer RPCs: {resp.text}")
        raise RuntimeError(f"stock transfer RPC migration failed: {resp.text}")
    logger.info("approve_stock_transfer + complete_stock_transfer installed")




async def ensure_decrement_stock_fefo():
    """
    Install the transactional FEFO decrement RPC.

    NOTE: location_stocks.location_id is UUID (matches locations.id),
    so p_location_id is UUID — not INTEGER.
    """
    sql = """
    DROP FUNCTION IF EXISTS public.decrement_stock_fefo(UUID, JSONB, INTEGER);
    DROP FUNCTION IF EXISTS public.decrement_stock_fefo(UUID, JSONB, INTEGER, UUID);
    DROP FUNCTION IF EXISTS public.decrement_stock_fefo(UUID, JSONB, UUID);
    DROP FUNCTION IF EXISTS public.decrement_stock_fefo(UUID, JSONB, UUID, UUID);

    CREATE OR REPLACE FUNCTION public.decrement_stock_fefo(
        p_org_id        UUID,
        p_items         JSONB,
        p_location_id   UUID,
        p_sale_id       UUID DEFAULT NULL
    )
    RETURNS JSONB
    LANGUAGE plpgsql
    SECURITY INVOKER
    AS $$
    DECLARE
        v_item           JSONB;
        v_inventory_id   INTEGER;
        v_quantity       INTEGER;
        v_remaining      INTEGER;
        v_batch          RECORD;
        v_take           INTEGER;
        v_short          JSONB := '[]'::JSONB;
        v_sale_status    TEXT;
    BEGIN
        IF p_items IS NULL OR jsonb_array_length(p_items) = 0 THEN
            RETURN jsonb_build_object('success', TRUE, 'skipped', FALSE, 'short', '[]'::JSONB);
        END IF;

        IF p_sale_id IS NOT NULL THEN
            SELECT status INTO v_sale_status
              FROM sales
             WHERE id = p_sale_id AND org_id = p_org_id
               FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'sale % not found in org %', p_sale_id, p_org_id;
            END IF;

            IF v_sale_status <> 'pending' THEN
                RETURN jsonb_build_object(
                    'success', TRUE,
                    'skipped', TRUE,
                    'reason',  'sale already ' || v_sale_status,
                    'short',   '[]'::JSONB
                );
            END IF;
        END IF;

        FOR v_item IN SELECT * FROM jsonb_array_elements(p_items)
        LOOP
            v_inventory_id := (v_item->>'inventory_id')::INTEGER;
            v_quantity     := (v_item->>'quantity')::INTEGER;

            CONTINUE WHEN v_quantity IS NULL OR v_quantity <= 0;

            PERFORM 1 FROM inventory
             WHERE id = v_inventory_id AND org_id = p_org_id
               FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'inventory % not in org %', v_inventory_id, p_org_id;
            END IF;

            v_remaining := v_quantity;

            IF p_location_id IS NOT NULL THEN
                FOR v_batch IN
                    SELECT id, quantity
                      FROM location_stocks
                     WHERE location_id = p_location_id
                       AND inventory_id = v_inventory_id
                     ORDER BY expiry_date ASC NULLS LAST, id ASC
                       FOR UPDATE
                LOOP
                    EXIT WHEN v_remaining <= 0;

                    v_take := LEAST(v_batch.quantity, v_remaining);

                    IF v_take = v_batch.quantity THEN
                        DELETE FROM location_stocks WHERE id = v_batch.id;
                    ELSE
                        UPDATE location_stocks
                           SET quantity = quantity - v_take,
                               updated_at = NOW()
                         WHERE id = v_batch.id;
                    END IF;

                    v_remaining := v_remaining - v_take;
                END LOOP;

                IF v_remaining > 0 THEN
                    v_short := v_short || jsonb_build_object(
                        'inventory_id', v_inventory_id,
                        'short_by',     v_remaining
                    );
                END IF;
            END IF;

            UPDATE inventory
               SET current_qty = GREATEST(0, COALESCE(current_qty, 0) - v_quantity),
                   updated_at  = NOW()
             WHERE id = v_inventory_id;
        END LOOP;

        IF p_sale_id IS NOT NULL THEN
            UPDATE sales
               SET status          = 'completed',
                   shipping_status = 'processing',
                   updated_at      = NOW()
             WHERE id = p_sale_id;
        END IF;

        RETURN jsonb_build_object(
            'success', TRUE,
            'skipped', FALSE,
            'short',   v_short
        );
    END;
    $$;

    GRANT EXECUTE ON FUNCTION public.decrement_stock_fefo(UUID, JSONB, UUID, UUID) TO service_role;
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
        logger.error(f"Failed to install decrement_stock_fefo: {resp.text}")
        raise RuntimeError(f"decrement_stock_fefo migration failed: {resp.text}")
    logger.info("decrement_stock_fefo RPC installed (UUID-typed location id)")


async def ensure_finalize_online_order():
    """
    Install finalize_online_order(sale_id, org_id) — an atomic transactional
    RPC that flips a pending online order to completed, decrements stock at
    the sale's location (FEFO), and marks the A/R record paid. All inside
    one Postgres transaction. Idempotent on retry.
    """
    sql = """
    DROP FUNCTION IF EXISTS public.finalize_online_order(UUID, UUID);

    CREATE OR REPLACE FUNCTION public.finalize_online_order(
        p_sale_id   UUID,
        p_org_id    UUID
    )
    RETURNS JSONB
    LANGUAGE plpgsql
    SECURITY INVOKER
    AS $$
    DECLARE
        v_sale              RECORD;
        v_item              RECORD;
        v_remaining         INTEGER;
        v_batch             RECORD;
        v_take              INTEGER;
        v_short             JSONB := '[]'::JSONB;
        v_location_id       UUID;
        v_ar_id             UUID;
    BEGIN
        -- Lock the sale row
        SELECT * INTO v_sale
          FROM sales
         WHERE id = p_sale_id AND org_id = p_org_id
           FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'sale % not found in org %', p_sale_id, p_org_id;
        END IF;

        -- Idempotent: already done, return current state
        IF v_sale.status <> 'pending' THEN
            RETURN jsonb_build_object(
                'success', TRUE,
                'skipped', TRUE,
                'reason',  'sale already ' || v_sale.status,
                'sale_id', p_sale_id,
                'status',  v_sale.status,
                'short',   '[]'::JSONB
            );
        END IF;

        v_location_id := v_sale.location_id;
        IF v_location_id IS NULL THEN
            RAISE WARNING
                'finalize_online_order: sale % has no location_id; location_stocks will not decrement',
                p_sale_id;
        END IF;

        -- Decrement stock for each item
        FOR v_item IN
            SELECT inventory_id, quantity
              FROM sale_items
             WHERE sale_id = p_sale_id
        LOOP
            CONTINUE WHEN v_item.quantity IS NULL OR v_item.quantity <= 0;

            PERFORM 1 FROM inventory
             WHERE id = v_item.inventory_id AND org_id = p_org_id
               FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'inventory % not in org %', v_item.inventory_id, p_org_id;
            END IF;

            v_remaining := v_item.quantity;

            IF v_location_id IS NOT NULL THEN
                FOR v_batch IN
                    SELECT id, quantity
                      FROM location_stocks
                     WHERE location_id = v_location_id
                       AND inventory_id = v_item.inventory_id
                     ORDER BY expiry_date ASC NULLS LAST, id ASC
                       FOR UPDATE
                LOOP
                    EXIT WHEN v_remaining <= 0;

                    v_take := LEAST(v_batch.quantity, v_remaining);

                    IF v_take = v_batch.quantity THEN
                        DELETE FROM location_stocks WHERE id = v_batch.id;
                    ELSE
                        UPDATE location_stocks
                           SET quantity   = quantity - v_take,
                               updated_at = NOW()
                         WHERE id = v_batch.id;
                    END IF;

                    v_remaining := v_remaining - v_take;
                END LOOP;

                IF v_remaining > 0 THEN
                    v_short := v_short || jsonb_build_object(
                        'inventory_id', v_item.inventory_id,
                        'short_by',     v_remaining
                    );
                END IF;
            END IF;

            UPDATE inventory
               SET current_qty = GREATEST(0, COALESCE(current_qty, 0) - v_item.quantity),
                   updated_at  = NOW()
             WHERE id = v_item.inventory_id;
        END LOOP;

        -- Flip sale to completed
        UPDATE sales
           SET status          = 'completed',
               shipping_status = COALESCE(shipping_status, 'processing'),
               updated_at      = NOW()
         WHERE id = p_sale_id;

        -- Upsert A/R record — create if missing, mark paid if exists
        SELECT id INTO v_ar_id
          FROM accounts_receivable
         WHERE sale_id = p_sale_id
         LIMIT 1;

        IF v_ar_id IS NULL THEN
            INSERT INTO accounts_receivable (
                org_id, branch_id, sale_id, customer_id,
                amount, paid_amount, status, due_date, created_at
            ) VALUES (
                p_org_id,
                NULLIF(v_sale.branch_id::text, '')::uuid,
                p_sale_id,
                NULLIF(v_sale.user_id::text,  '')::uuid,
                v_sale.total_amount,
                v_sale.total_amount,
                'paid',
                CURRENT_DATE,
                NOW()
            )
            RETURNING id INTO v_ar_id;
        ELSE
            UPDATE accounts_receivable
               SET paid_amount = amount,
                   status      = 'paid',
                   updated_at  = NOW()
             WHERE id = v_ar_id;
        END IF;

        RETURN jsonb_build_object(
            'success',   TRUE,
            'skipped',   FALSE,
            'sale_id',   p_sale_id,
            'status',    'completed',
            'ar_id',     v_ar_id,
            'short',     v_short
        );
    END;
    $$;

    GRANT EXECUTE ON FUNCTION public.finalize_online_order(UUID, UUID) TO service_role;
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
        logger.error(f"Failed to install finalize_online_order: {resp.text}")
        raise RuntimeError(f"finalize_online_order migration failed: {resp.text}")
    logger.info("finalize_online_order RPC installed")
async def ensure_webhook_events():
    """
    Webhook idempotency: dedupe duplicate deliveries, allow safe retry
    after a 5xx, and recover from crashed in-flight claims via TTL.
    """
    sql = """
    CREATE TABLE IF NOT EXISTS public.webhook_events (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        provider      TEXT NOT NULL,
        event_key     TEXT NOT NULL,
        event_type    TEXT,
        org_id        UUID,
        payload_hash  TEXT,
        claimed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        processed_at  TIMESTAMPTZ,
        UNIQUE (provider, event_key)
    );
    CREATE INDEX IF NOT EXISTS idx_webhook_events_org
        ON public.webhook_events (org_id, processed_at DESC);

    CREATE OR REPLACE FUNCTION public.claim_webhook_event(
        p_provider             TEXT,
        p_event_key            TEXT,
        p_event_type           TEXT,
        p_org_id               UUID,
        p_payload_hash         TEXT,
        p_stale_after_seconds  INTEGER DEFAULT 300
    ) RETURNS UUID
    LANGUAGE plpgsql
    AS $$
    DECLARE
        v_id            UUID;
        v_processed_at  TIMESTAMPTZ;
        v_claimed_at    TIMESTAMPTZ;
    BEGIN
        INSERT INTO webhook_events (provider, event_key, event_type, org_id, payload_hash)
        VALUES (p_provider, p_event_key, p_event_type, p_org_id, p_payload_hash)
        ON CONFLICT (provider, event_key) DO NOTHING
        RETURNING id INTO v_id;

        IF v_id IS NOT NULL THEN
            RETURN v_id;
        END IF;

        SELECT processed_at, claimed_at
          INTO v_processed_at, v_claimed_at
          FROM webhook_events
         WHERE provider = p_provider AND event_key = p_event_key
           FOR UPDATE;

        IF v_processed_at IS NOT NULL THEN
            RETURN NULL;
        END IF;

        IF v_claimed_at > NOW() - (p_stale_after_seconds || ' seconds')::INTERVAL THEN
            RETURN NULL;
        END IF;

        UPDATE webhook_events
           SET claimed_at = NOW()
         WHERE provider = p_provider AND event_key = p_event_key;

        RETURN (SELECT id FROM webhook_events
                 WHERE provider = p_provider AND event_key = p_event_key);
    END;
    $$;

    CREATE OR REPLACE FUNCTION public.mark_webhook_event_processed(p_claim_id UUID)
    RETURNS VOID
    LANGUAGE plpgsql
    AS $$
    BEGIN
        UPDATE webhook_events SET processed_at = NOW() WHERE id = p_claim_id;
    END;
    $$;

    CREATE OR REPLACE FUNCTION public.release_webhook_event_claim(p_claim_id UUID)
    RETURNS VOID
    LANGUAGE plpgsql
    AS $$
    BEGIN
        DELETE FROM webhook_events
         WHERE id = p_claim_id AND processed_at IS NULL;
    END;
    $$;

    GRANT EXECUTE ON FUNCTION public.claim_webhook_event(TEXT, TEXT, TEXT, UUID, TEXT, INTEGER) TO service_role;
    GRANT EXECUTE ON FUNCTION public.mark_webhook_event_processed(UUID) TO service_role;
    GRANT EXECUTE ON FUNCTION public.release_webhook_event_claim(UUID) TO service_role;
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
        logger.error(f"Failed to install webhook_events: {resp.text}")
        raise RuntimeError(f"webhook_events migration failed: {resp.text}")
    logger.info("webhook_events table and RPCs installed")


async def claim_webhook_event(
    provider: str,
    event_key: str,
    event_type: Optional[str],
    org_id: Optional[str],
    payload_hash: str,
) -> Optional[str]:
    resp = await run_sync_db_call(
        get_supabase().rpc("claim_webhook_event", {
            "p_provider":     provider,
            "p_event_key":    event_key,
            "p_event_type":   event_type,
            "p_org_id":       org_id,
            "p_payload_hash": payload_hash,
        }).execute
    )
    data = resp.data
    if data is None:
        return None
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return data.get("claim_webhook_event")
    return data


async def _call_void_rpc(rpc_name: str, payload: dict) -> None:
    """
    Call a Supabase RPC that returns VOID (204 No Content).
    The postgrest-py client cannot parse an empty 204 body, so we
    bypass it and use httpx directly.
    """
    url = f"{SUPABASE_URL}/rest/v1/rpc/{rpc_name}"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.post(url, json=payload, headers=headers)
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"{rpc_name} failed: {resp.status_code} {resp.text}")


async def mark_webhook_event_processed(claim_id: str) -> None:
    if not claim_id:
        return
    try:
        await _call_void_rpc("mark_webhook_event_processed", {"p_claim_id": claim_id})
    except Exception as e:
        logger.error(f"mark_webhook_event_processed({claim_id}) failed: {e}")


async def release_webhook_event_claim(claim_id: str) -> None:
    if not claim_id:
        return
    try:
        await _call_void_rpc("release_webhook_event_claim", {"p_claim_id": claim_id})
    except Exception as e:
        logger.error(f"release_webhook_event_claim({claim_id}) failed: {e}")


async def ensure_stock_reconciliation():
    """
    Audit + heal functions comparing inventory.current_qty against
    SUM(location_stocks.quantity) per inventory item.
    """
    sql = """
    CREATE OR REPLACE FUNCTION public.audit_stock_drift(p_org_id UUID)
    RETURNS TABLE (
        inventory_id    INTEGER,
        item_code       TEXT,
        description     TEXT,
        current_qty     INTEGER,
        location_total  INTEGER,
        drift           INTEGER
    )
    LANGUAGE plpgsql
    STABLE
    AS $$
    BEGIN
        RETURN QUERY
        SELECT
            i.id,
            i.item_code,
            i.description,
            COALESCE(i.current_qty, 0)::INTEGER,
            COALESCE(SUM(ls.quantity), 0)::INTEGER,
            (COALESCE(i.current_qty, 0) - COALESCE(SUM(ls.quantity), 0))::INTEGER
          FROM inventory i
          LEFT JOIN location_stocks ls ON ls.inventory_id = i.id
         WHERE i.org_id = p_org_id
         GROUP BY i.id, i.item_code, i.description, i.current_qty
        HAVING COALESCE(i.current_qty, 0) <> COALESCE(SUM(ls.quantity), 0)::INTEGER;
    END;
    $$;

    CREATE OR REPLACE FUNCTION public.heal_stock_drift(
        p_org_id               UUID,
        p_inventory_id         INTEGER,
        p_default_location_id  INTEGER
    ) RETURNS JSONB
    LANGUAGE plpgsql
    AS $$
    DECLARE
        v_current      INTEGER;
        v_loc_total    INTEGER;
        v_drift        INTEGER;
        v_remaining    INTEGER;
        v_batch        RECORD;
        v_take         INTEGER;
    BEGIN
        SELECT COALESCE(current_qty, 0) INTO v_current
          FROM inventory
         WHERE id = p_inventory_id AND org_id = p_org_id
           FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'inventory % not in org %', p_inventory_id, p_org_id;
        END IF;

        SELECT COALESCE(SUM(quantity), 0)::INTEGER INTO v_loc_total
          FROM location_stocks
         WHERE inventory_id = p_inventory_id;

        v_drift := v_current - v_loc_total;

        IF v_drift = 0 THEN
            RETURN jsonb_build_object('healed', FALSE, 'reason', 'in sync');
        END IF;

        IF v_drift > 0 THEN
            INSERT INTO location_stocks
                (location_id, inventory_id, quantity, reserved_quantity, updated_at)
            VALUES
                (p_default_location_id, p_inventory_id, v_drift, 0, NOW())
            ON CONFLICT (location_id, inventory_id)
            DO UPDATE SET quantity   = location_stocks.quantity + EXCLUDED.quantity,
                          updated_at = NOW();
        ELSE
            v_remaining := -v_drift;
            FOR v_batch IN
                SELECT id, quantity
                  FROM location_stocks
                 WHERE inventory_id = p_inventory_id
                 ORDER BY expiry_date ASC NULLS LAST, id ASC
                   FOR UPDATE
            LOOP
                EXIT WHEN v_remaining <= 0;
                v_take := LEAST(v_batch.quantity, v_remaining);
                IF v_take = v_batch.quantity THEN
                    DELETE FROM location_stocks WHERE id = v_batch.id;
                ELSE
                    UPDATE location_stocks
                       SET quantity = quantity - v_take, updated_at = NOW()
                     WHERE id = v_batch.id;
                END IF;
                v_remaining := v_remaining - v_take;
            END LOOP;
        END IF;

        RETURN jsonb_build_object('healed', TRUE, 'drift_corrected', v_drift);
    END;
    $$;

    GRANT EXECUTE ON FUNCTION public.audit_stock_drift(UUID) TO service_role;
    GRANT EXECUTE ON FUNCTION public.heal_stock_drift(UUID, INTEGER, INTEGER) TO service_role;
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
        logger.error(f"Failed to install stock reconciliation: {resp.text}")
        raise RuntimeError(f"stock reconciliation migration failed: {resp.text}")
    logger.info("audit_stock_drift + heal_stock_drift installed")



async def backfill_knowledge_embeddings():
    supabase = get_supabase()
    docs = await run_sync_db_call(supabase.table("general_knowledge").select("id, content").is_("embedding", "null").execute)
    if not docs.data:
        logger.info("No knowledge entries without embeddings. Backfill not needed.")
        return
    updated = 0
    for doc in docs.data:
        emb = get_embedding(doc["content"])
        if emb:
            await run_sync_db_call(supabase.table("general_knowledge").update({"embedding": emb}).eq("id", doc["id"]).execute)
            updated += 1
    logger.info(f"Backfilled embeddings for {updated} knowledge entries.")


async def ensure_org_registry_schema():
    """
    Adds slug, vertical, storefront_config, storefront_published to organisations.
    Runs idempotently — safe to call on every startup.
    """
    sql = """
    ALTER TABLE public.organisations
        ADD COLUMN IF NOT EXISTS slug                 TEXT,
        ADD COLUMN IF NOT EXISTS vertical             TEXT DEFAULT 'retail',
        ADD COLUMN IF NOT EXISTS storefront_config    JSONB DEFAULT '{}'::jsonb,
        ADD COLUMN IF NOT EXISTS storefront_published BOOLEAN DEFAULT FALSE;

    CREATE UNIQUE INDEX IF NOT EXISTS idx_organisations_slug
        ON public.organisations(slug)
        WHERE slug IS NOT NULL;

    -- Backfill any orgs created before the slug column existed.
    UPDATE public.organisations
       SET slug = sub.clean_slug
      FROM (
          SELECT id,
                 TRIM(BOTH '-' FROM
                   REGEXP_REPLACE(
                     REGEXP_REPLACE(LOWER(org_name), '[^a-z0-9]+', '-', 'g'),
                     '-+', '-', 'g'
                   )
                 ) AS clean_slug
            FROM public.organisations
           WHERE slug IS NULL
      ) AS sub
     WHERE organisations.id = sub.id
       AND sub.clean_slug <> '';

    -- Fill any remaining nulls with a uuid-suffixed fallback.
    UPDATE public.organisations
       SET slug = 'org-' || SUBSTRING(id::text, 1, 8)
     WHERE slug IS NULL;

    -- Same for vertical.
    UPDATE public.organisations
       SET vertical = 'retail'
     WHERE vertical IS NULL;
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
        logger.error(f"org_registry_schema migration failed: {resp.text}")
        raise RuntimeError(f"org_registry_schema migration failed: {resp.text}")
    logger.info("organisations registry schema installed (slug, vertical, storefront_config, storefront_published)")



# ===================== STREAMLIT APP MIGRATIONS =====================
async def ensure_alert_log_table():
    """
    ═══════════════════════════════════════════════════════════════════════
    BELT-AND-BRACES MIGRATION — 2026-10-13. DO NOT REVERT.

    Structure follows ensure_branches_table(): no pre-flight existence
    check, the full SQL runs on every boot, every statement is
    idempotent (CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS /
    CREATE INDEX IF NOT EXISTS), and any failure raises so the boot
    aborts loudly instead of serving a broken schema.

    WHY THIS REPLACED THE OLD try/except SHAPE:

        The previous version only ran its SQL when a probe query threw
        `relation "alert_log" does not exist`. That meant:

          1. A drifted table — present but missing a column — was never
             healed. The probe returned success, the CREATE never fired,
             and the missing column stayed missing until something broke
             at runtime. This is exactly the class of drift that produced
             the 08:42:26 startup crash on 2026-10-13.

          2. Two round trips per boot instead of one. The probe was a
             live GET against the table on every cold start.

          3. The schema was only ever validated against itself. A fresh
             CREATE from an outdated template could produce a table that
             did not match production — and nothing would notice until a
             query failed.

        The new shape closes all three. It matches the branches pattern,
        runs one SQL round trip, and reconciles against the live schema
        on every boot rather than betting on the first version being
        right forever.

    SCHEMA AUTHORITY:

        Column list below is copied verbatim from the live alert_log
        schema, verified 2026-10-13 with:

            SELECT column_name, data_type, is_nullable
              FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'alert_log'
             ORDER BY ordinal_position;

        If any of these ever drift on production, re-run the query
        above and reconcile this list. Do not eyeball it.

    COLUMNS THE OLD TEMPLATE GOT WRONG:

        location_id       INTEGER → UUID   (real type; the old CREATE
                                            would have rejected every
                                            locations.id value)

        product_id        INTEGER → removed (column never existed; the
                                            real FK is inventory_id)

        action_notes      absent  → added   (read by the resolve handler)
        item_code         absent  → added   (read by /alerts)
        description       absent  → added   (read by /alerts)

    NOT NULL NUANCE:

        The CREATE makes alert_type NOT NULL, matching production.
        The ALTER adds it as nullable, because Postgres will not add a
        NOT NULL column to a populated table without a default. On any
        table that already has the column (i.e. production), the ALTER
        is a no-op and the NOT NULL from the CREATE stands. The nullable
        path only fires on a table that is missing the column entirely —
        a state that no live environment should be in.

    COMPANION FUNCTION:

        ensure_alert_log_backfill() resolves org_id for legacy rows by
        joining inventory_id → inventory.org_id and, as a fallback,
        location_id → locations.org_id. It runs immediately after this
        function in startup_event. Both join keys are indexed below.
    ═══════════════════════════════════════════════════════════════════════
    """
    sql = """
    -- ── 1. Create the table if it is missing entirely. ──
    -- Column order and types match the live schema. This path only
    -- fires on a fresh environment or after a database reset.
    CREATE TABLE IF NOT EXISTS public.alert_log (
        id                SERIAL PRIMARY KEY,
        location_id       UUID,
        inventory_id      INTEGER,
        batch             VARCHAR(100),
        alert_type        VARCHAR(50) NOT NULL,
        details           TEXT,
        action_taken      TEXT,
        action_date       TIMESTAMPTZ,
        action_type       VARCHAR(50),
        affected_quantity INTEGER,
        created_at        TIMESTAMPTZ DEFAULT now(),
        updated_at        TIMESTAMPTZ DEFAULT now(),
        action_notes      TEXT,
        item_code         VARCHAR(200),
        description       TEXT,
        org_id            UUID REFERENCES public.organisations(id) ON DELETE CASCADE
    );

    -- ── 2. Heal a drifted table by adding any missing columns. ──
    -- ADD COLUMN IF NOT EXISTS is a no-op on a column that already
    -- exists, so this is safe to run on every boot. This block is the
    -- actual difference from the old try/except shape: a table that
    -- exists but has lost a column gets reconciled here instead of
    -- staying broken until something at runtime blows up.
    ALTER TABLE public.alert_log
        ADD COLUMN IF NOT EXISTS location_id       UUID,
        ADD COLUMN IF NOT EXISTS inventory_id      INTEGER,
        ADD COLUMN IF NOT EXISTS batch             VARCHAR(100),
        ADD COLUMN IF NOT EXISTS alert_type        VARCHAR(50),
        ADD COLUMN IF NOT EXISTS details           TEXT,
        ADD COLUMN IF NOT EXISTS action_taken      TEXT,
        ADD COLUMN IF NOT EXISTS action_date       TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS action_type       VARCHAR(50),
        ADD COLUMN IF NOT EXISTS affected_quantity INTEGER,
        ADD COLUMN IF NOT EXISTS created_at        TIMESTAMPTZ DEFAULT now(),
        ADD COLUMN IF NOT EXISTS updated_at        TIMESTAMPTZ DEFAULT now(),
        ADD COLUMN IF NOT EXISTS action_notes      TEXT,
        ADD COLUMN IF NOT EXISTS item_code         VARCHAR(200),
        ADD COLUMN IF NOT EXISTS description       TEXT,
        ADD COLUMN IF NOT EXISTS org_id            UUID;

    -- ── 3. Ensure the org_id foreign key exists. ──
    -- ADD COLUMN IF NOT EXISTS above cannot attach a REFERENCES clause
    -- to a column that already existed, and Postgres has no
    -- ADD CONSTRAINT IF NOT EXISTS. A DO block with a catalogue
    -- lookup is the idempotent way to add it only when absent.
    -- The constraint name is the one Postgres auto-generates for the
    -- CREATE-path FK, so this block correctly recognises and skips it.
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
              FROM pg_constraint c
              JOIN pg_attribute  a
                ON a.attrelid = c.conrelid
               AND a.attnum   = ANY (c.conkey)
             WHERE c.conrelid = 'public.alert_log'::regclass
               AND c.contype  = 'f'
               AND a.attname  = 'org_id'
        ) THEN
            ALTER TABLE public.alert_log
                ADD CONSTRAINT alert_log_org_id_fkey
                FOREIGN KEY (org_id)
                REFERENCES public.organisations(id)
                ON DELETE CASCADE;
        END IF;
    END $$;

    -- ── 4. Indexes. ──
    -- Composite on (org_id, created_at DESC) because both /alerts and
    -- /alerts/dashboard filter by org_id and order by created_at.
    CREATE INDEX IF NOT EXISTS idx_alert_log_org
        ON public.alert_log(org_id, created_at DESC);

    -- inventory_id is the primary join key used by
    -- ensure_alert_log_backfill to resolve org_id from inventory.
    CREATE INDEX IF NOT EXISTS idx_alert_log_inventory
        ON public.alert_log(inventory_id);

    -- location_id is the secondary backfill join key and the filter
    -- key for location-scoped alert reads.
    CREATE INDEX IF NOT EXISTS idx_alert_log_location
        ON public.alert_log(location_id);

    -- alert_type powers the type filter on /alerts and the type
    -- breakdown on /alerts/dashboard.
    CREATE INDEX IF NOT EXISTS idx_alert_log_type
        ON public.alert_log(alert_type);

    -- Standalone created_at index for the unfiltered recent-alerts scan.
    CREATE INDEX IF NOT EXISTS idx_alert_log_created
        ON public.alert_log(created_at DESC);
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
        logger.error(f"alert_log table migration failed: {resp.text}")
        raise RuntimeError(f"alert_log table migration failed: {resp.text}")
    logger.info("alert_log table installed (or already present)")

async def ensure_alert_log_backfill() -> None:
    """
    Backfill alert_log.org_id for rows written before the org_id column
    existed.

    The real alert_log schema is:
        id, location_id (UUID), inventory_id (INTEGER), batch, alert_type,
        details, action_taken, action_date, action_type, affected_quantity,
        created_at, updated_at, action_notes, item_code, description, org_id

    There is no product_id column — the tenant is resolved from
    inventory_id (INTEGER FK to inventory.id), with a fallback via
    location_id (UUID FK to locations.id), and finally to
    PUBLIC_STORE_ORG_ID for any rows still orphaned.

    Path 1 (preferred): join through inventory_id -> inventory.org_id.
    Both sides are INTEGER, so this is a same-type join with no cast.

    Path 2 (secondary): join through location_id -> locations.org_id.
    alert_log.location_id is UUID, but locations.id has been declared as
    both INTEGER and UUID across different eras of this schema, so both
    sides are cast to text for a type-agnostic match.

    Path 3 (fallback): any rows still NULL after Paths 1 and 2 go to
    PUBLIC_STORE_ORG_ID — the public storefront org. Without this,
    legacy rows become invisible to every org once the endpoint filter
    is applied.

    Idempotent. Safe to run on every boot.
    """
    if not PUBLIC_STORE_ORG_ID:
        logger.warning(
            "ensure_alert_log_backfill: PUBLIC_STORE_ORG_ID not set — "
            "orphan alert_log rows will stay NULL and be invisible to all orgs"
        )

    sql_parts = [
        # Path 1: via inventory_id -> inventory.org_id (INTEGER join).
        # alert_log.inventory_id is the real FK; product_id never existed.
        """
        UPDATE public.alert_log al
           SET org_id = i.org_id
          FROM public.inventory i
         WHERE al.inventory_id = i.id
           AND al.org_id IS NULL
           AND i.org_id IS NOT NULL;
        """,
        # Path 2: via location_id -> locations.org_id (UUID/text join).
        # alert_log.location_id is UUID. locations.id has been both
        # INTEGER and UUID historically, so cast both sides to text for
        # a type-agnostic match.
        """
        UPDATE public.alert_log al
           SET org_id = l.org_id
          FROM public.locations l
         WHERE al.location_id::text = l.id::text
           AND al.org_id IS NULL
           AND l.org_id IS NOT NULL;
        """,
    ]

    if PUBLIC_STORE_ORG_ID:
        # Path 3: anything still NULL goes to the public store org.
        sql_parts.append(f"""
            UPDATE public.alert_log
               SET org_id = '{PUBLIC_STORE_ORG_ID}'::uuid
             WHERE org_id IS NULL;
        """)

    sql = "\n".join(sql_parts)

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
        logger.error(f"alert_log backfill failed: {resp.text}")
        raise RuntimeError(f"alert_log backfill failed: {resp.text}")
    logger.info("alert_log org_id backfill complete")
    

async def ensure_transfer_suggestions_table():
    """
    ═══════════════════════════════════════════════════════════════════════
    BELT-AND-BRACES MIGRATION — 2026-10-13. DO NOT REVERT.

    Same shape as ensure_branches_table, ensure_alert_log_table, and
    ensure_stock_limits_table: full SQL on every boot, every statement
    idempotent, any failure raises so the boot aborts rather than
    serving a drifted schema.

    WRONG IN THE PREVIOUS VERSION (verified against the live schema on
    2026-10-13 via information_schema):

        from_location_id INTEGER         → real type is UUID.
        to_location_id   INTEGER NOT NULL → real type is UUID, and the
                                            live column is nullable, not
                                            NOT NULL.
        product_id       INTEGER NOT NULL → column does not exist at all.
                                            The real FK is
                                            inventory_id INTEGER.

        A fresh CREATE from the old template would have produced a
        table with a NOT NULL product_id that no writer fills and a
        NOT NULL to_location_id that the same writer would have been
        inserting as a UUID into an INTEGER slot — every single insert
        on a reset environment would have failed at the type boundary
        or the null constraint. Nothing would have noticed until the
        first transfer suggestion was attempted.

    MISSING FROM THE PREVIOUS VERSION:
        inventory_id, org_id

    COLUMN AUTHORITY:
        Verified 2026-10-13 with:
            SELECT column_name, data_type, is_nullable
              FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'transfer_suggestions'
             ORDER BY ordinal_position;

    NOT-NULL NUANCE:
        quantity is NOT NULL on production. The CREATE below preserves
        that. The ALTER adds it as nullable, because Postgres will not
        add a NOT NULL column to a populated table without a default.
        On any table that already has the column the ALTER is a no-op
        and the NOT NULL from the CREATE stands.

    COMPANION:
        ensure_transfer_suggestions_backfill() resolves org_id for
        legacy rows via inventory_id → inventory.org_id (primary),
        from_location_id → locations.org_id (fallback),
        to_location_id → locations.org_id (fallback), and finally
        PUBLIC_STORE_ORG_ID for any remaining orphans.
    ═══════════════════════════════════════════════════════════════════════
    """
    sql = """
    -- ── 1. Create the table if missing. ──
    CREATE TABLE IF NOT EXISTS public.transfer_suggestions (
        id                 SERIAL PRIMARY KEY,
        from_location_id   UUID,
        to_location_id     UUID,
        inventory_id       INTEGER,
        batch              VARCHAR(100),
        quantity           INTEGER NOT NULL,
        completed_quantity INTEGER DEFAULT 0,
        urgency            VARCHAR(20),
        reason             TEXT,
        status             VARCHAR(20) DEFAULT 'Pending',
        notes              TEXT,
        created_at         TIMESTAMPTZ DEFAULT now(),
        updated_at         TIMESTAMPTZ DEFAULT now(),
        last_updated       TIMESTAMPTZ DEFAULT now(),
        org_id             UUID REFERENCES public.organisations(id) ON DELETE CASCADE
    );

    -- ── 2. Heal a drifted table by adding missing columns. ──
    ALTER TABLE public.transfer_suggestions
        ADD COLUMN IF NOT EXISTS from_location_id   UUID,
        ADD COLUMN IF NOT EXISTS to_location_id     UUID,
        ADD COLUMN IF NOT EXISTS inventory_id       INTEGER,
        ADD COLUMN IF NOT EXISTS batch              VARCHAR(100),
        ADD COLUMN IF NOT EXISTS quantity           INTEGER,
        ADD COLUMN IF NOT EXISTS completed_quantity INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS urgency            VARCHAR(20),
        ADD COLUMN IF NOT EXISTS reason             TEXT,
        ADD COLUMN IF NOT EXISTS status             VARCHAR(20) DEFAULT 'Pending',
        ADD COLUMN IF NOT EXISTS notes              TEXT,
        ADD COLUMN IF NOT EXISTS created_at         TIMESTAMPTZ DEFAULT now(),
        ADD COLUMN IF NOT EXISTS updated_at         TIMESTAMPTZ DEFAULT now(),
        ADD COLUMN IF NOT EXISTS last_updated       TIMESTAMPTZ DEFAULT now(),
        ADD COLUMN IF NOT EXISTS org_id             UUID;

    -- ── 3. Ensure the org_id FK exists (ADD COLUMN cannot attach one). ──
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
              FROM pg_constraint c
              JOIN pg_attribute  a
                ON a.attrelid = c.conrelid
               AND a.attnum   = ANY (c.conkey)
             WHERE c.conrelid = 'public.transfer_suggestions'::regclass
               AND c.contype  = 'f'
               AND a.attname  = 'org_id'
        ) THEN
            ALTER TABLE public.transfer_suggestions
                ADD CONSTRAINT transfer_suggestions_org_id_fkey
                FOREIGN KEY (org_id)
                REFERENCES public.organisations(id)
                ON DELETE CASCADE;
        END IF;
    END $$;

    -- ── 4. Indexes. ──
    -- Composite tenant + recency, since the endpoint filters by org_id
    -- and orders by created_at DESC.
    CREATE INDEX IF NOT EXISTS idx_transfer_suggestions_org_created
        ON public.transfer_suggestions(org_id, created_at DESC);

    -- Join key used by the backfill to resolve org_id from inventory.
    CREATE INDEX IF NOT EXISTS idx_transfer_suggestions_inventory
        ON public.transfer_suggestions(inventory_id);

    -- Location filter keys. Both columns are UUID.
    CREATE INDEX IF NOT EXISTS idx_transfer_suggestions_from
        ON public.transfer_suggestions(from_location_id);
    CREATE INDEX IF NOT EXISTS idx_transfer_suggestions_to
        ON public.transfer_suggestions(to_location_id);

    -- Status filter used by the endpoint.
    CREATE INDEX IF NOT EXISTS idx_transfer_suggestions_status
        ON public.transfer_suggestions(status);
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
        logger.error(f"transfer_suggestions table migration failed: {resp.text}")
        raise RuntimeError(f"transfer_suggestions table migration failed: {resp.text}")
    logger.info("transfer_suggestions table installed (or already present)")

async def ensure_transfer_suggestions_backfill() -> None:
    """
    Backfill transfer_suggestions.org_id for rows written before the
    column existed.

    Three join paths, in preference order:

        1. inventory_id     INTEGER → inventory.id     → inventory.org_id
        2. from_location_id UUID    → locations.id     → locations.org_id
        3. to_location_id   UUID    → locations.id     → locations.org_id

    inventory_id is preferred because it is a direct FK to the item
    the suggestion is about, and inventory rows always carry org_id.
    The location joins are fallbacks for rows where inventory_id is
    NULL or points at a deleted inventory row.

    Any row that resolves via none of the three goes to
    PUBLIC_STORE_ORG_ID, because once the endpoint filter is applied,
    a NULL org_id makes the row invisible to every org.

    Idempotent. Safe on every boot.
    """
    if not PUBLIC_STORE_ORG_ID:
        logger.warning(
            "ensure_transfer_suggestions_backfill: PUBLIC_STORE_ORG_ID not set — "
            "orphan transfer_suggestions rows will stay NULL and invisible to all orgs"
        )

    sql_parts = [
        # Path 1: via inventory_id → inventory.org_id (INTEGER join)
        """
        UPDATE public.transfer_suggestions ts
           SET org_id = i.org_id
          FROM public.inventory i
         WHERE ts.inventory_id = i.id
           AND ts.org_id IS NULL
           AND i.org_id IS NOT NULL;
        """,
        # Path 2: via from_location_id → locations.org_id (UUID join)
        """
        UPDATE public.transfer_suggestions ts
           SET org_id = l.org_id
          FROM public.locations l
         WHERE ts.from_location_id::text = l.id::text
           AND ts.org_id IS NULL
           AND l.org_id IS NOT NULL;
        """,
        # Path 3: via to_location_id → locations.org_id (UUID join)
        """
        UPDATE public.transfer_suggestions ts
           SET org_id = l.org_id
          FROM public.locations l
         WHERE ts.to_location_id::text = l.id::text
           AND ts.org_id IS NULL
           AND l.org_id IS NOT NULL;
        """,
    ]

    if PUBLIC_STORE_ORG_ID:
        sql_parts.append(f"""
            UPDATE public.transfer_suggestions
               SET org_id = '{PUBLIC_STORE_ORG_ID}'::uuid
             WHERE org_id IS NULL;
        """)

    sql = "\n".join(sql_parts)

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
        logger.error(f"transfer_suggestions backfill failed: {resp.text}")
        raise RuntimeError(f"transfer_suggestions backfill failed: {resp.text}")
    logger.info("transfer_suggestions org_id backfill complete")



async def ensure_stock_limits_table():
    """
    ═══════════════════════════════════════════════════════════════════════
    BELT-AND-BRACES MIGRATION — 2026-10-13. DO NOT REVERT.

    Mirrors ensure_branches_table and ensure_alert_log_table: full SQL on
    every boot, every statement idempotent, any failure raises so the boot
    aborts rather than serving a drifted schema.

    WRONG IN THE PREVIOUS VERSION (verified against the live schema on
    2026-10-13 via information_schema):

        location_id INTEGER       → real type is UUID.
        product_id INTEGER NOT NULL → column does not exist at all.
                                     The real FK is inventory_id INTEGER.
                                     A fresh CREATE would have created a
                                     NOT NULL column that no writer fills,
                                     so every insert on a reset env would
                                     have failed with "null value in column
                                     product_id violates not-null constraint".

    MISSING FROM THE PREVIOUS VERSION:
        inventory_id, org_id

    NO NOT-NULL ON inventory_id:
        The live column is nullable. Making it NOT NULL here would break
        any existing NULL row and any writer that inserts a stock_limits
        row without a product association. Leaving it nullable matches
        reality.

    COLUMN AUTHORITY:
        Verified 2026-10-13 with:
            SELECT column_name, data_type, is_nullable
              FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'stock_limits'
             ORDER BY ordinal_position;

    COMPANION:
        ensure_stock_limits_backfill() resolves org_id for legacy rows via
        inventory_id → inventory.org_id (primary) and location_id →
        locations.org_id (fallback), then PUBLIC_STORE_ORG_ID for any
        remaining orphans. Both join keys are indexed below.
    ═══════════════════════════════════════════════════════════════════════
    """
    sql = """
    -- ── 1. Create the table if missing. ──
    CREATE TABLE IF NOT EXISTS public.stock_limits (
        id                SERIAL PRIMARY KEY,
        location_id       UUID,
        inventory_id      INTEGER,
        avg_daily_demand  NUMERIC DEFAULT 0,
        safety_stock      INTEGER DEFAULT 0,
        reorder_point     INTEGER DEFAULT 0,
        max_stock         INTEGER DEFAULT 0,
        calculated_at     TIMESTAMPTZ DEFAULT now(),
        updated_at        TIMESTAMPTZ DEFAULT now(),
        org_id            UUID REFERENCES public.organisations(id) ON DELETE CASCADE
    );

    -- ── 2. Heal a drifted table by adding missing columns. ──
    ALTER TABLE public.stock_limits
        ADD COLUMN IF NOT EXISTS location_id       UUID,
        ADD COLUMN IF NOT EXISTS inventory_id      INTEGER,
        ADD COLUMN IF NOT EXISTS avg_daily_demand  NUMERIC DEFAULT 0,
        ADD COLUMN IF NOT EXISTS safety_stock      INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS reorder_point     INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS max_stock         INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS calculated_at     TIMESTAMPTZ DEFAULT now(),
        ADD COLUMN IF NOT EXISTS updated_at        TIMESTAMPTZ DEFAULT now(),
        ADD COLUMN IF NOT EXISTS org_id            UUID;

    -- ── 3. Ensure the org_id FK exists (ADD COLUMN cannot attach one). ──
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
              FROM pg_constraint c
              JOIN pg_attribute  a
                ON a.attrelid = c.conrelid
               AND a.attnum   = ANY (c.conkey)
             WHERE c.conrelid = 'public.stock_limits'::regclass
               AND c.contype  = 'f'
               AND a.attname  = 'org_id'
        ) THEN
            ALTER TABLE public.stock_limits
                ADD CONSTRAINT stock_limits_org_id_fkey
                FOREIGN KEY (org_id)
                REFERENCES public.organisations(id)
                ON DELETE CASCADE;
        END IF;
    END $$;

    -- ── 4. Indexes. ──
    -- Primary tenant filter. The endpoint will read by org_id alone.
    CREATE INDEX IF NOT EXISTS idx_stock_limits_org
        ON public.stock_limits(org_id);

    -- Join key used by ensure_stock_limits_backfill to resolve org_id
    -- from inventory on legacy rows.
    CREATE INDEX IF NOT EXISTS idx_stock_limits_inventory
        ON public.stock_limits(inventory_id);

    -- Secondary backfill join key and location-scoped read filter.
    CREATE INDEX IF NOT EXISTS idx_stock_limits_location
        ON public.stock_limits(location_id);
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
        logger.error(f"stock_limits table migration failed: {resp.text}")
        raise RuntimeError(f"stock_limits table migration failed: {resp.text}")
    logger.info("stock_limits table installed (or already present)")

async def ensure_stock_limits_backfill() -> None:
    """
    Backfill stock_limits.org_id for rows written before the column
    existed.

    Live schema has inventory_id (INTEGER) and location_id (UUID). Both
    are valid join keys back to a tenant:
        inventory_id → inventory.id → inventory.org_id
        location_id  → locations.id → locations.org_id

    Any row that resolves to neither goes to PUBLIC_STORE_ORG_ID, because
    once the endpoint filter is applied, a NULL org_id is invisible to
    every org.

    Idempotent. Safe on every boot.
    """
    if not PUBLIC_STORE_ORG_ID:
        logger.warning(
            "ensure_stock_limits_backfill: PUBLIC_STORE_ORG_ID not set — "
            "orphan stock_limits rows will stay NULL and invisible to all orgs"
        )

    sql_parts = [
        # Path 1: via inventory_id → inventory.org_id (INTEGER join)
        """
        UPDATE public.stock_limits sl
           SET org_id = i.org_id
          FROM public.inventory i
         WHERE sl.inventory_id = i.id
           AND sl.org_id IS NULL
           AND i.org_id IS NOT NULL;
        """,
        # Path 2: via location_id → locations.org_id (UUID join)
        """
        UPDATE public.stock_limits sl
           SET org_id = l.org_id
          FROM public.locations l
         WHERE sl.location_id::text = l.id::text
           AND sl.org_id IS NULL
           AND l.org_id IS NOT NULL;
        """,
    ]

    if PUBLIC_STORE_ORG_ID:
        sql_parts.append(f"""
            UPDATE public.stock_limits
               SET org_id = '{PUBLIC_STORE_ORG_ID}'::uuid
             WHERE org_id IS NULL;
        """)

    sql = "\n".join(sql_parts)

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
        logger.error(f"stock_limits backfill failed: {resp.text}")
        raise RuntimeError(f"stock_limits backfill failed: {resp.text}")
    logger.info("stock_limits org_id backfill complete")


async def ensure_product_risk_view():
    """
    ═══════════════════════════════════════════════════════════════════════
    BELT-AND-BRACES MIGRATION — 2026-10-13. DO NOT REVERT.

    Same shape as ensure_branches_table, ensure_alert_log_table,
    ensure_stock_limits_table, ensure_transfer_suggestions_table: full
    SQL on every boot, idempotent, failure raises.

    WRONG IN THE PREVIOUS DEFINITION (verified against the live schemas
    on 2026-10-13 via information_schema):

        inv.product_id  → column does not exist on inventory.
        inv.location_id → column does not exist on inventory.
        inv.batch       → real column is batch_number.
        inv.quantity    → real column is current_qty.
        p.cost          → products.cost exists, but the JOIN to products
                          is on inv.product_id which does not exist, so
                          the join clause itself is invalid.

        A fresh environment would fail this CREATE silently inside the
        old try/except, leaving view_risk_list absent. /risk-scores
        would then 500 into its fallback, which is also broken (it
        selects inventory.product_id, .batch, .quantity, and .cost,
        none of which exist). The endpoint would return an empty list
        with no error surfaced.

    LIVE view_risk_list columns (verified 2026-10-13):
        id, inventory_id, org_id, product_name, sku, batch, quantity,
        financial_value, expiry_date, days_to_expiry, risk_score,
        risk_level

    This rewrite reproduces that exact set from the live inventory
    schema, so CREATE OR REPLACE VIEW produces a byte-identical column
    list and Postgres does not reject the replacement. Because the
    live view's column ORDER is not recorded here, the safer move is
    DROP + CREATE, which sidesteps the "cannot change name of view
    column" constraint that CREATE OR REPLACE imposes when order
    differs. A fresh environment that has no view yet gets the same
    outcome either way.

    DROP is guarded by IF EXISTS. The CASCADE keyword is omitted on
    purpose — if some external object depends on this view, we want
    the DROP to fail loudly, not silently cascade through the
    dependency tree.
    ═══════════════════════════════════════════════════════════════════════
    """
    sql = """
    DROP VIEW IF EXISTS public.view_risk_list;

    CREATE VIEW public.view_risk_list AS
    SELECT
        inv.id                                AS id,
        inv.id                                AS inventory_id,
        inv.org_id                            AS org_id,
        inv.description                       AS product_name,
        inv.item_code                         AS sku,
        inv.batch_number                      AS batch,
        inv.current_qty::integer              AS quantity,
        (inv.current_qty * inv.cost_price_naira) AS financial_value,
        inv.expiry_date                       AS expiry_date,
        (inv.expiry_date - CURRENT_DATE)      AS days_to_expiry,
        CASE
            WHEN (inv.expiry_date - CURRENT_DATE) <= 120 THEN 100
            WHEN (inv.expiry_date - CURRENT_DATE) <= 180 THEN 90
            WHEN (inv.expiry_date - CURRENT_DATE) <= 270 THEN 75
            WHEN (inv.expiry_date - CURRENT_DATE) <= 365 THEN 40
            ELSE 10
        END                                   AS risk_score,
        CASE
            WHEN (inv.expiry_date - CURRENT_DATE) <= 120 THEN 'CRITICAL'
            WHEN (inv.expiry_date - CURRENT_DATE) <= 180 THEN 'HIGH'
            WHEN (inv.expiry_date - CURRENT_DATE) <= 270 THEN 'MODERATE'
            ELSE 'LOW'
        END                                   AS risk_level
      FROM public.inventory inv
     WHERE COALESCE(inv.current_qty, 0) > 0;
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
        logger.error(f"view_risk_list migration failed: {resp.text}")
        raise RuntimeError(f"view_risk_list migration failed: {resp.text}")
    logger.info("view_risk_list view installed (or already present)")


async def ensure_transfer_suggestions_view():
    """
    ═══════════════════════════════════════════════════════════════════════
    BELT-AND-BRACES MIGRATION — 2026-10-13. DO NOT REVERT.

    DROP + CREATE instead of CREATE OR REPLACE.

    WHY:

        The first attempt at this rewrite used CREATE OR REPLACE VIEW.
        Postgres rejected it with SQLSTATE 42P16:

            cannot change name of view column "from_location_id" to "org_id"

        CREATE OR REPLACE VIEW can only add new columns at the END of
        the projection. It cannot rename, retype, or reorder any column
        that already exists in the live view. The old view had
        from_location_id at position 2; the new projection puts org_id
        there. The mismatch aborts the replacement.

        DROP VIEW IF EXISTS + CREATE VIEW has no such restriction. It
        discards whatever shape exists and rebuilds from scratch. That
        is what this rewrite has needed from the start.

    DROP IS GUARDED BUT NOT CASCADED:

        IF EXISTS so a fresh environment with no view does not fail.
        No CASCADE — if some external object depends on this view, the
        DROP should fail loudly rather than silently tear down the
        dependency tree.

    TRANSIENT ABSENCE WINDOW:

        The view is gone between the DROP and the CREATE. In a
        single-process deploy where this runs before the app accepts
        traffic, the window is invisible. If migrations ever move to a
        separate worker, sequence them so the API does not serve
        queries against this view during the swap. Nothing in main.py
        reads it, so today this is a non-issue.

    WRONG IN THE PREVIOUS DEFINITION:

        JOIN products p ON ts.product_id = p.id

        ts.product_id does not exist on transfer_suggestions. Every
        environment that has been running the old function has either
        failed the CREATE silently or is querying a view built from
        some other source. Either way, no caller has been getting
        reliable data from it.

    LIVE transfer_suggestions COLUMNS (verified 2026-10-13):
        id, from_location_id (uuid), to_location_id (uuid),
        inventory_id (integer), batch, quantity, completed_quantity,
        urgency, reason, status, notes, created_at, updated_at,
        last_updated

    This projection reproduces those plus product_name, sku,
    from_location, to_location, and org_id — the tenant key that the
    old view omitted entirely.
    ═══════════════════════════════════════════════════════════════════════
    """
    sql = """
    DROP VIEW IF EXISTS public.view_all_transfer_suggestions;

    CREATE VIEW public.view_all_transfer_suggestions AS
    SELECT
        ts.id,
        ts.org_id,
        ts.from_location_id,
        fl.name           AS from_location,
        ts.to_location_id,
        tl.name           AS to_location,
        ts.inventory_id,
        inv.description   AS product_name,
        inv.item_code     AS sku,
        ts.batch,
        ts.quantity,
        ts.completed_quantity,
        ts.urgency,
        ts.reason,
        ts.status,
        ts.notes,
        ts.created_at,
        ts.updated_at,
        ts.last_updated
      FROM public.transfer_suggestions ts
      LEFT JOIN public.inventory inv ON ts.inventory_id = inv.id
      LEFT JOIN public.locations fl  ON ts.from_location_id = fl.id
      LEFT JOIN public.locations tl  ON ts.to_location_id   = tl.id;
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
        logger.error(f"view_all_transfer_suggestions migration failed: {resp.text}")
        raise RuntimeError(f"view_all_transfer_suggestions migration failed: {resp.text}")
    logger.info("view_all_transfer_suggestions view installed (or already present)")

async def ensure_system_logs_table():
    supabase = get_supabase()
    try:
        test = await run_sync_db_call(supabase.table("system_logs").select("id").limit(1).execute)
        logger.info("system_logs table already exists.")
    except Exception as e:
        if 'relation "system_logs" does not exist' in str(e):
            logger.warning("system_logs table missing. Creating it now...")
            try:
                sql = """
                CREATE TABLE IF NOT EXISTS public.system_logs (
                    id SERIAL PRIMARY KEY,
                    org_id UUID,
                    user_id UUID,
                    level VARCHAR(20) NOT NULL,
                    message TEXT NOT NULL,
                    extra JSONB,
                    security BOOLEAN DEFAULT FALSE,
                    timestamp TIMESTAMPTZ DEFAULT now()
                );
                
                CREATE INDEX IF NOT EXISTS idx_system_logs_org ON public.system_logs(org_id);
                CREATE INDEX IF NOT EXISTS idx_system_logs_level ON public.system_logs(level);
                CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON public.system_logs(timestamp DESC);
                """
                headers = {
                    "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                        json={"query": sql},
                        headers=headers
                    )
                    if resp.status_code not in (200, 204):
                        logger.error(f"Failed to create system_logs table: {resp.text}")
                    else:
                        logger.info("Successfully created system_logs table.")
            except Exception as migration_err:
                logger.error(f"System logs migration error: {migration_err}")
        else:
            logger.error(f"Unexpected error checking system_logs: {e}")

async def ensure_rpc_functions():
    supabase = get_supabase()
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
    }
    sql_total = """
    CREATE OR REPLACE FUNCTION get_total_value(location_id_param INTEGER)
    RETURNS NUMERIC
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RETURN COALESCE(
            (SELECT SUM(quantity * cost) 
             FROM inventory 
             WHERE location_id = location_id_param 
             AND quantity > 0),
            0
        );
    END;
    $$;
    
    CREATE OR REPLACE FUNCTION get_total_value_all()
    RETURNS NUMERIC
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RETURN COALESCE(
            (SELECT SUM(quantity * cost) 
             FROM inventory 
             WHERE quantity > 0),
            0
        );
    END;
    $$;
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{SUPABASE_URL}/rest/v1/rpc/exec_sql", json={"query": sql_total}, headers=headers)
            if resp.status_code not in (200, 204):
                logger.error(f"Failed to create get_total_value RPC: {resp.text}")
            else:
                logger.info("Created get_total_value RPC functions.")
    except Exception as e:
        logger.error(f"Error creating get_total_value RPC: {e}")

    sql_waste = """
    CREATE OR REPLACE FUNCTION get_waste_risk(location_id_param INTEGER)
    RETURNS NUMERIC
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RETURN COALESCE(
            (SELECT SUM(quantity * cost) 
             FROM inventory 
             WHERE location_id = location_id_param 
             AND quantity > 0 
             AND expiry_date <= (CURRENT_DATE + INTERVAL '120 days')),
            0
        );
    END;
    $$;
    
    CREATE OR REPLACE FUNCTION get_waste_risk_all()
    RETURNS NUMERIC
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RETURN COALESCE(
            (SELECT SUM(quantity * cost) 
             FROM inventory 
             WHERE quantity > 0 
             AND expiry_date <= (CURRENT_DATE + INTERVAL '120 days')),
            0
        );
    END;
    $$;
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{SUPABASE_URL}/rest/v1/rpc/exec_sql", json={"query": sql_waste}, headers=headers)
            if resp.status_code not in (200, 204):
                logger.error(f"Failed to create get_waste_risk RPC: {resp.text}")
            else:
                logger.info("Created get_waste_risk RPC functions.")
    except Exception as e:
        logger.error(f"Error creating get_waste_risk RPC: {e}")

    sql_resolve = """
    CREATE OR REPLACE FUNCTION resolve_alert(
        p_alert_id INTEGER,
        p_action_type TEXT,
        p_quantity INTEGER,
        p_notes TEXT,
        p_executed_by UUID,
        p_dest_location_id INTEGER DEFAULT NULL
    )
    RETURNS JSONB
    LANGUAGE plpgsql
    AS $$
    DECLARE
        v_alert_record RECORD;
        v_result JSONB;
    BEGIN
        SELECT * INTO v_alert_record 
        FROM alert_log 
        WHERE id = p_alert_id 
        AND action_taken IS NULL;
        
        IF NOT FOUND THEN
            RETURN jsonb_build_object('success', false, 'error', 'Alert not found or already resolved');
        END IF;
        
        UPDATE alert_log 
        SET 
            action_taken = p_notes,
            action_date = NOW(),
            action_type = p_action_type,
            affected_quantity = p_quantity,
            updated_at = NOW()
        WHERE id = p_alert_id;
        
        IF p_action_type = 'TRANSFER' AND p_dest_location_id IS NOT NULL THEN
            INSERT INTO transfer_suggestions (
                from_location_id,
                to_location_id,
                product_id,
                batch,
                quantity,
                urgency,
                reason,
                status,
                created_at,
                updated_at
            ) VALUES (
                v_alert_record.location_id,
                p_dest_location_id,
                v_alert_record.product_id,
                v_alert_record.batch,
                p_quantity,
                'CRITICAL',
                'Auto-created from alert ' || p_alert_id,
                'Pending',
                NOW(),
                NOW()
            );
        END IF;
        
        IF p_action_type IN ('CONSUME', 'DISPOSE') THEN
            UPDATE inventory 
            SET quantity = quantity - p_quantity,
                updated_at = NOW()
            WHERE product_id = v_alert_record.product_id 
            AND location_id = v_alert_record.location_id
            AND (batch = v_alert_record.batch OR v_alert_record.batch IS NULL);
        END IF;
        
        RETURN jsonb_build_object(
            'success', true,
            'alert_id', p_alert_id,
            'action', p_action_type,
            'quantity', p_quantity,
            'message', 'Alert resolved successfully'
        );
    END;
    $$;
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{SUPABASE_URL}/rest/v1/rpc/exec_sql", json={"query": sql_resolve}, headers=headers)
            if resp.status_code not in (200, 204):
                logger.error(f"Failed to create resolve_alert RPC: {resp.text}")
            else:
                logger.info("Created resolve_alert RPC function.")
    except Exception as e:
        logger.error(f"Error creating resolve_alert RPC: {e}")

    sql_execute = """
    CREATE OR REPLACE FUNCTION execute_transfer_suggestion(
        p_suggestion_id INTEGER,
        p_quantity INTEGER,
        p_notes TEXT,
        p_executed_by UUID
    )
    RETURNS JSONB
    LANGUAGE plpgsql
    AS $$
    DECLARE
        v_suggestion RECORD;
        v_result JSONB;
    BEGIN
        SELECT * INTO v_suggestion 
        FROM transfer_suggestions 
        WHERE id = p_suggestion_id 
        AND status IN ('Pending', 'Partial');
        
        IF NOT FOUND THEN
            RETURN jsonb_build_object('success', false, 'error', 'Suggestion not found or already completed');
        END IF;
        
        IF p_quantity > (v_suggestion.quantity - v_suggestion.completed_quantity) THEN
            RETURN jsonb_build_object(
                'success', false, 
                'error', 'Quantity exceeds remaining amount',
                'remaining', (v_suggestion.quantity - v_suggestion.completed_quantity)
            );
        END IF;
        
        UPDATE inventory 
        SET quantity = quantity - p_quantity,
            updated_at = NOW()
        WHERE product_id = v_suggestion.product_id 
        AND location_id = v_suggestion.from_location_id
        AND (batch = v_suggestion.batch OR v_suggestion.batch IS NULL)
        AND quantity >= p_quantity;
        
        IF NOT FOUND THEN
            RETURN jsonb_build_object('success', false, 'error', 'Insufficient stock at source location');
        END IF;
        
        INSERT INTO inventory (
            location_id,
            product_id,
            batch,
            quantity,
            expiry_date,
            created_at,
            updated_at
        ) VALUES (
            v_suggestion.to_location_id,
            v_suggestion.product_id,
            v_suggestion.batch,
            p_quantity,
            (SELECT expiry_date FROM inventory 
             WHERE product_id = v_suggestion.product_id 
             AND location_id = v_suggestion.from_location_id
             AND (batch = v_suggestion.batch OR v_suggestion.batch IS NULL)
             LIMIT 1),
            NOW(),
            NOW()
        ) ON CONFLICT (location_id, product_id, batch) 
        DO UPDATE SET quantity = inventory.quantity + p_quantity;
        
        UPDATE transfer_suggestions 
        SET 
            completed_quantity = completed_quantity + p_quantity,
            status = CASE 
                WHEN completed_quantity + p_quantity >= quantity THEN 'Complete'
                ELSE 'Partial'
            END,
            notes = COALESCE(notes, '') || ' | Executed: ' || p_notes,
            last_updated = NOW(),
            updated_at = NOW()
        WHERE id = p_suggestion_id;
        
        RETURN jsonb_build_object(
            'success', true,
            'suggestion_id', p_suggestion_id,
            'quantity_executed', p_quantity,
            'new_status', CASE 
                WHEN v_suggestion.completed_quantity + p_quantity >= v_suggestion.quantity 
                THEN 'Complete'
                ELSE 'Partial'
            END,
            'message', 'Transfer executed successfully'
        );
    END;
    $$;
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{SUPABASE_URL}/rest/v1/rpc/exec_sql", json={"query": sql_execute}, headers=headers)
            if resp.status_code not in (200, 204):
                logger.error(f"Failed to create execute_transfer_suggestion RPC: {resp.text}")
            else:
                logger.info("Created execute_transfer_suggestion RPC function.")
    except Exception as e:
        logger.error(f"Error creating execute_transfer_suggestion RPC: {e}")

# ===================== HR TABLES MIGRATION =====================
async def ensure_hr_tables():
    supabase = get_supabase()
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
    }
    sql = """
    CREATE TABLE IF NOT EXISTS public.hr_departments (
        id SERIAL PRIMARY KEY,
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        description TEXT,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_hr_dept_org ON public.hr_departments(org_id);

    CREATE TABLE IF NOT EXISTS public.hr_employees (
        id SERIAL PRIMARY KEY,
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
        first_name VARCHAR(100) NOT NULL,
        last_name VARCHAR(100) NOT NULL,
        email VARCHAR(255) NOT NULL,
        phone VARCHAR(50),
        department_id INTEGER REFERENCES public.hr_departments(id) ON DELETE SET NULL,
        position VARCHAR(100),
        hire_date DATE NOT NULL,
        salary NUMERIC DEFAULT 0,
        status VARCHAR(20) DEFAULT 'active',
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_hr_emp_org ON public.hr_employees(org_id);
    CREATE INDEX IF NOT EXISTS idx_hr_emp_email ON public.hr_employees(email);
    CREATE INDEX IF NOT EXISTS idx_hr_emp_user ON public.hr_employees(user_id);

    CREATE TABLE IF NOT EXISTS public.hr_attendance (
        id SERIAL PRIMARY KEY,
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        employee_id INTEGER NOT NULL REFERENCES public.hr_employees(id) ON DELETE CASCADE,
        date DATE NOT NULL,
        clock_in TIMESTAMPTZ NOT NULL,
        clock_out TIMESTAMPTZ,
        status VARCHAR(20) DEFAULT 'present',
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_hr_att_emp_date ON public.hr_attendance(employee_id, date);

    CREATE TABLE IF NOT EXISTS public.hr_leave_requests (
        id SERIAL PRIMARY KEY,
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        employee_id INTEGER NOT NULL REFERENCES public.hr_employees(id) ON DELETE CASCADE,
        leave_type VARCHAR(20) NOT NULL CHECK (leave_type IN ('annual','sick','personal')),
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        reason TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        approved_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_hr_leave_emp ON public.hr_leave_requests(employee_id);

    CREATE TABLE IF NOT EXISTS public.hr_leave_balances (
        id SERIAL PRIMARY KEY,
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        employee_id INTEGER NOT NULL REFERENCES public.hr_employees(id) ON DELETE CASCADE,
        leave_type VARCHAR(20) NOT NULL,
        balance INTEGER DEFAULT 0,
        year INTEGER NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE(employee_id, leave_type, year)
    );
    CREATE INDEX IF NOT EXISTS idx_hr_balance_emp ON public.hr_leave_balances(employee_id);

    CREATE TABLE IF NOT EXISTS public.hr_payroll (
        id SERIAL PRIMARY KEY,
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        employee_id INTEGER NOT NULL REFERENCES public.hr_employees(id) ON DELETE CASCADE,
        month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
        year INTEGER NOT NULL,
        base_salary NUMERIC DEFAULT 0,
        allowances NUMERIC DEFAULT 0,
        deductions NUMERIC DEFAULT 0,
        net_pay NUMERIC DEFAULT 0,
        status VARCHAR(20) DEFAULT 'draft',
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_hr_payroll_emp ON public.hr_payroll(employee_id);
    CREATE INDEX IF NOT EXISTS idx_hr_payroll_month_year ON public.hr_payroll(month, year);
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
            json={"query": sql},
            headers=headers
        )
        if resp.status_code not in (200, 204):
            logger.error(f"Failed to create HR tables: {resp.text}")
        else:
            logger.info("HR tables created/verified.")


async def ensure_is_cogs_column():
    """
    ═══════════════════════════════════════════════════════════════════════
    BELT-AND-BRACES MIGRATION — 2026-10-13. DO NOT REVERT.

    WHY THE PREVIOUS SHAPE FAILED:

        The old version probed with .select("is_cogs") and matched the
        exception against the literal string
        'column "is_cogs" does not exist'. PostgREST does not return
        that string. A missing column surfaces as a 400 with a JSON
        body whose message format differs. Neither the if branch nor
        the else branch matched, so:

          - the column was never added
          - nothing was logged
          - startup continued as if the migration had succeeded

        The 2026-10-13 10:13 boot log shows the exact failure mode:
        a bare GET ...?select=is_cogs returning 400, then
        "Startup complete" with no follow-up line. Silent miss.

    THE FIX:

        No probe. Run the ALTER directly. It is idempotent, so it is
        safe on every boot whether the column exists or not. Raise on
        failure. There is no string to match, so there is no way for
        the code to get the match wrong.
    ═══════════════════════════════════════════════════════════════════════
    """
    sql = """
    ALTER TABLE public.chart_of_accounts
        ADD COLUMN IF NOT EXISTS is_cogs BOOLEAN DEFAULT FALSE;
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
        logger.error(f"is_cogs column migration failed: {resp.text}")
        raise RuntimeError(f"is_cogs column migration failed: {resp.text}")
    logger.info("is_cogs column installed (or already present)")


async def ensure_accounting_tables():
    supabase = get_supabase()
    sql = """
    CREATE TABLE IF NOT EXISTS public.chart_of_accounts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        code VARCHAR(20) NOT NULL,
        name VARCHAR(100) NOT NULL,
        type VARCHAR(20) NOT NULL CHECK (type IN ('asset','liability','equity','revenue','expense')),
        parent_id UUID REFERENCES public.chart_of_accounts(id),
        description TEXT,
        is_cogs BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE(org_id, code)
    );
    CREATE TABLE IF NOT EXISTS public.journal_entries (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        entry_date DATE NOT NULL,
        description TEXT,
        reference VARCHAR(50),
        status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft','posted','cancelled')),
        created_by UUID REFERENCES public.profiles(id),
        posted_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS public.journal_lines (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        journal_entry_id UUID NOT NULL REFERENCES public.journal_entries(id) ON DELETE CASCADE,
        account_id UUID NOT NULL REFERENCES public.chart_of_accounts(id),
        debit NUMERIC(15,2) DEFAULT 0,
        credit NUMERIC(15,2) DEFAULT 0,
        description TEXT,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS public.accounts_receivable (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        sale_id UUID NOT NULL REFERENCES public.sales(id) ON DELETE CASCADE,
        customer_id UUID REFERENCES public.profiles(id),
        amount NUMERIC(15,2) NOT NULL,
        paid_amount NUMERIC(15,2) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending','partial','paid','overdue','written_off')),
        due_date DATE NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS public.accounts_payable (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        purchase_order_id UUID REFERENCES public.purchase_orders(id) ON DELETE SET NULL,
        grn_id UUID REFERENCES public.grn(id) ON DELETE SET NULL,
        supplier_id UUID NOT NULL REFERENCES public.suppliers(id),
        amount NUMERIC(15,2) NOT NULL,
        paid_amount NUMERIC(15,2) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending','partial','paid','overdue','written_off')),
        due_date DATE NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS public.profit_loss_summary (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        period_start DATE NOT NULL,
        period_end DATE NOT NULL,
        revenue NUMERIC(15,2) DEFAULT 0,
        cogs NUMERIC(15,2) DEFAULT 0,
        gross_profit NUMERIC(15,2) DEFAULT 0,
        operating_expenses NUMERIC(15,2) DEFAULT 0,
        net_income NUMERIC(15,2) DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    """
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
            json={"query": sql},
            headers=headers
        )
        if resp.status_code not in (200, 204):
            logger.error(f"Failed to create accounting tables: {resp.text}")
        else:
            logger.info("Accounting tables created/verified.")

async def _read_stored_migration_hash() -> Optional[str]:
    """
    Return the hash of the last successful migration suite run, or
    None if the schema_migrations table does not yet exist (first ever
    boot on this database) or has no row.
    """
    sql = """
    CREATE TABLE IF NOT EXISTS public.schema_migrations (
        id              SERIAL PRIMARY KEY,
        suite_hash      TEXT NOT NULL,
        applied_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        applied_by      TEXT
    );
    """
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Ensure the table exists — this is the one statement that must
        # run on every boot, because it's how we bootstrap the gate.
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
            json={"query": sql},
            headers=headers,
        )
        if resp.status_code not in (200, 204):
            logger.error(f"schema_migrations bootstrap failed: {resp.text}")
            return None

        # Read the most recent row.
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
            json={"query": "SELECT suite_hash FROM public.schema_migrations ORDER BY applied_at DESC LIMIT 1;"},
            headers=headers,
        )
    if resp.status_code not in (200, 204):
        return None
    try:
        rows = resp.json()
    except Exception:
        return None
    if not rows:
        return None
    return rows[0].get("suite_hash")


async def _record_migration_hash(suite_hash: str, applied_by: str) -> None:
    sql = f"""
    INSERT INTO public.schema_migrations (suite_hash, applied_at, applied_by)
    VALUES ('{suite_hash}', NOW(), '{applied_by}');
    """
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
            json={"query": sql},
            headers=headers,
        )
    if resp.status_code not in (200, 204):
        logger.error(f"failed to record migration hash: {resp.text}")

# ─────────────────────────────────────────────────────────────────────
# Migration gate — multi-instance safe
#
# advisory lock key. Any integer. Same across all instances. Chosen
# arbitrarily and noted here so no other code accidentally claims it.
# ─────────────────────────────────────────────────────────────────────
_MIGRATION_ADVISORY_LOCK_KEY = 8127346521


async def _try_acquire_migration_lock() -> bool:
    """Try to acquire the migration advisory lock. Non-blocking."""
    sql = f"SELECT pg_try_advisory_lock({_MIGRATION_ADVISORY_LOCK_KEY}) AS acquired;"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
            json={"query": sql},
            headers=headers,
        )
    if resp.status_code not in (200, 204):
        return False
    try:
        rows = resp.json()
        return bool(rows and rows[0].get("acquired"))
    except Exception:
        return False


async def _release_migration_lock() -> None:
    sql = f"SELECT pg_advisory_unlock({_MIGRATION_ADVISORY_LOCK_KEY});"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                json={"query": sql},
                headers=headers,
            )
    except Exception:
        # The connection drop releases the lock anyway.
        pass


async def _wait_for_hash(stored_hash_wanted: str, timeout_s: float = 60.0) -> bool:
    """
    Poll the schema_migrations table until its latest row matches
    stored_hash_wanted, or the timeout elapses.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        h = await _read_stored_migration_hash()
        if h == stored_hash_wanted:
            return True
    return False




# ------------------------------------------------------------------
# SINGLE STARTUP EVENT - ALL MIGRATIONS CONSOLIDATED
# ------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    if os.environ.get("SKIP_MIGRATIONS", "false").lower() == "true":
        logger.info("⏩ Skipping migrations (SKIP_MIGRATIONS=true)")
        await _verify_plan_catalog()
        return

    force = os.environ.get("FORCE_MIGRATIONS", "false").lower() == "true"
    current_hash = _compute_migration_suite_hash()
    instance_id = os.environ.get("RENDER_INSTANCE_ID") or os.environ.get("SPACE_ID") or "unknown"

    # ── Single-instance fast path ──
    #
    # HF Spaces runs exactly one instance. There is no second instance
    # to race against, so the lock is pure overhead — and worse, a
    # session-scoped pg_advisory_lock acquired through Supabase's
    # Supavisor pooler can leak: the acquire lands on one backend, the
    # release lands on another, and the original backend returns to
    # the pool holding the lock forever. Every subsequent boot then
    # waits 90s for a lock that will never be released.
    #
    # Set MULTI_INSTANCE_MIGRATIONS=true only when running N>1 replicas
    # (Render with scale > 1). The current multi-instance path still
    # uses pg_advisory_lock and has the same leak risk; do not enable
    # it without first migrating to a table-based lock.
    multi_instance = os.environ.get("MULTI_INSTANCE_MIGRATIONS", "false").lower() == "true"

    if not multi_instance:
        if not force:
            stored_hash = await _read_stored_migration_hash()
            if stored_hash == current_hash:
                logger.info(
                    "migration suite up to date — skipping",
                    suite_hash=current_hash[:12],
                    instance=instance_id,
                )
                await _verify_plan_catalog()
                return
            logger.info(
                "migration suite hash changed — running full suite (single-instance)",
                stored=stored_hash[:12] if stored_hash else "none",
                current=current_hash[:12],
                instance=instance_id,
            )

        await ensure_branches_table()
        await ensure_location_stocks_constraints()
        await ensure_cost_price_column()
        await ensure_delivery_fee_columns()
        await ensure_org_delivery_columns()
        await ensure_role_column()
        await ensure_org_registry_schema()
        await ensure_health_check_schema()
        await ensure_knowledge_audit_table()
        await ensure_vector_support()
        await ensure_loyalty_tables()
        await ensure_stock_transfers_table()
        await ensure_stock_transfer_rpcs()
        await ensure_transfer_suggestions_last_updated_column()
        await ensure_decrement_stock_fefo()
        await ensure_finalize_online_order()
        await ensure_webhook_events()
        await ensure_stock_reconciliation()
        await ensure_sales_fulfillment_columns()
        await ensure_alert_log_table()
        await ensure_alert_log_backfill()
        await ensure_transfer_suggestions_table()
        await ensure_transfer_suggestions_backfill()
        await ensure_stock_limits_table()
        await ensure_stock_limits_backfill()
        await ensure_product_risk_view()
        await ensure_transfer_suggestions_view()
        await ensure_system_logs_table()
        await ensure_rpc_functions()

        await ensure_hr_tables()

        await ensure_accounting_tables()
        await ensure_is_cogs_column()

        await _record_migration_hash(
            suite_hash=current_hash,
            applied_by=instance_id,
        )

        logger.info(
            "Startup complete — all tables and functions ready",
            suite_hash=current_hash[:12],
            instance=instance_id,
        )
        await _verify_plan_catalog()
        return

    # ── Multi-instance path (only when MULTI_INSTANCE_MIGRATIONS=true) ──
    if not force:
        stored_hash = await _read_stored_migration_hash()
        if stored_hash == current_hash:
            logger.info(
                "migration suite up to date — skipping",
                suite_hash=current_hash[:12],
                instance=instance_id,
            )
            await _verify_plan_catalog()
            return

    acquired = await _try_acquire_migration_lock()

    if not acquired:
        logger.info(
            "another instance holds the migration lock — waiting",
            instance=instance_id,
            suite_hash=current_hash[:12],
        )
        if await _wait_for_hash(current_hash, timeout_s=90.0):
            logger.info(
                "migration lock released — suite is up to date",
                instance=instance_id,
            )
            await _verify_plan_catalog()
            return
        else:
            logger.warning(
                "timed out waiting for migration lock — booting anyway",
                instance=instance_id,
            )
            await _verify_plan_catalog()
            return

    try:
        if not force:
            stored_hash = await _read_stored_migration_hash()
            if stored_hash == current_hash:
                logger.info(
                    "migration suite already applied by another instance — skipping",
                    suite_hash=current_hash[:12],
                    instance=instance_id,
                )
                await _verify_plan_catalog()
                return

        logger.info(
            "migration suite running under advisory lock",
            instance=instance_id,
            suite_hash=current_hash[:12],
        )

        await ensure_branches_table()
        await ensure_location_stocks_constraints()
        await ensure_cost_price_column()
        await ensure_delivery_fee_columns()
        await ensure_org_delivery_columns()
        await ensure_role_column()
        await ensure_org_registry_schema()
        await ensure_health_check_schema()
        await ensure_knowledge_audit_table()
        await ensure_vector_support()
        await ensure_loyalty_tables()
        await ensure_stock_transfers_table()
        await ensure_stock_transfer_rpcs()
        await ensure_transfer_suggestions_last_updated_column()
        await ensure_decrement_stock_fefo()
        await ensure_finalize_online_order()
        await ensure_webhook_events()
        await ensure_stock_reconciliation()
        await ensure_sales_fulfillment_columns()
        await ensure_alert_log_table()
        await ensure_alert_log_backfill()
        await ensure_transfer_suggestions_table()
        await ensure_transfer_suggestions_backfill()
        await ensure_stock_limits_table()
        await ensure_stock_limits_backfill()
        await ensure_product_risk_view()
        await ensure_transfer_suggestions_view()
        await ensure_system_logs_table()
        await ensure_rpc_functions()

        await ensure_hr_tables()

        await ensure_accounting_tables()
        await ensure_is_cogs_column()

        await _record_migration_hash(
            suite_hash=current_hash,
            applied_by=instance_id,
        )

        logger.info(
            "Startup complete — all tables and functions ready",
            suite_hash=current_hash[:12],
            instance=instance_id,
        )
    finally:
        await _release_migration_lock()

    await _verify_plan_catalog()

async def _verify_plan_catalog():
    for key, tier in PLAN_TIERS.items():
        unknown = set(tier["features"]) - set(FEATURE_CATALOG)
        if unknown:
            logger.error(f"plan {key}: unknown feature keys {unknown}")
    logger.info(
        "plan catalog loaded",
        tiers=len(PLAN_TIERS),
        features=len(FEATURE_CATALOG),
        metrics=len(METRIC_CATALOG),
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_detail = traceback.format_exc()
    logger.error(f"Unhandled exception: {error_detail}")
    return JSONResponse(status_code=500, content={"detail": str(exc), "traceback": error_detail})

@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    start_time = time.time()

    with bound_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        client_ip=get_client_ip(request)
    ):
        logger.info("request_started")
        try:
            response = await call_next(request)
            process_time = (time.time() - start_time) * 1000
            logger.info(
                "request_completed",
                status_code=response.status_code,
                duration_ms=round(process_time, 2)
            )
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as e:
            process_time = (time.time() - start_time) * 1000
            logger.error(
                "request_failed",
                error_type=type(e).__name__,
                error=str(e),
                duration_ms=round(process_time, 2),
                exc_info=True
            )
            raise


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)

    # HSTS only over HTTPS (HF Spaces terminates TLS in front of you)
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "geolocation=(self), camera=(), microphone=(), payment=(self)"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

    # Content Security Policy — scoped to exactly what the storefront and admin app need.
    csp_directives = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.tailwindcss.com "
            "https://cdnjs.cloudflare.com "
            "https://cdn.jsdelivr.net "
            "https://js.paystack.co "
            "https://checkout.flutterwave.com "
            "https://checkout.paystack.com "
            "https://crxykdfgexuysngzwulk.supabase.co",
        "style-src 'self' 'unsafe-inline' "
            "https://cdnjs.cloudflare.com "
            "https://fonts.googleapis.com",
        "font-src 'self' data: "
            "https://cdnjs.cloudflare.com "
            "https://fonts.gstatic.com",
        "img-src 'self' data: blob: https:",
        "connect-src 'self' "
            "https://crxykdfgexuysngzwulk.supabase.co "
            "https://api.paystack.co "
            "https://api.flutterwave.com "
            "https://checkout.paystack.com "
            "https://checkout.flutterwave.com "
            "https://nominatim.openstreetmap.org "
            "https://kevsono-kevs-digital-bos.hf.space",
        "frame-src 'self' "
            "https://checkout.paystack.com "
            "https://checkout.flutterwave.com",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self' "
            "https://checkout.paystack.com "
            "https://checkout.flutterwave.com",
        "frame-ancestors 'self'",
        "manifest-src 'self'",
        "worker-src 'self' blob:",
        "upgrade-insecure-requests",
    ]
    response.headers["Content-Security-Policy"] = "; ".join(csp_directives) + ";"

    return response






# ------------------------------------------------------------------
# Embedder & semantic firewall
# ------------------------------------------------------------------
_guardrail_embedder = _GLOBAL_EMBEDDER
_approved_topics = [
    "greetings and pleasantries",
    "product availability and inventory",
    "order status and tracking",
    "return and refund policy",
    "store location and business hours",
    "loyalty points and membership",
    "create a support ticket",
    "warranty and guarantees",
    "product waranty information",
    "talk to a human agent"
]
_approved_embeddings = None

try:
    _approved_embeddings = _GLOBAL_EMBEDDER.encode(_approved_topics, convert_to_tensor=True)
    logger.info("Approved topics embeddings preloaded")
except Exception as e:
    logger.error(f"Failed to preload approved embeddings: {e}")

def get_embedder():
    return _GLOBAL_EMBEDDER

def get_embedding(text: str) -> Optional[List[float]]:
    embedder = get_embedder()
    if embedder:
        return embedder.encode(text).tolist()
    return None

def semantic_firewall(user_message: str, threshold: float = 0.65) -> bool:
    if _guardrail_embedder is None or _approved_embeddings is None:
        logger.warning("Guardrail embedder not available – allowing all messages")
        return True
    msg_emb = _guardrail_embedder.encode(user_message, convert_to_tensor=True)
    cos_scores = util.cos_sim(msg_emb, _approved_embeddings)[0]
    max_score = float(cos_scores.max())
    logger.info(f"Semantic firewall: max similarity = {max_score:.3f}")
    return max_score >= threshold

# ------------------------------------------------------------------
# Pydantic guardrail for LLM output
# ------------------------------------------------------------------
class SafeReply(BaseModel):
    message: str = Field(..., max_length=800)
    confidence: float = Field(..., ge=0.0, le=1.0)
    action: Literal["reply", "create_ticket", "escalate"] = "reply"
    metadata: Optional[dict] = None

    @validator('message')
    def no_hallucinated_numbers(cls, v):
        if re.search(r'\bORD-\d{6}\b', v) and "your order" not in v.lower():
            raise ValueError('Suspicious order number pattern')
        return v

    @validator('message')
    def no_unsafe_links(cls, v):
        urls = re.findall(r'https?://[^\s<>"\'()]+', v)
        allowed_domains = [
            r'^https?://(?:www\.)?paystack\.com',
            r'^https?://(?:www\.)?checkout\.paystack\.com',
            r'^https?://kevsono-kevs-digital-bos\.hf\.space',
            r'^https?://kevsono-penafort-concierge\.hf\.space'
        ]
        for url in urls:
            if not any(re.match(domain_pattern, url) for domain_pattern in allowed_domains):
                logger.warning(f"🚨 Guardrail blocked malicious/unverified URL generation: {url}")
                raise ValueError('External unverified links are not allowed in automated customer interactions.')
        return v

def fallback_response() -> str:
    return "I'm sorry, I can only help with questions about our products, orders, store hours, and loyalty program. Please rephrase or contact support."

def escalation_response() -> str:
    return "I've escalated this to our human support team. They will contact you shortly."

# ------------------------------------------------------------------
# Knowledge content validation
# ------------------------------------------------------------------
def validate_knowledge_content(content: str, title: str) -> None:
    urls = re.findall(r'https?://[^\s<>"\'()]+', content)
    allowed_domains = [
        r'^https?://(?:www\.)?paystack\.com',
        r'^https?://(?:www\.)?checkout\.paystack\.com',
        r'^https?://kevsono-kevs-digital-bos\.hf\.space',
        r'^https?://kevsono-penafort-concierge\.hf\.space'
    ]
    for url in urls:
        if not any(re.match(domain_pattern, url) for domain_pattern in allowed_domains):
            raise HTTPException(status_code=400, detail=f"Knowledge contains unverified URL: {url}")
    if re.search(r'\bORD-\d{6}\b', content) and "your order" not in content.lower():
        raise HTTPException(status_code=400, detail="Knowledge cannot contain fake order numbers")
    if re.search(r'\b(\+?234|0)[7-9][01]\d{8}\b', content):
        raise HTTPException(status_code=400, detail="Knowledge cannot contain real phone numbers. Use placeholders like '123-456-7890'")
    injection_patterns = [
        r"(?i)ignore (all|previous) (instructions|rules)",
        r"(?i)you are now (a different|not )",
        r"(?i)system prompt override",
        r"(?i)forget (your|the) (previous|above)",
        r"(?i)new instruction:",
    ]
    for pattern in injection_patterns:
        if re.search(pattern, content):
            raise HTTPException(status_code=400, detail=f"Knowledge contains potential prompt injection: {pattern}")
    offensive_words = ['fuck', 'shit', 'damn', 'stupid', 'idiot', 'asshole', 'bastard']
    lower_content = content.lower()
    for word in offensive_words:
        if word in lower_content:
            raise HTTPException(status_code=400, detail=f"Knowledge contains offensive word: {word}")
    if len(content) > 5000:
        raise HTTPException(status_code=400, detail="Knowledge content exceeds 5000 characters")
    if len(title) < 3 or len(title) > 200:
        raise HTTPException(status_code=400, detail="Title must be 3-200 characters")

# ------------------------------------------------------------------
# LLM caller
# ------------------------------------------------------------------
async def call_llm(prompt: str) -> str:
    if GROQ_API_KEY:
        try:
            groq = Groq(api_key=GROQ_API_KEY)
            resp = groq.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="openai/gpt-oss-120b",
                temperature=AI_TEMPERATURE,
                max_tokens=800
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.warning(f"Groq error: {e}, falling back to Gemini")
    if GEMINI_API_KEY:
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel('gemini-2.0-flash', generation_config={"temperature": AI_TEMPERATURE})
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            raise
    raise RuntimeError("No LLM API key configured")

# ------------------------------------------------------------------
# Rate limiter
# ------------------------------------------------------------------
async def rate_limit(client_id: str, org_id: Optional[str] = None, request: Optional[Request] = None):
    if not RATE_LIMIT_ENABLED:
        return

    if request:
        logger.info(f"Header X-Load-Test: {request.headers.get('X-Load-Test')}")

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
            insert_data = {
                "client_id": client_id,
                "window_start": window_start.isoformat(),
                "request_count": 1
            }
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

# ─── Brevo email sender ──────────────────────────
async def send_sendgrid_email(to_email: str, subject: str, html_content: str):
    if not BREVO_API_KEY or not BREVO_FROM_EMAIL:
        logger.warning(f"Brevo not configured. Would send email to {to_email}: {subject}")
        return

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "sender": {"email": BREVO_FROM_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=data, headers=headers)
            if resp.status_code >= 400:
                logger.error(f"Brevo error {resp.status_code}: {resp.text}")
            else:
                logger.info(f"Brevo email sent to {to_email}: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email via Brevo: {e}")

# ─── Order confirmation email ──────────────────────────────────
async def send_order_confirmation_email(sale_data: dict, items: list = None):
    customer_email = sale_data.get("customer_email")
    if not customer_email:
        logger.warning("No customer email, skipping confirmation")
        return

    receipt = sale_data.get("receipt_number", "N/A")
    total = float(sale_data.get("total_amount", 0))
    subtotal = float(sale_data.get("subtotal", total))
    delivery_fee = float(sale_data.get("delivery_fee", 0))
    handling_fee = float(sale_data.get("handling_fee", 0))

    customer_phone = sale_data.get("customer_phone")
    if not customer_phone and sale_data.get("user_id"):
        client = get_supabase()
        try:
            profile = await run_sync_db_call(
                client.table("profiles")
                .select("phone")
                .eq("id", sale_data["user_id"])
                .maybe_single()
                .execute
            )
            if profile and profile.data:
                customer_phone = profile.data.get("phone")
        except Exception as e:
            logger.warning(f"Could not fetch profile phone: {e}")
    if not customer_phone:
        customer_phone = "Not provided"

    if items is None:
        client = get_supabase()
        try:
            result = await run_sync_db_call(
                client.table("sale_items")
                .select("product_name, quantity, unit_price, subtotal")
                .eq("sale_id", sale_data.get("id"))
                .execute
            )
            items = result.data or []
        except Exception as e:
            logger.error(f"Failed to fetch sale items for confirmation: {e}")
            items = []

    if not subtotal and items:
        subtotal = sum(float(i.get("subtotal", 0)) for i in items)

    items_html = ""
    if items:
        rows = []
        for i in items:
            rows.append(f"""
                <tr>
                    <td>{i.get('product_name', '')}</td>
                    <td>{i.get('quantity', 0)}</td>
                    <td>₦{float(i.get('unit_price', 0)):,.2f}</td>
                    <td>₦{float(i.get('subtotal', 0)):,.2f}</td>
                </tr>
            """)
        items_html = f"""
        <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%;">
            <tr><th>Product</th><th>Qty</th><th>Unit Price</th><th>Subtotal</th></tr>
            {''.join(rows)}
        </table>
        """

    tracking_link = f"{PRODUCTION_HOST}/kdstore?receipt_number={receipt}&email={customer_email}"

    summary_rows = []
    summary_rows.append(f"<tr><td><strong>Subtotal</strong></td><td style='text-align:right;'>₦{subtotal:,.2f}</td></tr>")
    if delivery_fee > 0:
        summary_rows.append(f"<tr><td><strong>Delivery Fee</strong></td><td style='text-align:right;'>₦{delivery_fee:,.2f}</td></tr>")
    if handling_fee > 0:
        summary_rows.append(f"<tr><td><strong>Handling Fee</strong></td><td style='text-align:right;'>₦{handling_fee:,.2f}</td></tr>")
    summary_rows.append(f"<tr><td><strong>Total</strong></td><td style='text-align:right;font-weight:bold;'>₦{total:,.2f}</td></tr>")
    summary_html = f"""
    <table style="width: 100%; max-width: 300px; margin-top: 10px;">
        {''.join(summary_rows)}
    </table>
    """

    subject = f"Order Confirmation – {receipt}"
    html_content = f"""
    <h2>Thank you for your order!</h2>
    <p>Your order <strong>{receipt}</strong> has been confirmed.</p>
    {items_html}
    <hr>
    <h3>Order Summary</h3>
    {summary_html}
    <hr>
    <p><strong>Customer Phone:</strong> {customer_phone}</p>
    <p>You can track your order anytime using this link:<br>
    <a href="{tracking_link}">{tracking_link}</a></p>
    <p>We'll notify you when it's shipped.</p>
    <p>If you have any questions, reply to this email.</p>
    """
    await send_sendgrid_email(customer_email, subject, html_content)

async def send_status_update_email(sale_id: str, old_status: str, new_status: str, tracking_info: dict = None):
    client = get_supabase()
    sale = await run_sync_db_call(client.table("sales").select("*, sale_items(*)").eq("id", sale_id).maybe_single().execute)
    if not sale.data:
        logger.error(f"Sale {sale_id} not found for status email")
        return
    sale_data = sale.data
    org = await run_sync_db_call(client.table("organisations").select("org_name, logistics_email").eq("id", sale_data["org_id"]).maybe_single().execute)
    org_name = org.data["org_name"] if org.data else "Our Store"
    logistics_email = org.data.get("logistics_email") if org.data else LOGISTICS_EMAIL

    customer_email = sale_data.get("customer_email")
    if not customer_email:
        logger.warning(f"No customer email for order {sale_id}")
        return

    customer_phone = sale_data.get("customer_phone", "Not provided")

    tracking_link = f"{PRODUCTION_HOST}/kdstore?receipt_number={sale_data['receipt_number']}&email={customer_email}"

    if new_status == "shipped":
        subject = f"Your order #{sale_data['receipt_number']} is on the way!"
        customer_html = f"""
        <h2>Order Dispatched</h2>
        <p>Good news! Your order <strong>{sale_data['receipt_number']}</strong> has been shipped.</p>
        <p><strong>Carrier:</strong> {tracking_info.get('carrier', sale_data.get('shipping_carrier', 'Not specified')) if tracking_info else sale_data.get('shipping_carrier', 'Not specified')}</p>
        <p><strong>Tracking number:</strong> {tracking_info.get('tracking_number', sale_data.get('tracking_number', 'N/A')) if tracking_info else sale_data.get('tracking_number', 'N/A')}</p>
        <p><strong>Estimated delivery:</strong> {tracking_info.get('estimated_delivery', sale_data.get('estimated_delivery', '2-5 business days')) if tracking_info else sale_data.get('estimated_delivery', '2-5 business days')}</p>
        <p><strong>Customer phone:</strong> {customer_phone}</p>
        <p>Track your order: <a href="{tracking_link}">Click here</a></p>
        """
        internal_html = f"""
        <h2>Order Dispatched – Action Required</h2>
        <p>Order <strong>{sale_data['receipt_number']}</strong> has been marked as shipped.</p>
        <p>Carrier: {tracking_info.get('carrier', sale_data.get('shipping_carrier', 'N/A')) if tracking_info else sale_data.get('shipping_carrier', 'N/A')}</p>
        <p>Tracking: {tracking_info.get('tracking_number', sale_data.get('tracking_number', 'N/A')) if tracking_info else sale_data.get('tracking_number', 'N/A')}</p>
        <p><strong>Customer phone:</strong> {customer_phone}</p>
        <p>Ensure delivery confirmation is received.</p>
        """
    elif new_status == "delivered":
        subject = f"Your order #{sale_data['receipt_number']} has been delivered"
        customer_html = f"""
        <h2>Order Delivered</h2>
        <p>Your order <strong>{sale_data['receipt_number']}</strong> has been delivered.</p>
        <p>Thank you for shopping with {org_name}!</p>
        <p><strong>Customer phone:</strong> {customer_phone}</p>
        <p>If you have any issues, please contact support.</p>
        """
        internal_html = f"""
        <h2>Order Delivered – Complete</h2>
        <p>Order <strong>{sale_data['receipt_number']}</strong> has been marked as delivered.</p>
        <p><strong>Customer phone:</strong> {customer_phone}</p>
        <p>Fulfillment cycle closed.</p>
        """
    else:
        return

    await send_sendgrid_email(customer_email, subject, customer_html)
    if logistics_email:
        await send_sendgrid_email(logistics_email, f"Order Update: {sale_data['receipt_number']} - {new_status}", internal_html)
    else:
        logger.warning(f"No logistics email configured for org {sale_data['org_id']}")

# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------
async def generate_invite_code() -> str:
    # Reads every row of organisations.invite_code to compute the next
    # KD### code. Must use the admin client so RLS can't hide rows from
    # us — otherwise a polluted cached client (carrying some user's JWT)
    # would only see that user's orgs and hand out an invite code that
    # collides with an existing one.
    client = get_admin_supabase()
    result = await run_sync_db_call(client.table("organisations").select("invite_code").execute)
    codes = [row["invite_code"] for row in result.data if row.get("invite_code")]
    max_num = 0
    for code in codes:
        if code.startswith("KD"):
            try:
                num = int(code[2:])
                if num > max_num:
                    max_num = num
            except:
                pass
    next_num = max_num + 1
    return f"KD{next_num:03d}"
    
def slugify(text: str) -> str:
    """URL-safe slug: 'Acme Pharmacy Ltd.' → 'acme-pharmacy-ltd'"""
    if not text:
        return ""
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s[:60]

def escape_html(s: str) -> str:
    if not s:
        return ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))
             

RESERVED_SLUGS = {
    "admin", "api", "app", "store", "login", "signup", "register",
    "kdadmin", "kdstore", "kdsiginin", "kdpos", "kdteam", "kdorgs",
    "support", "help", "docs", "www", "mail", "static", "assets",
}


async def generate_unique_slug(org_name: str, exclude_org_id: Optional[str] = None) -> str:
    """
    Turn a name into a slug that isn't already taken.
    Appends -2, -3, ... on collision. Reserves system slugs.

    Uses the admin client so the collision check sees every org row,
    even if the cached client ever carries a user session.
    """
    base = slugify(org_name) or "org"
    if base in RESERVED_SLUGS:
        base = f"{base}-org"

    client = get_admin_supabase()
    for attempt in range(50):
        candidate = base if attempt == 0 else f"{base}-{attempt + 1}"
        if candidate in RESERVED_SLUGS:
            continue
        q = client.table("organisations").select("id").eq("slug", candidate)
        if exclude_org_id:
            q = q.neq("id", exclude_org_id)
        res = await run_sync_db_call(q.limit(1).execute)
        if not res.data:
            return candidate

    return f"{base}-{uuid.uuid4().hex[:6]}"
async def get_next_auto_batch_number() -> str:
    client = get_supabase()
    try:
        result = await run_sync_db_call(client.rpc('get_next_auto_batch_number', {}).execute)
        next_num = result.data
        return f"autogen{next_num:03d}"
    except Exception as e:
        logger.error(f"Failed to get next auto batch number: {e}")
        return f"autogen{int(datetime.now(timezone.utc).timestamp()) % 10000:03d}"

async def get_current_user(authorization: str = Header(None)) -> Optional[Tuple[str, str]]:
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("get_current_user: No Bearer token")
        return None
    token = authorization.split(" ")[1]
    try:
        # Auth operations use a throwaway anon client so the cached
        # service-role client never has a user session attached to it.
        auth_client = get_user_supabase()
        user = await run_sync_db_call(auth_client.auth.get_user, token)
        if user and user.user:
            email = getattr(user.user, 'email', None)
            logger.info(f"get_current_user: user_id={user.user.id}, email={email}")
            return user.user.id, email
        else:
            logger.warning("get_current_user: No user from token")
            return None
    except Exception as e:
        logger.warning(f"get_current_user: Invalid token - {e}")
        return None
        
async def get_current_org(authorization: str = Header(None), x_selected_org_id: Optional[str] = None) -> Tuple[str, str]:
    """FIXED: Enforces role validation per tenant instance - prevents cross-tenant privilege escalation."""
    user_info = await get_current_user(authorization)
    if not user_info:
        logger.error("get_current_org: No user info")
        raise HTTPException(status_code=401, detail="Not authenticated")
    token_user_id, email = user_info

    client = get_supabase()
    resolved_user_id = token_user_id
    org_id = None
    org_rows = []

    try:
        logger.info(f"🔍 Query org_members with user_id={token_user_id}")
        res = await run_sync_db_call(client.table("org_members").select("org_id, role").eq("user_id", token_user_id).order("org_id", desc=False).execute)
        logger.info(f"🔍 org_members response (direct): {res.data}")
        logger.info(f"✅ Using org_id = {org_id} for user {token_user_id}")
        org_rows = getattr(res, "data", []) or []

        if x_selected_org_id:
            user_role_in_tenant = next(
                (org.get("role") for org in org_rows if str(org.get("org_id")) == str(x_selected_org_id)),
                None
            )
            if not user_role_in_tenant:
                logger.warning(f"User {token_user_id} attempted to access org {x_selected_org_id} without membership")
                raise HTTPException(
                    status_code=403,
                    detail="You are not a member of the requested organisation"
                )

            logger.info(f"User {token_user_id} has role '{user_role_in_tenant}' in org {x_selected_org_id}")
            return token_user_id, x_selected_org_id
        else:
            if org_rows:
                org_id = org_rows[0]["org_id"]
                logger.info(f"✅ Org found via token user_id: {token_user_id}, org_id={org_id}")
                return token_user_id, org_id
            else:
                logger.warning(f"Direct lookup returned no rows for user_id={token_user_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Direct lookup failed: {e}", exc_info=True)

    if email:
        try:
            logger.info(f"🔍 Looking up profile by email={email}")
            profile_res = await run_sync_db_call(client.table("profiles").select("id").eq("email", email).maybe_single().execute)
            logger.info(f"Profile lookup response: {profile_res.data}")
            if profile_res and profile_res.data:
                resolved_user_id = profile_res.data["id"]
                logger.info(f"📧 Resolved user_id {resolved_user_id} from email {email}")
                res2 = await run_sync_db_call(client.table("org_members").select("org_id, role").eq("user_id", resolved_user_id).execute)
                logger.info(f"🔍 org_members response (email fallback): {res2.data}")
                org_rows = getattr(res2, "data", []) or []

                if x_selected_org_id:
                    user_role_in_tenant = next(
                        (org.get("role") for org in org_rows if str(org.get("org_id")) == str(x_selected_org_id)),
                        None
                    )
                    if not user_role_in_tenant:
                        raise HTTPException(
                            status_code=403,
                            detail="You are not a member of the requested organisation"
                        )
                    return resolved_user_id, x_selected_org_id
                elif org_rows:
                    org_id = org_rows[0]["org_id"]
                    logger.info(f"✅ Org found via email-resolved user_id: {resolved_user_id}, org_id={org_id}")
                    return resolved_user_id, org_id
                else:
                    logger.warning(f"Email fallback: no org_members row for resolved_user_id={resolved_user_id}")
            else:
                logger.warning(f"Email fallback: no profile found for email={email}")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Email fallback lookup failed: {e}", exc_info=True)
    else:
        logger.warning("No email available from token")

    logger.error(f"❌ No org for token_user_id={token_user_id}, email={email}, resolved_id={resolved_user_id}")
    raise HTTPException(
        status_code=403,
        detail="Workspace Access Denied. Your credentials match, but you have not been assigned to an organization profile yet."
    )

async def get_current_user_with_role(authorization: str = Header(None), x_selected_org_id: Optional[str] = None) -> Tuple[str, str, str]:
    """FIXED: Includes role validation per tenant instance."""
    user_id, org_id = await get_current_org(authorization, x_selected_org_id)
    client = get_supabase()
    member = await run_sync_db_call(client.table("org_members").select("role").eq("user_id", user_id).eq("org_id", org_id).maybe_single().execute)
    role = member.data["role"] if member and member.data else "customer"
    return user_id, org_id, role

def require_role(allowed_roles: List[str]):
    async def role_checker(user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
        _, _, role = user_data
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Access denied. Required role: {allowed_roles}")
        return user_data
    return role_checker

async def get_user_and_org_names(user_id: str, org_id: str) -> Tuple[str, str]:
    client = get_supabase()

    if user_id.startswith("guest_"):
        first_name = "Guest"
    else:
        try:
            profile_res = await run_sync_db_call(client.table("profiles").select("first_name").eq("id", user_id).maybe_single().execute)
            first_name = profile_res.data["first_name"] if profile_res and profile_res.data else "there"
        except Exception as e:
            logger.warning(f"Failed to fetch profile for user {user_id}: {e}")
            first_name = "there"

    try:
        org_res = await run_sync_db_call(client.table("organisations").select("org_name").eq("id", org_id).maybe_single().execute)
        org_name = org_res.data["org_name"] if org_res and org_res.data else "our organization"
    except Exception as e:
        logger.warning(f"Failed to fetch org for {org_id}: {e}")
        org_name = "our organization"

    return first_name, org_name

async def get_full_conversation_history(user_id: str, session_id: str, limit: int = 20) -> List[Dict]:
    client = get_supabase()
    if not client:
        return []
    try:
        result = await run_sync_db_call(
            client.table("chat_messages").select("message, response, created_at")
            .eq("user_id", user_id)
            .eq("session_id", session_id)
            .order("created_at", desc=False).limit(limit).execute
        )
        if not result.data:
            return []
        history = []
        for msg in result.data:
            if msg.get("message"):
                history.append({"role": "user", "content": msg["message"]})
            if msg.get("response"):
                history.append({"role": "assistant", "content": msg["response"]})
        return history
    except Exception as e:
        logger.error(f"History error: {e}", exc_info=True)
        return []


# ------------------------------------------------------------------
# *** THE CRITICAL FIX ***
# vector_search is now strictly tenant-scoped in BOTH paths.
# ------------------------------------------------------------------
async def vector_search(org_id: str, query: str, top_k: int = None, threshold: float = None) -> List[Dict]:
    if top_k is None: top_k = RAG_TOP_K
    if threshold is None: threshold = RAG_THRESHOLD
    client = get_supabase()
    if not client:
        return []
    embedder = get_embedder()
    use_vector = embedder is not None
    if use_vector:
        try:
            query_embedding = embedder.encode(query).tolist()
            # RPC now accepts and enforces p_org_id — no cross-tenant leakage possible.
            result = await run_sync_db_call(
                client.rpc('match_knowledge_documents', {
                    'query_embedding': query_embedding,
                    'match_threshold': threshold,
                    'match_count': top_k * 2,
                    'p_org_id': org_id,
                }).execute
            )

            if result.data:
                # RPC already filtered by org_id. Return as-is.
                return result.data[:top_k]
        except Exception as e:
            logger.warning(f"Vector search error: {e}, fallback to keyword")

    # ─── KEYWORD FALLBACK — org-scoped at the DB layer ───
    try:
        all_rows = await run_sync_db_call(
            client.table("general_knowledge")
            .select("category, title, content, keywords")
            .eq("org_id", org_id)          # ← tenant-scoped. No cross-tenant reads.
            .execute
        )
        if not all_rows.data:
            return []
        q_lower = query.lower()
        scored = []
        for row in all_rows.data:
            content = row.get('content', '')
            title = row.get('title', '')
            keywords = row.get('keywords', []) or []
            score = 0
            if title and query.lower() in title.lower():
                score += 50
            for kw in keywords:
                if kw and kw.lower() in q_lower:
                    score += 30
            for word in q_lower.split():
                if len(word) > 3 and word in content.lower():
                    score += 5
            if score > 0:
                scored.append({"content": content, "title": title, "score": score})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]
    except Exception as e:
        logger.error(f"Keyword search error: {e}", exc_info=True)
        return []

async def get_relevant_context(org_id: str, query: str, max_tokens: int = None, top_k: int = None, threshold: float = None) -> str:
    if max_tokens is None: max_tokens = RAG_MAX_TOKENS
    if top_k is None: top_k = RAG_TOP_K
    if threshold is None: threshold = RAG_THRESHOLD
    relevant = await vector_search(org_id, query, top_k=top_k, threshold=threshold)
    if not relevant:
        return ""
    parts = []
    total_est = 0
    for item in relevant:
        content = item.get("content", "")
        est_tokens = len(content) // 4
        if total_est + est_tokens > max_tokens:
            max_chars = (max_tokens - total_est) * 4
            parts.append(content[:max_chars] + "...")
            break
        parts.append(content)
        total_est += est_tokens
    return "\n\n".join(parts)


async def search_inventory(org_id: str, query: str, limit: int = 5) -> List[Dict]:
    client = get_supabase()
    if not client:
        return []
    try:
        result = await run_sync_db_call(
            client.table("inventory")
            .select("id, description, item_code, price_naira, current_qty, product_group")
            .eq("org_id", org_id)
            .or_(f"description.ilike.%{query}%,item_code.ilike.%{query}%")
            .limit(limit)
            .execute
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Inventory search error: {e}", exc_info=True)
        return []


async def get_loyalty_info_by_user_id(user_id: str) -> Optional[Dict]:
    client = get_supabase()
    if not client:
        return None
    try:
        result = await run_sync_db_call(
            client.table("profiles")
            .select("first_name, current_points, tier, membership_id, phone")
            .eq("id", user_id)
            .maybe_single()
            .execute
        )
        if result and result.data:
            return result.data
    except Exception as e:
        logger.error(f"Loyalty fetch error: {e}", exc_info=True)
    return None

async def create_support_ticket(user_id: str, org_id: str, subject: str, message: str, priority: str = "normal") -> Optional[str]:
    client = get_supabase()
    branch_id_for_ticket = await resolve_branch_for_write(org_id)
    ticket = await run_sync_db_call(
        client.table("support_tickets").insert({
            "user_id": user_id,
            "org_id": org_id,
            "branch_id": branch_id_for_ticket,
            "subject": subject,
            "priority": priority,
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute
    )
    if not ticket.data:
        return None
    ticket_id = ticket.data[0]["id"]
    await run_sync_db_call(
        client.table("ticket_messages").insert({
            "ticket_id": ticket_id,
            "sender_type": "user",
            "sender_id": user_id,
            "message": message,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute
    )
    return str(ticket_id)

async def save_conversation(user_id: str, org_id: str, session_id: str, message: str, response: str, channel: str = "website"):
    client = get_supabase()
    if not client:
        return
    try:
        try:
            sess = await run_sync_db_call(client.table("chat_sessions").select("id").eq("id", session_id).maybe_single().execute)
        except Exception as e:
            logger.warning(f"chat_sessions table query failed: {e}. Skipping conversation save.")
            return

        if not sess or not sess.data:
            try:
                branch_id_for_session = await resolve_branch_for_write(org_id)
                new_sess = await run_sync_db_call(
                    client.table("chat_sessions").insert({
                        "id": session_id,
                        "user_id": user_id,
                        "org_id": org_id,
                        "branch_id": branch_id_for_session,
                        "channel": channel,
                        "started_at": datetime.now(timezone.utc).isoformat()
                    }).execute
                )
                if not new_sess.data:
                    logger.error("Failed to create chat session")
                    return
            except Exception as e:
                logger.error(f"Failed to insert chat session: {e}")
                return

        await run_sync_db_call(
            client.table("chat_messages").insert({
                "session_id": session_id,
                "user_id": user_id,
                "org_id": org_id,
                "message": message,
                "response": None,
                "created_at": datetime.now(timezone.utc).isoformat()
            }).execute
        )

        await run_sync_db_call(
            client.table("chat_messages").insert({
                "session_id": session_id,
                "user_id": user_id,
                "org_id": org_id,
                "message": None,
                "response": response,
                "created_at": datetime.now(timezone.utc).isoformat()
            }).execute
        )
    except Exception as e:
        logger.error(f"Save conversation error: {e}", exc_info=True)

# ------------------------------------------------------------------
# get_strategic_reply
# ------------------------------------------------------------------
async def get_strategic_reply(
    user_message: str,
    user_id: str,
    org_id: str,
    session_id: str,
    channel: str = "website"
) -> Tuple[str, Optional[str]]:

    greetings = ["hello", "hi", "hey", "good morning", "good afternoon", "good evening", "howdy", "greetings"]
    if any(greet in user_message.lower() for greet in greetings):
        return "Hello! How can I help you? Ask me about products, orders, or store info.", None

    is_product_query = False
    product_keywords = [
        "price", "cost", "stock", "available", "availability",
        "inventory", "product", "item", "model", "sku",
        "specs", "specification", "dimensions", "do you have",
        "in stock", "is there", "have you got"
    ]
    if any(kw in user_message.lower() for kw in product_keywords):
        is_product_query = True
        return (
            "For product availability and pricing, please use the search bar on our store page. "
            "You can also browse our categories there. I'm here to help with orders, policies, and other questions.",
            None
        )

    service_keywords = [
        "services", "offer", "what do you do", "about your company",
        "your offerings", "company services", "business services", "service offerings"
    ]
    is_service_query = any(phrase in user_message.lower() for phrase in service_keywords)

    if not is_service_query:
        if not semantic_firewall(user_message, threshold=0.30):
            logger.info(f"Off-topic message blocked: {user_message[:50]}")
            return fallback_response(), None
    else:
        logger.info(f"Service query allowed (bypass): {user_message[:50]}")

    complaint_keywords = [
        'broken', 'damaged', 'wrong', 'late', 'missing', 'defective',
        'not working', 'issue', 'problem', 'complaint', 'poor service', 'billing error'
    ]
    if any(kw in user_message.lower() for kw in complaint_keywords):
        if user_id.startswith("guest_"):
            return "Please log in to create a support ticket. Once logged in, you can resubmit your issue.", None
        ticket_id = await create_support_ticket(
            user_id, org_id, "Customer complaint",
            f"User message: {user_message}\nAuto-detected complaint."
        )
        return f"✅ I've created a support ticket (ID: {ticket_id[:8]}) for your issue. Our team will get back to you within 24 hours.", ticket_id

    first_name, org_name = await get_user_and_org_names(user_id, org_id)
    loyalty_data = await get_loyalty_info_by_user_id(user_id)
    loyalty_text = f"Customer {first_name} has {loyalty_data.get('current_points',0)} points, tier {loyalty_data.get('tier','Standard')}" if loyalty_data else ""
    history = await get_full_conversation_history(user_id, session_id, limit=20)
    context = await get_relevant_context(org_id, user_message)

    history_text = ""
    if history:
        recent = history[-10:]
        history_text = "\n".join([f"{h['role']}: {h['content']}" for h in recent])

    product_context = ""
    if is_product_query:
        inventory_results = await search_inventory(org_id, user_message, limit=5)
        if inventory_results:
            inv_lines = []
            for p in inventory_results:
                desc = p.get('description', 'Unknown')
                sku = p.get('item_code', 'N/A')
                price = p.get('price_naira', 0)
                stock = p.get('current_qty', 0)
                inv_lines.append(f"- {desc} (SKU: {sku}) | ₦{price:.2f} | Stock: {stock}")
            product_context = "Inventory search results:\n" + "\n".join(inv_lines)
        else:
            product_context = "No matching products found in inventory."

    if product_context:
        if context:
            context = f"{context}\n\n{product_context}"
        else:
            context = product_context

    system_prompt = f"""You are {org_name}'s AI assistant, Kevs Assistant.
You are speaking with {first_name}, a registered customer.
{loyalty_text}
Business knowledge (provided via `context` below):
{context if context else "(none)"}
Conversation history:
{history_text if history_text else "(start of conversation)"}
🔴 **MANDATORY RULES – follow in exact priority order:**
1. **If `context` is NOT empty:**
   - You MUST set `action` = "reply".
   - You MUST set `confidence` = 0.95.
   - You MUST set `message` to the **exact, verbatim content** from the `content` field that best answers the question.
   - DO NOT paraphrase, summarize, reword, add extra questions, or expand.
   - DO NOT escalate or create a ticket – the answer is already provided.
2. **If `context` IS empty:**
   - Set `action` = "escalate".
   - Set `confidence` = 0.1.
   - Set `message` = "I don't have that information in my knowledge base."
3. **If the user expresses a complaint** (damaged, wrong item, late delivery, poor service, billing error, defective, missing parts), **override** and set `action` = "create_ticket" with a descriptive subject.
4. **If the user explicitly asks to create a ticket or talk to a human**, set `action` = "create_ticket".
You MUST respond with a valid JSON object only, no extra text. The JSON must follow this schema:
{{
    "message": "Your response – verbatim content or fallback",
    "confidence": 0.95,
    "action": "reply" or "create_ticket" or "escalate",
    "metadata": {{ "ticket_subject": "only if action is create_ticket" }}
}}
Do NOT hallucinate order numbers, phone numbers, or personal data.
User's latest message: {user_message}
Respond with ONLY the JSON object, no markdown, no backticks."""

    try:
        raw = await call_llm(system_prompt)
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON found in LLM output")
        parsed = json.loads(json_match.group())
        safe = SafeReply(**parsed)
    except Exception as e:
        logger.error(f"LLM output validation failed: {e}\nRaw output: {raw}")
        if user_id.startswith("guest_"):
            return "Please log in to continue. If you need help, please log in and try again.", None
        ticket_id = await create_support_ticket(
            user_id, org_id, "LLM validation failure",
            f"User: {user_message}\nError: {e}"
        )
        return escalation_response(), ticket_id

    if context:
        logger.info("Context exists. Forcing verbatim reply (ignoring LLM confidence/action).")
        safe.action = "reply"
        safe.confidence = 0.95
        safe.message = context.strip() if isinstance(context, str) else str(context).strip()
        logger.info(f"Overridden message (first 100 chars): {safe.message[:100]}...")
    else:
        logger.info("No context – relying on LLM decision.")

    if safe.action == "create_ticket":
        if user_id.startswith("guest_"):
            return "Please log in to create a support ticket. Once logged in, you can resubmit your request.", None
        ticket_subject = safe.metadata.get("ticket_subject", f"Support request from {first_name}")
        ticket_id = await create_support_ticket(
            user_id, org_id, ticket_subject,
            f"User message: {user_message}\nAI context: {context}"
        )
        return f"✅ I've created a support ticket (ID: {ticket_id[:8]}). Our team will reach out within 24 hours.", ticket_id

    elif safe.action == "escalate" or safe.confidence < 0.6:
        if user_id.startswith("guest_"):
            return "Please log in to get further assistance. Once logged in, we can escalate your query.", None
        ticket_id = await create_support_ticket(
            user_id, org_id, "Low confidence query",
            f"User: {user_message}\nConfidence: {safe.confidence}"
        )
        return escalation_response(), ticket_id

    else:
        final_message = safe.message.strip()
        if any(phrase in final_message.lower() for phrase in ["fake", "scam", "steal"]):
            final_message = "I cannot answer that. Please contact support for help."
        if len(final_message) > 800:
            final_message = final_message[:797] + "..."
        return final_message, None

# ------------------------------------------------------------------
# Knowledge base Pydantic models
# ------------------------------------------------------------------
class KnowledgeBaseCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., max_length=5000)
    keywords: List[str] = []

class KnowledgeBaseUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    content: Optional[str] = Field(None, max_length=5000)
    keywords: Optional[List[str]] = None

# ------------------------------------------------------------------
# Audit Event Models
# ------------------------------------------------------------------
class AuditEventIn(BaseModel):
    event_type: str = Field(..., max_length=100, description="e.g., sale.created, user.login")
    event_version: int = Field(1, description="Schema version for future compatibility")
    payload: dict = Field(..., description="The event payload (free-form JSON)")
    local_created_at: Optional[datetime] = Field(None, description="Client-side timestamp")

    @validator('event_type')
    def validate_event_type(cls, v):
        allowed = [
            'sale.created', 'sale.updated', 'payment.received',
            'points.redeemed', 'customer.added', 'stock.adjusted',
            'batch.added', 'transfer.created', 'user.login',
            'user.logout', 'password.reset', 'sync.completed',
            'error.occurred'
        ]
        if v not in allowed:
            raise ValueError(f'Invalid event_type: {v}')
        return v

class AuditEventBatchIn(BaseModel):
    events: List[AuditEventIn]

# ------------------------------------------------------------------
# LOCATION MANAGEMENT MODELS
# ------------------------------------------------------------------
class LocationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    address: Optional[str] = None
    type: Literal["warehouse", "store", "online_fulfillment"] = "store"
    branch_id: Optional[str] = Field(
        None,
        description="Branch this location belongs to. Defaults to the org's MAIN branch.",
    )
    is_warehouse: Optional[bool] = None  # deprecated, derived from type

class LocationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    address: Optional[str] = None
    type: Optional[Literal["warehouse", "store", "online_fulfillment"]] = None
    branch_id: Optional[str] = None
    is_warehouse: Optional[bool] = None
    is_active: Optional[bool] = None
    
class StockTransferRequest(BaseModel):
    from_location_id: Optional[str] = None   # locations.id is UUID
    to_location_id: str                       # locations.id is UUID
    inventory_id: int
    quantity: int = Field(..., gt=0)
    request_notes: Optional[str] = None

class StockTransferUpdate(BaseModel):
    status: Literal["approved", "rejected", "completed"]
    approval_notes: Optional[str] = None
    tracking_number: Optional[str] = None

# ===================== SUPPLIER MODELS =====================
class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    contact_person: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    payment_terms: Optional[str] = None

class SupplierUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    contact_person: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    payment_terms: Optional[str] = None
    status: Optional[Literal["active", "inactive"]] = None

# ===================== PURCHASE ORDER MODELS =====================
class POItemCreate(BaseModel):
    inventory_id: int
    quantity_ordered: int = Field(..., gt=0)
    unit_cost: Decimal = Field(..., gt=0)

class POCreate(BaseModel):
    supplier_id: UUID
    expected_delivery_date: date
    notes: Optional[str] = None
    items: List[POItemCreate] = Field(..., min_items=1)

class POItemUpdate(BaseModel):
    id: Optional[UUID] = None
    inventory_id: Optional[int] = None
    quantity_ordered: Optional[int] = Field(None, gt=0)
    unit_cost: Optional[Decimal] = Field(None, gt=0)

class POUpdate(BaseModel):
    supplier_id: Optional[UUID] = None
    expected_delivery_date: Optional[date] = None
    notes: Optional[str] = None
    items: Optional[List[POItemUpdate]] = None

class POStatusUpdate(BaseModel):
    status: Literal["sent", "received", "cancelled"]

# ===================== GRN MODELS =====================
class GRNItemCreate(BaseModel):
    po_item_id: UUID
    received_quantity: int = Field(..., gt=0)
    accepted_quantity: int = Field(..., ge=0)
    rejected_quantity: int = Field(0, ge=0)
    rejection_reason: Optional[str] = None
    batch_number: str = Field(..., min_length=1, description="Batch number from supplier (required)")
    expiry_date: date = Field(..., description="Expiry date printed on goods (required)")
    cost_price_naira: Optional[Decimal] = None

class GRNCreate(BaseModel):
    po_id: UUID
    received_date: date
    location_id: UUID
    notes: Optional[str] = None
    items: List[GRNItemCreate] = Field(..., min_items=1)

class GRNUpdate(BaseModel):
    received_date: Optional[date] = None
    location_id: Optional[UUID] = None
    notes: Optional[str] = None
    items: Optional[List[GRNItemCreate]] = None

# ===================== HR MODULE MODELS =====================
class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None

class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None

class EmployeeCreate(BaseModel):
    user_id: Optional[str] = None
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    department_id: Optional[int] = None
    position: Optional[str] = None
    hire_date: date
    salary: float = 0.0
    status: str = "active"

class EmployeeUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    department_id: Optional[int] = None
    position: Optional[str] = None
    hire_date: Optional[date] = None
    salary: Optional[float] = None
    status: Optional[str] = None

class AttendanceClockIn(BaseModel):
    employee_id: int
    clock_in: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AttendanceClockOut(BaseModel):
    employee_id: int
    clock_out: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class LeaveRequestCreate(BaseModel):
    employee_id: int
    leave_type: str = Field(..., pattern="^(annual|sick|personal)$")
    start_date: date
    end_date: date
    reason: Optional[str] = None

class LeaveRequestUpdate(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected)$")
    approved_by: Optional[str] = None
    notes: Optional[str] = None

class PayrollGenerate(BaseModel):
    month: int = Field(..., ge=1, le=12)
    year: int

# ===================== HR HELPERS =====================
async def get_employee_by_user_id(user_id: str, org_id: str) -> Optional[Dict]:
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("hr_employees")
        .select("*")
        .eq("user_id", user_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    return result.data

async def get_employee_by_id(employee_id: int, org_id: str) -> Optional[Dict]:
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("hr_employees")
        .select("*")
        .eq("id", employee_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    return result.data

# ------------------------------------------------------------------
# LOCATION MANAGEMENT ENDPOINTS
# ------------------------------------------------------------------
@app.get("/locations")
async def list_locations(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "logistics"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("locations")
        .select("*")
        .eq("org_id", org_id)
        .order("is_warehouse", desc=True)
        .order("name", desc=False)
        .execute
    )
    return {"locations": result.data}

@app.post("/locations")
async def create_location(
    request: Request,
    loc: LocationCreate,
    user_data: Tuple[str, str, str] = Depends(
        require_feature("multi_location", allowed_roles=["owner", "admin", "inventory_manager"])
    )
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    # ── Branch resolution ──
    if loc.branch_id:
        # Caller supplied one — validate it belongs to this org.
        branch_check = await run_sync_db_call(
            client.table("branches")
            .select("id")
            .eq("id", loc.branch_id)
            .eq("org_id", org_id)
            .maybe_single()
            .execute
        )
        if not branch_check or not branch_check.data:
            raise HTTPException(
                status_code=400,
                detail="Branch not found in this organisation",
            )
        resolved_branch = loc.branch_id
    else:
        # Fall back to the org's default branch, seeding MAIN if needed.
        resolved_branch = await ensure_default_branch(org_id)
        if not resolved_branch:
            raise HTTPException(
                status_code=500,
                detail="Could not resolve a default branch for this organisation",
            )

    now = datetime.now(timezone.utc).isoformat()
    data = {
        "org_id":       org_id,
        "name":         loc.name,
        "address":      loc.address,
        "type":         loc.type,
        "branch_id":    resolved_branch,
        # keep is_warehouse consistent with type for the legacy readers
        "is_warehouse": loc.type == "warehouse",
        "is_active":    True,
        "created_at":   now,
        "updated_at":   now,
    }
    result = await run_sync_db_call(client.table("locations").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create location")
    return {"location": result.data[0]}
    
@app.put("/locations/{location_id}")
async def update_location(
    request: Request,
    location_id: int,
    loc: LocationUpdate,
    user_data: Tuple[str, str, str] = Depends(
        require_feature("multi_location", allowed_roles=["owner", "admin", "inventory_manager"])
    )
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    existing = await run_sync_db_call(
        client.table("locations")
        .select("id")
        .eq("id", location_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Location not found")

    update_data = {
        k: v for k, v in loc.dict(exclude_unset=True).items()
        if v is not None
    }

    # Validate branch_id if the caller is changing it.
    if "branch_id" in update_data:
        branch_check = await run_sync_db_call(
            client.table("branches")
            .select("id")
            .eq("id", update_data["branch_id"])
            .eq("org_id", org_id)
            .maybe_single()
            .execute
        )
        if not branch_check or not branch_check.data:
            raise HTTPException(
                status_code=400,
                detail="Branch not found in this organisation",
            )

    if "type" in update_data:
        # keep is_warehouse in sync when type changes
        update_data["is_warehouse"] = update_data["type"] == "warehouse"

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = await run_sync_db_call(
        client.table("locations")
        .update(update_data)
        .eq("id", location_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update location")

    return {"location": result.data[0]}
    


@app.delete("/locations/{location_id}")
async def delete_location(
    request: Request,
    location_id: int,
    user_data: Tuple[str, str, str] = Depends(
        require_feature("multi_location", allowed_roles=["owner", "admin"])
    )
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    existing = await run_sync_db_call(
        client.table("locations")
        .select("id")
        .eq("id", location_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Location not found")

    stock = await run_sync_db_call(
        client.table("location_stocks")
        .select("id")
        .eq("location_id", location_id)
        .limit(1)
        .execute
    )
    if stock.data:
        raise HTTPException(status_code=400, detail="Cannot delete location with existing stock. Transfer stock first.")

    result = await run_sync_db_call(
        client.table("locations")
        .delete()
        .eq("id", location_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to delete location")

    return {"message": "Location deleted successfully"}

@app.get("/inventory/v2")
async def get_inventory_by_location(
    request: Request,
    location_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "inventory_manager", "sales_rep", "finance"])
    )
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data

    # The all-locations fan-out is a multi-location feature. The
    # single-location read is available on every plan because every
    # org has at least one location.
    if location_id is None:
        await check_org_feature(org_id, "multi_location")

    client = get_supabase()

    # Build the query in one shot — supabase-py does NOT allow calling .select() twice.
    if location_id is not None:
        inv_query = (
            client.table("inventory")
            .select(
                "*, location_stocks!inner(location_id, quantity, reserved_quantity)",
                count="exact",
            )
            .eq("org_id", org_id)
            .eq("location_stocks.location_id", location_id)
        )
    else:
        inv_query = (
            client.table("inventory")
            .select("*", count="exact")
            .eq("org_id", org_id)
        )

    inv_result = await run_sync_db_call(inv_query.range(offset, offset + limit - 1).execute)
    inventory_items = inv_result.data or []
    total_count = inv_result.count or 0

    if not inventory_items:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    # Fetch locations once — needed both for naming and for the un-filtered fan-out.
    locations_res = await run_sync_db_call(
        client.table("locations").select("id, name").eq("org_id", org_id).execute
    )
    locations_rows = locations_res.data or []
    location_name_by_id = {loc["id"]: loc["name"] for loc in locations_rows}

    # ── Single-location view ──
    if location_id is not None:
        items = []
        for inv in inventory_items:
            stock_info = inv.pop("location_stocks", None) or []
            stock = stock_info[0] if stock_info else {}
            qty = int(stock.get("quantity") or 0)
            items.append({
                **inv,
                "current_qty":      qty,               # override so card badge is location-scoped
                "location_qty":     qty,
                "location_id":      location_id,
                "location_name":    location_name_by_id.get(location_id),
                "reserved_quantity": int(stock.get("reserved_quantity") or 0),
                "location_stocks": [{
                    "location_id":   location_id,
                    "location_name": location_name_by_id.get(location_id),
                    "quantity":      qty,
                    "reserved_quantity": int(stock.get("reserved_quantity") or 0),
                }],
            })
        return {"items": items, "total": total_count, "limit": limit, "offset": offset}

    # ── All-locations view: fan out per location ──
    location_ids = [loc["id"] for loc in locations_rows]
    if not location_ids:
        for inv in inventory_items:
            inv["location_stocks"] = []
        return {"items": inventory_items, "total": total_count, "limit": limit, "offset": offset}

    stock_query = (
        client.table("location_stocks")
        .select("location_id, inventory_id, quantity, reserved_quantity")
        .in_("inventory_id", [inv["id"] for inv in inventory_items])
        .in_("location_id", location_ids)
    )
    stock_result = await run_sync_db_call(stock_query.execute)
    stock_rows = stock_result.data or []

    stock_by_inv = defaultdict(dict)
    for s in stock_rows:
        stock_by_inv[s["inventory_id"]][s["location_id"]] = {
            "quantity": int(s.get("quantity") or 0),
            "reserved_quantity": int(s.get("reserved_quantity") or 0),
        }

    items = []
    for inv in inventory_items:
        inv_id = inv["id"]
        per_location = []
        for loc in locations_rows:
            loc_id = loc["id"]
            stock = stock_by_inv.get(inv_id, {}).get(loc_id, {"quantity": 0, "reserved_quantity": 0})
            per_location.append({
                "location_id":   loc_id,
                "location_name": loc["name"],
                "quantity":      stock["quantity"],
                "reserved_quantity": stock["reserved_quantity"],
            })
        inv["location_stocks"] = per_location
        items.append(inv)

    return {"items": items, "total": total_count, "limit": limit, "offset": offset}

@app.get("/inventory/search")
async def search_inventory_endpoint(
    request: Request,
    q: str = Query(..., min_length=1),
    location_id: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "sales_rep"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    or_condition = f"description.ilike.%{q}%,item_code.ilike.%{q}%,product_group.ilike.%{q}%"

    query = (
        client.table("inventory")
        .select("*, location_stocks!left(location_id, quantity, reserved_quantity)", count="exact")
        .eq("org_id", org_id)
    )

    query.params = query.params.set("or", f"({or_condition})")

    if location_id is not None:
        query = query.eq("location_stocks.location_id", location_id)

    result = await run_sync_db_call(
        query.range(offset, offset + limit - 1).execute
    )

    items = result.data or []
    total = result.count or 0

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset
    }

# ------------------------------------------------------------------
# STOCK TRANSFER ENDPOINTS
# ------------------------------------------------------------------
@app.post("/stock-transfers/request")
async def request_stock_transfer(
    request: Request,
    transfer: StockTransferRequest,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    if transfer.from_location_id:
        from_loc = await run_sync_db_call(client.table("locations").select("id").eq("id", transfer.from_location_id).eq("org_id", org_id).maybe_single().execute)
        if not from_loc.data:
            raise HTTPException(status_code=404, detail="Source location not found")

    to_loc = await run_sync_db_call(client.table("locations").select("id").eq("id", transfer.to_location_id).eq("org_id", org_id).maybe_single().execute)
    if not to_loc.data:
        raise HTTPException(status_code=404, detail="Destination location not found")

    inventory_item = await run_sync_db_call(client.table("inventory").select("id, description, current_qty").eq("id", transfer.inventory_id).eq("org_id", org_id).maybe_single().execute)
    if not inventory_item.data:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    if transfer.from_location_id:
        source_stock = await run_sync_db_call(
            client.table("location_stocks")
            .select("quantity, reserved_quantity")
            .eq("location_id", transfer.from_location_id)
            .eq("inventory_id", transfer.inventory_id)
            .execute
        )

        rows = source_stock.data or []
        total_qty      = sum(int(r.get("quantity", 0) or 0) for r in rows)
        total_reserved = sum(int(r.get("reserved_quantity", 0) or 0) for r in rows)
        available_qty  = total_qty - total_reserved
        if available_qty < transfer.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock at source location. Available: {available_qty}"
            )

    branch_id_for_transfer = None
    if transfer.from_location_id:
        from_loc_full = await run_sync_db_call(
            client.table("locations").select("branch_id")
            .eq("id", transfer.from_location_id).maybe_single().execute
        )
        if from_loc_full and from_loc_full.data:
            branch_id_for_transfer = from_loc_full.data.get("branch_id")
    if not branch_id_for_transfer:
        branch_id_for_transfer = await resolve_branch_for_write(org_id)

    # Insert the transfer record
    result = await run_sync_db_call(
        client.table("stock_transfers").insert({
            "org_id": org_id,
            "branch_id": branch_id_for_transfer,
            "from_location_id": transfer.from_location_id,
            "to_location_id": transfer.to_location_id,
            "inventory_id": transfer.inventory_id,
            "quantity": transfer.quantity,
            "status": "pending",
            "requested_by": user_id,
            "request_notes": transfer.request_notes,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create transfer request")
    transfer_id = result.data[0]["id"]

    # Location-to-location transfers within a branch complete immediately —
    # there is no approval step. The RPC moves the stock atomically.
    try:
        await run_sync_db_call(
            client.rpc("complete_stock_transfer", {
                "p_transfer_id":     transfer_id,
                "p_user_id":         user_id,
                "p_notes":           transfer.request_notes,
                "p_tracking_number": None,
            }).execute
        )
    except Exception as e:
        # Roll back the pending row so we don't leave a ghost transfer
        try:
            await run_sync_db_call(
                client.table("stock_transfers").delete().eq("id", transfer_id).execute
            )
        except Exception as cleanup_err:
            logger.error(f"Failed to clean up transfer {transfer_id}: {cleanup_err}")

        detail = str(e)
        if "Insufficient" in detail:
            raise HTTPException(status_code=400, detail=detail)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        logger.error(f"Auto-complete transfer {transfer_id} failed: {detail}")
        raise HTTPException(status_code=500, detail=f"Transfer failed: {detail}")

    refreshed = await run_sync_db_call(
        client.table("stock_transfers")
        .select("*, from_location:from_location_id(name), to_location:to_location_id(name), inventory:inventory_id(description, item_code)")
        .eq("id", transfer_id)
        .maybe_single()
        .execute
    )
    return {
        "transfer": refreshed.data if refreshed else None,
        "message": "Transfer completed immediately"
    }

@app.get("/stock-transfers")
async def list_stock_transfers(
    request: Request,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "logistics"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    query = client.table("stock_transfers") \
        .select("*, from_location:from_location_id(name), to_location:to_location_id(name), inventory:inventory_id(description, item_code), requested_by_user:requested_by(first_name, last_name), approved_by_user:approved_by(first_name, last_name)") \
        .eq("org_id", org_id)

    if status:
        query = query.eq("status", status)

    result = await run_sync_db_call(query.order("created_at", desc=True).range(offset, offset + limit - 1).execute)

    return {"transfers": result.data, "total": len(result.data) if result.data else 0}

@app.get("/stock-transfers/{transfer_id}")
async def get_stock_transfer(
    request: Request,
    transfer_id: int,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "logistics"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    result = await run_sync_db_call(
        client.table("stock_transfers")
        .select("*, from_location:from_location_id(*), to_location:to_location_id(*), inventory:inventory_id(*), requested_by_user:requested_by(first_name, last_name, email), approved_by_user:approved_by(first_name, last_name, email)")
        .eq("id", transfer_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Transfer not found")

    return {"transfer": result.data[0]}

@app.put("/stock-transfers/{transfer_id}/status")
async def update_stock_transfer_status(
    request: Request,
    transfer_id: int,
    update: StockTransferUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    # Ownership check before we let the RPC touch anything
    transfer_check = await run_sync_db_call(
        client.table("stock_transfers")
        .select("id, status")
        .eq("id", transfer_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not transfer_check.data:
        raise HTTPException(status_code=404, detail="Transfer not found")

    current_status = transfer_check.data["status"]
    if current_status == "completed":
        raise HTTPException(status_code=400, detail="Transfer already completed")

    # Rejection is a pure status flip — no stock movement, no RPC needed
    if update.status == "rejected":
        reject_result = await run_sync_db_call(
            client.table("stock_transfers").update({
                "status": "rejected",
                "approved_by": user_id,
                "approval_notes": update.approval_notes,
                "tracking_number": update.tracking_number,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", transfer_id).eq("org_id", org_id).execute
        )
        if not reject_result.data:
            raise HTTPException(status_code=500, detail="Failed to reject transfer")
        return {"transfer": reject_result.data[0]}

    if update.status == "approved":
        rpc_name = "approve_stock_transfer"
    elif update.status == "completed":
        rpc_name = "complete_stock_transfer"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported status: {update.status}")

    try:
        await run_sync_db_call(
            client.rpc(rpc_name, {
                "p_transfer_id":     transfer_id,
                "p_user_id":         user_id,
                "p_notes":           update.approval_notes,
                "p_tracking_number": update.tracking_number,
            }).execute
        )
    except Exception as e:
        logger.error(f"Stock transfer RPC {rpc_name} failed: {e}")
        detail = str(e)
        if "Insufficient" in detail:
            raise HTTPException(status_code=400, detail=detail)
        if "already" in detail.lower():
            raise HTTPException(status_code=400, detail=detail)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        if "Cannot complete a rejected" in detail:
            raise HTTPException(status_code=400, detail=detail)
        raise HTTPException(status_code=500, detail=f"Failed to update transfer: {detail}")

    # Return the freshly-updated row so the frontend sees the new state
    refreshed = await run_sync_db_call(
        client.table("stock_transfers")
        .select("*")
        .eq("id", transfer_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    return {"transfer": refreshed.data[0] if refreshed.data else None}

# ------------------------------------------------------------------
# Auth endpoints
# ------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: str
    password: str
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    invite_code: Optional[str] = None
    org_name: Optional[str] = None
    location: Optional[str] = None
    niche: Optional[str] = None
    budget: Optional[int] = 0
    store_address: Optional[str] = None
    store_latitude: Optional[float] = None
    store_longitude: Optional[float] = None
    delivery_base_fee: Optional[float] = 300
    delivery_per_km_rate: Optional[float] = 80
    delivery_per_kg_rate: Optional[float] = 50

class LoginRequest(BaseModel):
    email: str
    password: str

class ResetPasswordRequest(BaseModel):
    email: str

class RefreshRequest(BaseModel):
    refresh_token: str

@app.post("/auth/register")
async def register(request: Request, auth: RegisterRequest):
    await rate_limit(get_client_ip(request))
    client = get_supabase()

    if not auth.email or not auth.password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    if not auth.first_name or not auth.last_name or not auth.phone:
        raise HTTPException(status_code=400, detail="First name, last name, and phone number are required")

    existing_profile = await run_sync_db_call(
        client.table("profiles")
        .select("id")
        .eq("email", auth.email)
        .maybe_single()
        .execute
    )
    if existing_profile and existing_profile.data:
        raise HTTPException(status_code=400, detail="Email already registered. Please log in or use a different email.")

    org_id = None
    role = "customer"

    if auth.invite_code and auth.invite_code.strip():
        org_result = await run_sync_db_call(client.table("organisations").select("id").eq("invite_code", auth.invite_code).maybe_single().execute)
        if not org_result or not org_result.data:
            raise HTTPException(status_code=400, detail="Invalid invite code")
        org_id = org_result.data["id"]
    elif auth.org_name and auth.location and auth.niche:
        existing = await run_sync_db_call(client.table("organisations").select("id").eq("org_name", auth.org_name).maybe_single().execute)
        if existing and existing.data:
            raise HTTPException(status_code=400, detail="Organisation name already exists. Please use an invite code or different name.")

        store_lat = auth.store_latitude
        store_lng = auth.store_longitude
        if auth.store_address and (store_lat is None or store_lng is None):
            geocode_url = "https://nominatim.openstreetmap.org/search"
            params = {"q": auth.store_address, "format": "json", "limit": 1}
            try:
                async with httpx.AsyncClient(timeout=10.0) as http:
                    geo_resp = await http.get(geocode_url, params=params, headers={"User-Agent": "KevsDigital/1.0"})
                    if geo_resp.status_code == 200:
                        geo_data = geo_resp.json()
                        if geo_data:
                            store_lat = float(geo_data[0]["lat"])
                            store_lng = float(geo_data[0]["lon"])
                            logger.info(f"Geocoded store address '{auth.store_address}' -> ({store_lat}, {store_lng})")
            except Exception as geo_err:
                logger.warning(f"Geocoding failed for store address: {geo_err}")

        invite_code = await generate_invite_code()
        new_org = await run_sync_db_call(
            client.table("organisations").insert({
                "org_name": auth.org_name,
                "location": auth.location,
                "niche": auth.niche,
                "budget": auth.budget or 0,
                "invite_code": invite_code,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "payment_gateway_config": {"provider": "paystack", "credentials": {}},
                "latitude": store_lat,
                "longitude": store_lng,
                "delivery_base_fee": auth.delivery_base_fee or 300,
                "delivery_per_km_rate": auth.delivery_per_km_rate or 80,
                "delivery_per_kg_rate": auth.delivery_per_kg_rate or 50,
                "handling_surcharge_fragile": 200,
                "handling_surcharge_bulky": 500,
                "handling_surcharge_hazardous": 1000
            }).execute
        )
        if not new_org.data:
            raise HTTPException(status_code=500, detail="Failed to create organisation")
        org_id = new_org.data[0]["id"]
        role = "owner"

        # Seed a MAIN branch, then the default warehouse pointing at it.
        try:
            seeded_branch_id = await ensure_default_branch(org_id)
            now_iso = datetime.now(timezone.utc).isoformat()
            await run_sync_db_call(
                client.table("locations").insert({
                    "org_id":       org_id,
                    "name":         "Main Warehouse",
                    "address":      auth.store_address or "Main Store",
                    "branch_id":    seeded_branch_id,
                    "type":         "warehouse",
                    "is_warehouse": True,
                    "is_active":    True,
                    "created_at":   now_iso,
                    "updated_at":   now_iso,
                }).execute
            )
            logger.info(
                "Created default branch+location for org",
                org_id=org_id, branch_id=seeded_branch_id,
            )
        except Exception as loc_err:
            logger.warning(f"Failed to create default branch/location: {loc_err}")
    else:
        default_org_id = PUBLIC_STORE_ORG_ID
        if not default_org_id:
            raise HTTPException(status_code=500, detail="Public store organisation not configured")
        org_id = default_org_id
        role = "customer"

    try:
        # Auth operations use a throwaway anon client so the shared
        # service-role client never carries a user session.
        auth_client = get_user_supabase()
        resp = await run_sync_db_call(auth_client.auth.sign_up, {"email": auth.email, "password": auth.password})
        if not resp.user:
            raise HTTPException(status_code=400, detail="Registration failed")
        user_id = resp.user.id

        await run_sync_db_call(
            client.table("profiles").insert({
                "id": user_id,
                "email": auth.email,
                "first_name": auth.first_name,
                "last_name": auth.last_name,
                "phone": auth.phone,
                "membership_id": f"MEM-{user_id[:8]}",
                "status": "Active"
            }).execute
        )

        await run_sync_db_call(
            client.table("org_members").insert({
                "user_id": user_id,
                "org_id": org_id,
                "role": role,
                "joined_at": datetime.now(timezone.utc).isoformat()
            }).execute
        )

        # Stamp tenant claims onto the auth user so the next JWT carries them
        await _admin_set_app_metadata(user_id, {
            "org_id": org_id,
            "role": role,
            "branch_scope": None,
        })

        return {
            "user_id": user_id,
            "org_id": org_id,
            "role": role,
            "message": "Registration successful. Please verify email (if required)."
        }
    except Exception as e:
        logger.error(f"Registration error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/auth/login")
async def login(request: Request, auth: LoginRequest):
    await rate_limit(get_client_ip(request))
    try:
        # Auth operations use a throwaway anon client so the shared
        # service-role client never carries a user session.
        auth_client = get_user_supabase()
        resp = await run_sync_db_call(auth_client.auth.sign_in_with_password, {"email": auth.email, "password": auth.password})
        if resp.session:
            client = get_supabase()
            profile_res = await run_sync_db_call(client.table("profiles").select("first_name, last_name").eq("id", resp.user.id).maybe_single().execute)
            profile_data = profile_res.data if profile_res else None

            first_name = profile_data.get("first_name", "User") if profile_data else "User"
            last_name = profile_data.get("last_name", "") if profile_data else ""
            display_name = f"{first_name} {last_name}".strip()

            return {
                "user_id": resp.user.id,
                "access_token": resp.session.access_token,
                "refresh_token": resp.session.refresh_token,
                "display_name": display_name,
                "first_name": first_name,
                "last_name": last_name
            }
        raise HTTPException(status_code=401, detail="Invalid credentials")
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@app.post("/auth/refresh")
async def refresh_token(request: Request, req: RefreshRequest):
    await rate_limit(get_client_ip(request))
    try:
        # Refresh must run on a throwaway client — never on the shared one.
        auth_client = get_user_supabase()
        resp = await run_sync_db_call(auth_client.auth.refresh_session, req.refresh_token)
        if resp.session:
            return {
                "access_token": resp.session.access_token,
                "refresh_token": resp.session.refresh_token
            }
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@app.post("/auth/logout")
async def logout(request: Request, authorization: str = Header(None)):
    await rate_limit(get_client_ip(request))

    if not authorization or not authorization.startswith("Bearer "):
        return {"message": "Logged out (no token)"}

    token = authorization.split(" ")[1]
    # The client holds the JWT; the server is stateless. There is no
    # server-side session on the shared client to clear, and calling
    # sign_out on it would be a no-op at best and a footgun at worst.
    # We do not attempt to revoke the token here; the browser discards it.
    try:
        auth_client = get_user_supabase()
        await run_sync_db_call(auth_client.auth.sign_out)
    except Exception as e:
        logger.warning(f"Logout error (ignored): {e}")

    return {"message": "Logged out"}

@app.get("/auth/me")
async def me(request: Request, authorization: str = Header(None), x_selected_org_id: Optional[str] = Header(None)):
    await rate_limit(get_client_ip(request))
    user_data = await get_current_user_with_role(authorization, x_selected_org_id)
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id, org_id, role = user_data

    client = get_supabase()
    profile_res = await run_sync_db_call(client.table("profiles").select("first_name, last_name, email").eq("id", user_id).maybe_single().execute)
    profile_data = profile_res.data if profile_res else None

    first_name = profile_data.get("first_name", "User") if profile_data else "User"
    last_name = profile_data.get("last_name", "") if profile_data else ""
    email = profile_data.get("email") if profile_data else None
    display_name = f"{first_name} {last_name}".strip()

    # branch_scope is stamped into the JWT app_metadata at signup/staff-create time.
    # We expose it here so the frontend can reason about branch visibility.
    branch_scope = None
    try:
        token = None
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]
        if token:
            auth_client = get_user_supabase()
            user = await run_sync_db_call(auth_client.auth.get_user, token)
            if user and user.user:
                app_meta = getattr(user.user, "app_metadata", None) or {}
                branch_scope = app_meta.get("branch_scope")
    except Exception as e:
        logger.warning(f"Could not read branch_scope from token: {e}")

    return {
        "user_id": user_id,
        "org_id": org_id,
        "role": role,
        "display_name": display_name,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "branch_scope": branch_scope,
    }
# ------------------------------------------------------------------
# TEAM MANAGEMENT
# ------------------------------------------------------------------
class CreateStaffRequest(BaseModel):
    email: str
    first_name: str
    last_name: str
    phone: str = Field(..., min_length=1, description="Phone number is required")
    role: str = "customer"
    send_invite_email: bool = True

@app.get("/organisations/me/users")
async def list_org_members(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data

    members = await supabase_rest_get(
        "org_members",
        select="user_id, role, joined_at",
        filters={"org_id": org_id}
    )
    logger.info(f"🔍 Found {len(members)} members in org {org_id}")

    if not members:
        return {"users": []}

    user_ids = [m["user_id"] for m in members]

    ids_str = ",".join(user_ids)
    filter_string = f"id=in.({ids_str})"

    profiles = await supabase_rest_get(
        "profiles",
        select="id,first_name,last_name,email,phone,status,current_points,tier,created_at,address,date_of_birth",
        filter_string=filter_string
    )
    profile_map = {p["id"]: p for p in profiles}

    users = []
    for m in members:
        profile = profile_map.get(m["user_id"], {})
        users.append({
            "id": m["user_id"],
            "first_name": profile.get("first_name"),
            "last_name": profile.get("last_name"),
            "email": profile.get("email"),
            "phone": profile.get("phone"),
            "role": m["role"],
            "status": profile.get("status", "active"),
            "joined_at": m["joined_at"],
            "loyalty_points": profile.get("current_points", 0),
            "loyalty_tier": profile.get("tier", "bronze"),
            "created_at": profile.get("created_at"),
            "address": profile.get("address"),
            "date_of_birth": profile.get("date_of_birth")
        })

    logger.info(f"✅ Returning {len(users)} users (REST API)")
    return {"users": users}

@app.post("/organisations/me/users")
async def create_staff_member(
    request: Request,
    staff: CreateStaffRequest,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data

    if not staff.phone or not staff.phone.strip():
        raise HTTPException(status_code=400, detail="Phone number is required for staff members")

    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=500, detail="Service role key not configured. Cannot create users.")

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as http_client:
        check_url = f"{SUPABASE_URL}/rest/v1/profiles?select=id&email=eq.{staff.email}"
        check_resp = await http_client.get(check_url, headers=headers)

        if check_resp.status_code == 200 and check_resp.json():
            raise HTTPException(status_code=400, detail="Email already registered")

        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))

        admin_url = f"{SUPABASE_URL}/auth/v1/admin/users"
        admin_payload = {
            "email": staff.email,
            "password": temp_password,
            "email_confirm": True,
            "user_metadata": {
                "first_name": staff.first_name,
                "last_name": staff.last_name,
                "phone": staff.phone or ""
            }
        }

        admin_resp = await http_client.post(admin_url, json=admin_payload, headers=headers)

        if admin_resp.status_code != 200:
            logger.error(f"Admin user creation failed: {admin_resp.text}")
            raise HTTPException(status_code=500, detail=f"Failed to create user: {admin_resp.text}")

        user_data_resp = admin_resp.json()
        user_id = user_data_resp.get("id")

        if not user_id:
            raise HTTPException(status_code=500, detail="Failed to get user ID from creation response")

        profile_data = {
            "id": user_id,
            "email": staff.email,
            "first_name": staff.first_name,
            "last_name": staff.last_name,
            "phone": staff.phone,
            "membership_id": f"MEM-{user_id[:8]}",
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "current_points": 0,
            "tier": "bronze"
        }

        profile_resp = await http_client.post(
            f"{SUPABASE_URL}/rest/v1/profiles",
            json=profile_data,
            headers=headers
        )

        if profile_resp.status_code not in [200, 201]:
            logger.error(f"Profile creation failed: {profile_resp.text}")
            await http_client.delete(f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=headers)
            raise HTTPException(status_code=500, detail="Failed to create user profile")

        member_data = {
            "user_id": user_id,
            "org_id": org_id,
            "role": staff.role,
            "joined_at": datetime.now(timezone.utc).isoformat()
        }

        member_resp = await http_client.post(
            f"{SUPABASE_URL}/rest/v1/org_members",
            json=member_data,
            headers=headers
        )

        if member_resp.status_code not in [200, 201]:
            logger.error(f"Org member creation failed: {member_resp.text}")
            await http_client.delete(f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}", headers=headers)
            await http_client.delete(f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=headers)
            raise HTTPException(status_code=500, detail="Failed to add user to organisation")

    await _admin_set_app_metadata(user_id, {
        "org_id": org_id,
        "role": staff.role,
        "branch_scope": None,
    })

    if staff.send_invite_email:
        login_link = f"{PRODUCTION_HOST}/kdsiginin"
        html = f"""
        <h2>Welcome to your organisation</h2>
        <p>You have been added as a <strong>{staff.role}</strong>.</p>
        <p>Your temporary password: <code>{temp_password}</code></p>
        <p>Please login here: <a href="{login_link}">{login_link}</a> and change your password immediately.</p>
        """
        await send_sendgrid_email(staff.email, "Your staff account has been created", html)

    return {
        "user_id": user_id,
        "message": f"Staff invited. Temporary password sent to {staff.email}."
    }

@app.delete("/organisations/me/users/{target_user_id}")
async def remove_staff_member(
    request: Request,
    target_user_id: str,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"])),
    x_admin_key: Optional[str] = Header(None)
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    current_user_id, org_id, current_role = user_data

    if target_user_id == current_user_id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself")

    client = get_supabase()
    membership = await run_sync_db_call(client.table("org_members").select("role").eq("user_id", target_user_id).eq("org_id", org_id).maybe_single().execute)
    if not membership.data:
        raise HTTPException(status_code=404, detail="User not found in this organisation")

    target_role = membership.data["role"]

    if target_role == "owner" and current_role != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can delete another owner")

    if target_role == "owner":
        if not x_admin_key or x_admin_key != ADMIN_SECRET_KEY:
            raise HTTPException(status_code=403, detail="Admin secret key required to delete an owner")

    await run_sync_db_call(client.table("org_members").delete().eq("user_id", target_user_id).eq("org_id", org_id).execute)
    await run_sync_db_call(client.table("profiles").update({"status": "inactive"}).eq("id", target_user_id).execute)

    return {"message": "Staff member removed"}

@app.post("/auth/admin-reset-password")
async def admin_reset_password(
    request: Request,
    email: str,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data

    # Ownership check uses the shared service-role client so RLS doesn't
    # hide rows from us. This is a pure read — no auth mutation.
    client = get_supabase()
    profile = await run_sync_db_call(client.table("profiles").select("id").eq("email", email).maybe_single().execute)
    if not profile.data:
        raise HTTPException(status_code=404, detail="Email not found")
    membership = await run_sync_db_call(client.table("org_members").select("role").eq("user_id", profile.data["id"]).eq("org_id", org_id).maybe_single().execute)
    if not membership.data:
        raise HTTPException(status_code=403, detail="User not in your organisation")

    try:
        # Auth operation — must run on a throwaway anon client so the
        # shared service-role client never picks up a session.
        auth_client = get_user_supabase()
        await run_sync_db_call(auth_client.auth.reset_password_for_email, email)
        return {"message": f"Password reset email sent to {email}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/reset-password")
async def reset_password(request: Request, req: ResetPasswordRequest):
    await rate_limit(get_client_ip(request))

    client = get_supabase()

    profile = None
    try:
        profile = await run_sync_db_call(client.table("profiles").select("id").eq("email", req.email).maybe_single().execute)
    except Exception as e:
        logger.warning(f"Profile query failed for {req.email}: {e}")

    if profile is None or not profile.data:
        return {"message": "If the email exists, a reset link has been sent."}

    url = f"{SUPABASE_URL}/auth/v1/recover"
    headers = {
        "apikey": SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "email": req.email,
        "redirect_to": f"{PRODUCTION_HOST}/kdsiginin"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                return {"message": "Password reset email sent. Please check your inbox."}
            elif resp.status_code == 429:
                raise HTTPException(
                    status_code=429,
                    detail="Too many password reset requests. Please wait a few minutes and try again."
                )
            else:
                logger.error(f"Supabase recover error: {resp.text}")
                return {"message": "If the email exists, a reset link has been sent."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reset password error: {e}")
        return {"message": "If the email exists, a reset link has been sent."}

# ------------------------------------------------------------------
# Admin: create organisation
# ------------------------------------------------------------------
class CreateOrgRequest(BaseModel):
    org_name: str
    location: str
    niche: str
    budget: int



# ─────────────────────────────────────────────────────────────────
# STOREFRONT CONFIG — schema, defaults, merge
# ─────────────────────────────────────────────────────────────────

DEFAULT_STOREFRONT_CONFIG = {
    "theme": "modern",  # modern | minimal | bold

    "sections": [
        {"type": "hero"},
        {"type": "benefits"},
        {"type": "categories"},
        {"type": "top-picks"},
        {"type": "needs"},
        {"type": "products"},
    ],


    "layout": {
        "product_card": "grid",       # grid | list | editorial | rounded
        "hero":         "split",      # split | minimal | full | centred
        "grid_density": "normal",     # normal | dense | sparse
    },

    "branding": {
        "store_name":    None,       # falls back to org_name
        "tagline":       None,
        "logo_url":      None,
        "favicon_url":   None,
        "primary_color": "#3b82f6",
        "accent_color":  "#f59e0b",
        "background":    "#ffffff",
        "text_color":    "#0f172a",
        "font_family":   "Inter",
    },

    "hero": {
        "enabled":   True,
        "headline":  None,           # falls back to tagline or store_name
        "subtext":   None,
        "image_url": None,
        "overlay":   0.35,           # 0..1 darkness over hero image
        "cta_text":  "Shop now",
        "cta_link":  "#products",
    },

    "about": {
        "enabled": False,
        "title":   "About us",
        "body":    None,
    },

    "contact": {
        "email":    None,
        "phone":    None,
        "whatsapp": None,
        "address":  None,
    },

    "social": {
        "facebook":  None,
        "instagram": None,
        "twitter":   None,
        "tiktok":    None,
    },

    "policies": {
        "returns":  None,
        "shipping": None,
        "privacy":  None,
    },

    "seo": {
        "meta_title":       None,
        "meta_description": None,
    },

    "features": {
        "show_search":       True,
        "show_categories":   True,
        "show_loyalty_cta":  True,
        "show_contact_bar":  True,
    },

    "retail_config": {
        "layout": "grid",            # grid | list
        "items_per_row": 4,          # 2 | 3 | 4
    },

    "food_config": {
        "menu_sections": [
            {"name": "Starters", "order": 1},
            {"name": "Mains",    "order": 2},
            {"name": "Drinks",   "order": 3},
        ],
        "fulfillment_modes": {
            "delivery": {"enabled": True,  "prep_time_minutes": 30, "fee_note": None},
            "pickup":   {"enabled": True,  "prep_time_minutes": 20, "fee_note": "No delivery fee"},
            "dine_in":  {"enabled": False, "prep_time_minutes": 15, "fee_note": None},
        },
        "opening_hours": {
            "mon": {"open": "09:00", "close": "22:00"},
            "tue": {"open": "09:00", "close": "22:00"},
            "wed": {"open": "09:00", "close": "22:00"},
            "thu": {"open": "09:00", "close": "22:00"},
            "fri": {"open": "09:00", "close": "23:00"},
            "sat": {"open": "10:00", "close": "23:00"},
            "sun": {"open": "10:00", "close": "20:00"},
        },
        "accepting_orders":   True,
        "closed_message":     "We're closed right now. Browse the menu and order when we open.",
        "show_spice_level":   False,
        "show_nutrition":     False,
        "delivery_radius_km": None,
        "min_order_naira":    None,
    },
}

def merge_storefront_config(org_config: Optional[dict]) -> dict:
    """
    Deep-merge the org's stored config over the defaults.
    Missing keys come from defaults; partial nested objects keep their defaults.
    """
    result = copy.deepcopy(DEFAULT_STOREFRONT_CONFIG)
    if not org_config:
        return result

    for section, values in org_config.items():
        if (
            section in result
            and isinstance(result[section], dict)
            and isinstance(values, dict)
        ):
            result[section].update(values)
        else:
            result[section] = values
    return result


def validate_org_vertical(vertical: Optional[str]) -> str:
    if vertical not in ("retail", "food", "service"):
        return "retail"
    return vertical











# ─────────────────────────────────────────────────────────────────
# ADMIN: ORGANISATION REGISTRY
# ─────────────────────────────────────────────────────────────────

class AdminCreateOrgRequest(BaseModel):
    org_name: str = Field(..., min_length=2, max_length=200)
    slug: Optional[str] = Field(None, max_length=60)
    vertical: Literal["retail", "food", "service"] = "retail"
    location: str = Field(..., min_length=1, max_length=200)
    niche: str = Field(..., min_length=1, max_length=100)
    budget: int = 0

    # NEW — required, validated against PLAN_TIERS
    plan_tier: str = Field(..., min_length=1, max_length=50)

    # Optional owner — if provided, user is created (or attached) as owner
    owner_email: Optional[str] = Field(None, max_length=200)
    owner_first_name: Optional[str] = Field(None, max_length=100)
    owner_last_name: Optional[str] = Field(None, max_length=100)
    owner_phone: Optional[str] = Field(None, max_length=50)
    owner_password: Optional[str] = Field(None, min_length=8, max_length=100)


class AdminUpdateOrgRequest(BaseModel):
    # Basic identity
    org_name: Optional[str] = Field(None, min_length=2, max_length=200)
    slug:     Optional[str] = Field(None, max_length=60)
    vertical: Optional[Literal["retail", "food", "service"]] = None
    location: Optional[str] = None
    niche:    Optional[str] = None
    budget:   Optional[int] = None

    # Control center fields
    plan_tier:         Optional[str] = None
    status:            Optional[Literal["trial", "active", "suspended", "churned"]] = None
    feature_overrides: Optional[Dict[str, bool]] = None
    limits_overrides:  Optional[Dict[str, Any]] = None
    admin_notes:       Optional[str] = Field(None, max_length=5000)

def _require_admin_key(x_admin_key: Optional[str]) -> None:
    if not x_admin_key or x_admin_key != ADMIN_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

async def _log_admin_action(
    admin_ip: Optional[str],
    org_id: Optional[str],
    action: str,
    from_value: Optional[dict],
    to_value: Optional[dict],
) -> None:
    """
    Append an entry to admin_audit. Best-effort: a failure to write the
    audit row must never fail the underlying operation, but it is logged
    at WARNING so we notice.
    """
    try:
        client = get_admin_supabase()
        payload = {
            "admin_ip":   admin_ip,
            "org_id":     org_id,
            "action":     action,
            "from_value": from_value,
            "to_value":   to_value,
        }
        await run_sync_db_call(
            client.table("admin_audit").insert(payload).execute
        )
    except Exception as e:
        logger.warning(
            "admin_audit write failed",
            action=action, org_id=org_id, error=str(e),
        )



@app.get("/admin/orgs")
async def admin_list_orgs(
    request: Request,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    _require_admin_key(x_admin_key)

    # Admin endpoints use a fresh service-role client per call. Never the
    # cached singleton, because a stray user session on that singleton
    # would silently scope this query to that user's orgs via RLS.
    client = get_admin_supabase()

    # Canary: if this ever logs a session, something upstream is leaking
    # a user JWT onto an admin client. Should always be None.
    try:
        _sess = client.auth.get_session()
        if _sess is not None:
            logger.error(
                "admin_list_orgs: admin client carried a user session — "
                "RLS will scope results. Investigate immediately.",
                session_user=getattr(getattr(_sess, "user", None), "email", None),
            )
    except Exception:
        pass

    res = await run_sync_db_call(
        client.table("organisations")
        .select(
            "id, org_name, slug, vertical, location, niche, budget, "
            "invite_code, storefront_published, created_at, "
            "plan_tier, plan_started_at, plan_renews_at, status, "
            "feature_overrides, limits_overrides, partner_id, admin_notes"
        )
        .order("created_at", desc=True)
        .execute
    )
    orgs = res.data or []

    # Enrich each row with plan metadata, effective features, usage counts,
    # and owner info.
    for org in orgs:
        # ── Plan metadata from the static catalog ──
        tier = PLAN_TIERS.get(org.get("plan_tier") or "", {})
        org["plan_label"]           = tier.get("label")
        org["plan_monthly_naira"]   = tier.get("monthly_naira")
        org["plan_vertical"]        = tier.get("vertical")

        # ── Effective features (merged tier + overrides, status-aware) ──
        org["features"]             = effective_features(org)
        org["has_feature_overrides"] = bool(org.get("feature_overrides"))
        org["has_limit_overrides"]   = bool(org.get("limits_overrides"))

        # ── Live usage counts ──
        # NOTE: per-org COUNT queries. Fine at 5 orgs; replaced by the
        # nightly rollup in Phase 5 when the org count grows.
        org["skus"] = 0
        org["locations"] = 0
        try:
            sku_res = await run_sync_db_call(
                client.table("inventory")
                .select("id", count="exact")
                .eq("org_id", org["id"])
                .limit(1)
                .execute
            )
            org["skus"] = sku_res.count or 0
        except Exception as e:
            logger.warning(f"admin_list_orgs: sku count failed for {org['id']}: {e}")
        try:
            loc_res = await run_sync_db_call(
                client.table("locations")
                .select("id", count="exact")
                .eq("org_id", org["id"])
                .limit(1)
                .execute
            )
            org["locations"] = loc_res.count or 0
        except Exception as e:
            logger.warning(f"admin_list_orgs: location count failed for {org['id']}: {e}")

        # ── Owner + member count ──
        org["member_count"] = 0
        org["owner_email"]  = None
        org["owner_name"]   = None
        try:
            members_res = await run_sync_db_call(
                client.table("org_members")
                .select("user_id, role")
                .eq("org_id", org["id"])
                .execute
            )
            members = members_res.data or []
            org["member_count"] = len(members)

            owner = next((m for m in members if m.get("role") == "owner"), None)
            if owner:
                prof_res = await run_sync_db_call(
                    client.table("profiles")
                    .select("email, first_name, last_name")
                    .eq("id", owner["user_id"])
                    .maybe_single()
                    .execute
                )
                if prof_res and prof_res.data:
                    org["owner_email"] = prof_res.data.get("email")
                    first = prof_res.data.get("first_name") or ""
                    last  = prof_res.data.get("last_name") or ""
                    org["owner_name"] = f"{first} {last}".strip() or None
        except Exception as e:
            logger.warning(f"admin_list_orgs enrichment failed for {org['id']}: {e}")

    return {"organisations": orgs}

@app.get("/admin/orgs/stats")
async def admin_org_stats(
    request: Request,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    _require_admin_key(x_admin_key)

    # Admin client: fresh service-role client per call. This endpoint
    # counts every org and every membership platform-wide, so RLS must
    # not scope either query to any single user's view. Under the old
    # polluted singleton, these counts silently matched one user's
    # memberships instead of the whole platform.
    client = get_admin_supabase()

    orgs_res = await run_sync_db_call(
        client.table("organisations").select("id, vertical, storefront_published").execute
    )
    orgs = orgs_res.data or []

    members_res = await run_sync_db_call(
        client.table("org_members").select("user_id").execute
    )
    members = members_res.data or []

    return {
        "total_orgs":       len(orgs),
        "published_orgs":   sum(1 for o in orgs if o.get("storefront_published")),
        "by_vertical": {
            "retail":  sum(1 for o in orgs if o.get("vertical") == "retail"),
            "food":    sum(1 for o in orgs if o.get("vertical") == "food"),
            "service": sum(1 for o in orgs if o.get("vertical") == "service"),
        },
        "total_users": len(members),
    }



@app.get("/admin/orgs/{org_id}")
async def admin_get_org(
    request: Request,
    org_id: str,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    _require_admin_key(x_admin_key)
    client = get_admin_supabase()

    res = await run_sync_db_call(
        client.table("organisations")
        .select("*")
        .eq("id", org_id)
        .maybe_single()
        .execute
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Organisation not found")

    org = res.data

    tier = PLAN_TIERS.get(org.get("plan_tier") or "", {})
    org["plan_definition"] = tier
    org["features"]        = effective_features(org)

    # Live usage counts for the drawer
    try:
        sku_res = await run_sync_db_call(
            client.table("inventory").select("id", count="exact")
            .eq("org_id", org_id).limit(1).execute
        )
        org["skus"] = sku_res.count or 0
    except Exception:
        org["skus"] = 0

    try:
        loc_res = await run_sync_db_call(
            client.table("locations").select("id", count="exact")
            .eq("org_id", org_id).limit(1).execute
        )
        org["locations"] = loc_res.count or 0
    except Exception:
        org["locations"] = 0

    try:
        mem_res = await run_sync_db_call(
            client.table("org_members").select("user_id", count="exact")
            .eq("org_id", org_id).limit(1).execute
        )
        org["member_count"] = mem_res.count or 0
    except Exception:
        org["member_count"] = 0

    return {"organisation": org}

@app.get("/admin/plans")
async def admin_list_plans(
    request: Request,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    _require_admin_key(x_admin_key)

    return {
        "plans": [
            {"key": key, **tier}
            for key, tier in PLAN_TIERS.items()
        ],
        "features": FEATURE_CATALOG,
        "metrics":  METRIC_CATALOG,
    }


@app.get("/admin/audit")
async def admin_audit_log(
    request: Request,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
    org_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    await rate_limit(get_client_ip(request))
    _require_admin_key(x_admin_key)
    client = get_admin_supabase()

    query = client.table("admin_audit").select("*", count="exact")
    if org_id:
        query = query.eq("org_id", org_id)
    res = await run_sync_db_call(
        query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute
    )
    return {
        "entries": res.data or [],
        "total":   res.count or 0,
        "limit":   limit,
        "offset":  offset,
    }



async def _create_or_attach_owner(
    org_id: str,
    email: str,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    password: Optional[str] = None,
) -> Dict:
    """
    Attach a user as owner of the given org.
    - If a profile with this email exists, uses that user.
    - Otherwise creates the user via Supabase admin auth API + profile row.
    - Then upserts org_members with role='owner'.
    - Stamps JWT metadata.
    Returns { user_id, email, created, temporary_password }.

    NOTE: this is a helper, not an endpoint. The @app.post("/admin/orgs")
    decorator that used to be attached here has been moved to its rightful
    owner, admin_create_org. This function is only ever called from there.
    """
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=500, detail="Service role key required to create users")

    # Admin client: fresh service-role client, built per call. Never carries
    # a session, always bypasses RLS, so the profile lookup and org_members
    # upsert see the whole table regardless of who last logged in.
    client = get_admin_supabase()

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    # 1. Try to find existing profile
    prof_res = await run_sync_db_call(
        client.table("profiles").select("id").eq("email", email).maybe_single().execute
    )

    created = False
    temp_password: Optional[str] = None
    user_id: Optional[str] = None

    if prof_res and prof_res.data:
        user_id = prof_res.data["id"]
    else:
        # 2. Create the auth user
        temp_password = password or ''.join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(12)
        )
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                f"{SUPABASE_URL}/auth/v1/admin/users",
                json={
                    "email": email,
                    "password": temp_password,
                    "email_confirm": True,
                    "user_metadata": {
                        "first_name": first_name,
                        "last_name": last_name,
                        "phone": phone,
                    },
                },
                headers=headers,
            )
        if resp.status_code not in (200, 201):
            raise HTTPException(status_code=500, detail=f"Failed to create user: {resp.text}")

        user_id = resp.json().get("id")
        if not user_id:
            raise HTTPException(status_code=500, detail="Auth user created but no id returned")
        created = True

        # 3. Create the profile row
        async with httpx.AsyncClient(timeout=15.0) as http:
            prof_resp = await http.post(
                f"{SUPABASE_URL}/rest/v1/profiles",
                json={
                    "id": user_id,
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "phone": phone,
                    "membership_id": f"MEM-{user_id[:8]}",
                    "status": "active",
                    "current_points": 0,
                    "tier": "bronze",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                headers=headers,
            )
        if prof_resp.status_code not in (200, 201):
            # Roll back the auth user so we don't leave an orphan
            async with httpx.AsyncClient(timeout=10.0) as http:
                await http.delete(f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=headers)
            raise HTTPException(status_code=500, detail=f"Failed to create profile: {prof_resp.text}")

    # 4. Upsert org_members as owner
    existing = await run_sync_db_call(
        client.table("org_members")
        .select("user_id, role")
        .eq("user_id", user_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if existing and existing.data:
        if existing.data.get("role") != "owner":
            await run_sync_db_call(
                client.table("org_members")
                .update({"role": "owner"})
                .eq("user_id", user_id)
                .eq("org_id", org_id)
                .execute
            )
    else:
        await run_sync_db_call(
            client.table("org_members").insert({
                "user_id": user_id,
                "org_id": org_id,
                "role": "owner",
                "joined_at": datetime.now(timezone.utc).isoformat(),
            }).execute
        )

    # 5. Stamp app_metadata so the JWT carries org + role
    await _admin_set_app_metadata(user_id, {
        "org_id": org_id,
        "role": "owner",
        "branch_scope": None,
    })

    return {
        "user_id": user_id,
        "email": email,
        "created": created,
        "temporary_password": temp_password,
    }
    
@app.post("/admin/orgs")
async def admin_create_org(
    request: Request,
    req: AdminCreateOrgRequest,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    _require_admin_key(x_admin_key)

    # Admin client: fresh service-role client per call, never a cached
    # singleton that could carry a user session. Every read and write in
    # this handler (slug clash check, org insert, warehouse seed) needs
    # to see the whole table — RLS must not scope any of it.
    client = get_admin_supabase()

    # ── Slug resolution ──
    if req.slug and req.slug.strip():
        candidate = slugify(req.slug)
        if not candidate:
            raise HTTPException(status_code=400, detail="Invalid slug — use letters, numbers, and dashes")
        if candidate in RESERVED_SLUGS:
            raise HTTPException(status_code=400, detail=f"'{candidate}' is a reserved slug")
        clash = await run_sync_db_call(
            client.table("organisations").select("id").eq("slug", candidate).limit(1).execute
        )
        if clash.data:
            raise HTTPException(status_code=409, detail=f"Slug '{candidate}' is already taken")
    else:
        candidate = await generate_unique_slug(req.org_name)

    # ── Plan tier validation ──
    if req.plan_tier not in PLAN_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown plan_tier '{req.plan_tier}'. "
                   f"Valid: {sorted(PLAN_TIERS.keys())}",
        )

    tier_def = PLAN_TIERS[req.plan_tier]
    if tier_def.get("vertical") != req.vertical:
        raise HTTPException(
            status_code=400,
            detail=f"Plan '{req.plan_tier}' is for vertical '{tier_def.get('vertical')}', "
                   f"but org vertical is '{req.vertical}'.",
        )

    invite_code = await generate_invite_code()

    insert_payload = {
        "org_name":             req.org_name,
        "slug":                 candidate,
        "vertical":             req.vertical,
        "location":             req.location,
        "niche":                req.niche,
        "budget":               req.budget,
        "invite_code":          invite_code,
        "storefront_config":    {},
        "storefront_published": False,
        "plan_tier":            req.plan_tier,
        "plan_started_at":      datetime.now(timezone.utc).isoformat(),
        "plan_renews_at":       (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "status":               "active",
        "created_at":           datetime.now(timezone.utc).isoformat(),
        "payment_gateway_config": {"provider": "paystack", "credentials": {}},
    }

    result = await run_sync_db_call(
        client.table("organisations").insert(insert_payload).execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create organisation")

    org = result.data[0]

    # ── Seed the default branch + warehouse so inventory has a home ──
    try:
        seeded_branch_id = await ensure_default_branch(org["id"])
        now_iso = datetime.now(timezone.utc).isoformat()
        await run_sync_db_call(
            client.table("locations").insert({
                "org_id":       org["id"],
                "name":         "Main Warehouse",
                "address":      req.location,
                "branch_id":    seeded_branch_id,
                "type":         "warehouse",
                "is_warehouse": True,
                "is_active":    True,
                "created_at":   now_iso,
                "updated_at":   now_iso,
            }).execute
        )
        logger.info(
            "Seeded MAIN branch + warehouse",
            org_id=org["id"], branch_id=seeded_branch_id,
        )
    except Exception as e:
        logger.warning(f"Failed to seed branch/warehouse for org {org['id']}: {e}")

    # ── Create or attach the first owner ──
    owner_info = None
    if req.owner_email:
        try:
            owner_info = await _create_or_attach_owner(
                org_id=org["id"],
                email=req.owner_email,
                first_name=req.owner_first_name or "",
                last_name=req.owner_last_name or "",
                phone=req.owner_phone or "",
                password=req.owner_password,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Owner creation failed for org {org['id']}: {e}", exc_info=True)
            # Don't fail the whole org creation if only the owner step failed
            owner_info = {"error": str(e)}

    # ── Notify the owner with credentials if we created them ──
    if owner_info and owner_info.get("temporary_password"):
        try:
            login_link = f"{PRODUCTION_HOST}/kdsiginin"
            html = f"""
            <h2>Welcome to {escape_html(req.org_name)}</h2>
            <p>You have been set up as an <strong>owner</strong> of {escape_html(req.org_name)} on Kevs Digital bOS.</p>
            <p><strong>Email:</strong> {req.owner_email}<br>
               <strong>Temporary password:</strong> <code>{owner_info['temporary_password']}</code></p>
            <p>Sign in here: <a href="{login_link}">{login_link}</a></p>
            <p>Change your password immediately after signing in.</p>
            """
            await send_sendgrid_email(req.owner_email, f"Your {req.org_name} owner account", html)
        except Exception as e:
            logger.warning(f"Owner invite email failed: {e}")

    return {
        "org_id":         org["id"],
        "org_name":       org["org_name"],
        "slug":           candidate,
        "vertical":       req.vertical,
        "invite_code":    invite_code,
        "storefront_url": f"{PRODUCTION_HOST}/store/{candidate}",
        "published":      False,
        "owner":          owner_info,
    }


@app.patch("/admin/orgs/{org_id}")
async def admin_update_org(
    request: Request,
    org_id: str,
    req: AdminUpdateOrgRequest,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    _require_admin_key(x_admin_key)

    # Admin client: fresh service-role client per call. The slug clash
    # check must see every org in the table.
    client = get_admin_supabase()

    # 1. Load current state — we need it for the audit diff.
    current_res = await run_sync_db_call(
        client.table("organisations")
        .select(
            "id, org_name, slug, vertical, location, niche, budget, "
            "plan_tier, status, feature_overrides, limits_overrides, admin_notes"
        )
        .eq("id", org_id)
        .maybe_single()
        .execute
    )
    if not current_res or not current_res.data:
        raise HTTPException(status_code=404, detail="Organisation not found")
    current = current_res.data

    # 2. Build the update dict from explicitly-provided fields only.
    update = {
        k: v for k, v in req.dict(exclude_unset=True).items()
        if v is not None
    }
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")

    # 3. Validate the fields that need validation.

    # 3a. Slug — normalise and check collision
    if "slug" in update:
        new_slug = slugify(update["slug"])
        if not new_slug:
            raise HTTPException(status_code=400, detail="Invalid slug")
        if new_slug in RESERVED_SLUGS:
            raise HTTPException(status_code=400, detail=f"'{new_slug}' is a reserved slug")
        clash = await run_sync_db_call(
            client.table("organisations")
            .select("id").eq("slug", new_slug).neq("id", org_id).limit(1).execute
        )
        if clash.data:
            raise HTTPException(status_code=409, detail=f"Slug '{new_slug}' is already taken")
        update["slug"] = new_slug

    # 3b. Plan tier — must be a known catalog key
    if "plan_tier" in update:
        if update["plan_tier"] not in PLAN_TIERS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown plan_tier '{update['plan_tier']}'. "
                       f"Valid keys: {sorted(PLAN_TIERS.keys())}",
            )

    # 3c. Feature overrides — keys must be known features, values boolean
    if "feature_overrides" in update:
        fo = update["feature_overrides"]
        if not isinstance(fo, dict):
            raise HTTPException(status_code=400, detail="feature_overrides must be an object")
        unknown = set(fo.keys()) - set(FEATURE_CATALOG.keys())
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown feature keys: {sorted(unknown)}",
            )
        for k, v in fo.items():
            if not isinstance(v, bool):
                raise HTTPException(
                    status_code=400,
                    detail=f"feature_overrides['{k}'] must be true or false",
                )

    # 3d. Limits overrides — values must be int or null
    if "limits_overrides" in update:
        lo = update["limits_overrides"]
        if not isinstance(lo, dict):
            raise HTTPException(status_code=400, detail="limits_overrides must be an object")
        for k, v in lo.items():
            if v is not None and not isinstance(v, int):
                raise HTTPException(
                    status_code=400,
                    detail=f"limits_overrides['{k}'] must be an integer or null",
                )

    # 4. Apply
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = await run_sync_db_call(
        client.table("organisations").update(update).eq("id", org_id).execute
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Update failed")

    # 5. Audit — one row per logical change group
    admin_ip = get_client_ip(request)

    # Split the update into logical actions so the audit log is readable.
    basic_keys   = {"org_name", "slug", "vertical", "location", "niche", "budget"}
    basic_diff   = {k: update[k] for k in basic_keys if k in update}
    if basic_diff:
        from_subset = {k: current.get(k) for k in basic_diff}
        await _log_admin_action(
            admin_ip, org_id, "org.update_basic",
            from_value=from_subset, to_value=basic_diff,
        )

    if "plan_tier" in update and update["plan_tier"] != current.get("plan_tier"):
        await _log_admin_action(
            admin_ip, org_id, "plan.change",
            from_value={"plan_tier": current.get("plan_tier")},
            to_value={"plan_tier":   update["plan_tier"]},
        )

    if "status" in update and update["status"] != current.get("status"):
        await _log_admin_action(
            admin_ip, org_id, "status.change",
            from_value={"status": current.get("status")},
            to_value={"status":   update["status"]},
        )

    if "feature_overrides" in update:
        await _log_admin_action(
            admin_ip, org_id, "features.override",
            from_value={"feature_overrides": current.get("feature_overrides") or {}},
            to_value={"feature_overrides": update["feature_overrides"]},
        )

    if "limits_overrides" in update:
        await _log_admin_action(
            admin_ip, org_id, "limits.override",
            from_value={"limits_overrides": current.get("limits_overrides") or {}},
            to_value={"limits_overrides": update["limits_overrides"]},
        )

    if "admin_notes" in update:
        await _log_admin_action(
            admin_ip, org_id, "notes.update",
            from_value=None,   # notes may be long; don't store the old
            to_value={"admin_notes": update["admin_notes"]},
        )

    return {"organisation": res.data[0]}


@app.post("/admin/orgs/{org_id}/suspend")
async def admin_suspend_org(
    request: Request,
    org_id: str,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    _require_admin_key(x_admin_key)
    client = get_admin_supabase()

    current = await run_sync_db_call(
        client.table("organisations").select("status")
        .eq("id", org_id).maybe_single().execute
    )
    if not current or not current.data:
        raise HTTPException(status_code=404, detail="Organisation not found")
    old_status = current.data.get("status") or "active"
    if old_status == "suspended":
        return {"status": "suspended", "organisation": current.data}

    await run_sync_db_call(
        client.table("organisations").update({
            "status": "suspended",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", org_id).execute
    )
    await _log_admin_action(
        get_client_ip(request), org_id, "status.suspend",
        from_value={"status": old_status},
        to_value={"status": "suspended"},
    )
    return {"status": "suspended"}


@app.post("/admin/orgs/{org_id}/reactivate")
async def admin_reactivate_org(
    request: Request,
    org_id: str,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    _require_admin_key(x_admin_key)
    client = get_admin_supabase()

    current = await run_sync_db_call(
        client.table("organisations").select("status")
        .eq("id", org_id).maybe_single().execute
    )
    if not current or not current.data:
        raise HTTPException(status_code=404, detail="Organisation not found")
    old_status = current.data.get("status") or "active"
    if old_status == "active":
        return {"status": "active"}

    await run_sync_db_call(
        client.table("organisations").update({
            "status": "active",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", org_id).execute
    )
    await _log_admin_action(
        get_client_ip(request), org_id, "status.reactivate",
        from_value={"status": old_status},
        to_value={"status": "active"},
    )
    return {"status": "active"}






@app.post("/admin/orgs/{org_id}/publish")
async def admin_publish_org(
    request: Request,
    org_id: str,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    _require_admin_key(x_admin_key)
    body = await request.json()
    publish = bool(body.get("published", True))

    # Admin client: fresh service-role client per call. The publish flip
    # must update any org in the table, not just ones the last logged-in
    # user belongs to.
    client = get_admin_supabase()

    res = await run_sync_db_call(
        client.table("organisations")
        .update({
            "storefront_published": publish,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", org_id)
        .execute
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return {"published": publish, "organisation": res.data[0]}
    
@app.post("/admin/orgs/{org_id}/regenerate-invite")
async def admin_regenerate_invite(
    request: Request,
    org_id: str,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    _require_admin_key(x_admin_key)
    new_code = await generate_invite_code()

    # Admin client: fresh service-role client per call. The invite-code
    # update must touch any org in the table.
    client = get_admin_supabase()

    res = await run_sync_db_call(
        client.table("organisations")
        .update({
            "invite_code": new_code,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", org_id)
        .execute
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return {"invite_code": new_code}



# ─────────────────────────────────────────────────────────────────
# STOREFRONT — public read
# ─────────────────────────────────────────────────────────────────

@app.get("/public/storefront/{slug}")
async def get_public_storefront(slug: str, request: Request):
    await rate_limit(get_client_ip(request))

    client = get_supabase()
    res = await run_sync_db_call(
        client.table("organisations")
        .select(
            "id, org_name, slug, vertical, location, niche, "
            "storefront_config, storefront_published"
        )
        .eq("slug", slug)
        .maybe_single()
        .execute
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Store not found")

    org = res.data

    # Feature gate: ecommerce
    await check_org_feature(org["id"], "ecommerce")

    if not org.get("storefront_published"):
        raise HTTPException(status_code=404, detail="Store is not yet live")

    config = merge_storefront_config(org.get("storefront_config"))

    if not config["branding"]["store_name"]:
        config["branding"]["store_name"] = org["org_name"]
    if not config["seo"]["meta_title"]:
        config["seo"]["meta_title"] = config["branding"]["store_name"]
    if not config["hero"]["headline"]:
        config["hero"]["headline"] = config["branding"]["tagline"] or config["branding"]["store_name"]

    return {
        "org_id":   org["id"],
        "slug":     org["slug"],
        "org_name": org["org_name"],
        "vertical": validate_org_vertical(org.get("vertical")),
        "config":   config,
    }

# ─────────────────────────────────────────────────────────────────
# STOREFRONT — owner read / write
# ─────────────────────────────────────────────────────────────────

class StorefrontConfigUpdate(BaseModel):
    theme:          Optional[str]  = None
    sections:       Optional[List[dict]] = None      # ← ADD
    layout:         Optional[dict] = None
    branding:       Optional[dict] = None
    hero:           Optional[dict] = None
    about:          Optional[dict] = None
    contact:        Optional[dict] = None
    social:         Optional[dict] = None
    policies:       Optional[dict] = None
    seo:            Optional[dict] = None
    features:       Optional[dict] = None
    retail_config:  Optional[dict] = None
    food_config:    Optional[dict] = None


# Sections that must be objects, not strings or scalars.
_CONFIG_SECTIONS = (
    "layout",
    "branding", "hero", "about", "contact", "social",
    "policies", "seo", "features", "retail_config", "food_config",
)


@app.get("/storefront/config")
async def get_own_storefront_config(
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"])),
):
    _, org_id, _ = user_data
    client = get_supabase()

    res = await run_sync_db_call(
        client.table("organisations")
        .select("org_name, slug, vertical, storefront_config, storefront_published")
        .eq("id", org_id)
        .maybe_single()
        .execute
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Organisation not found")

    org = res.data
    config = merge_storefront_config(org.get("storefront_config"))
    if not config["branding"]["store_name"]:
        config["branding"]["store_name"] = org["org_name"]

    return {
        "org_name":  org["org_name"],
        "slug":      org["slug"],
        "vertical":  validate_org_vertical(org.get("vertical")),
        "published": org.get("storefront_published", False),
        "config":    config,
    }


@app.patch("/storefront/config")
async def update_own_storefront_config(
    update: StorefrontConfigUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"])),
):
    _, org_id, _ = user_data
    client = get_supabase()

    res = await run_sync_db_call(
        client.table("organisations")
        .select("storefront_config")
        .eq("id", org_id)
        .maybe_single()
        .execute
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Organisation not found")

    current = res.data.get("storefront_config") or {}

    patch = {k: v for k, v in update.dict(exclude_unset=True).items() if v is not None}

    # Every config section must be an object. A stray string would clobber
    # the whole section and break the renderer on the next request.
    for section in _CONFIG_SECTIONS:
        if section in patch and not isinstance(patch[section], dict):
            raise HTTPException(
                status_code=400,
                detail=f"'{section}' must be an object, got {type(patch[section]).__name__}",
            )

    # Theme whitelist
    if "theme" in patch and patch["theme"] not in ("modern", "minimal", "bold", "warm"):
        raise HTTPException(status_code=400, detail="Unknown theme")

    # Layout whitelist
    if "layout" in patch and patch["layout"]:
        if not isinstance(patch["layout"], dict):
            raise HTTPException(status_code=400, detail="'layout' must be an object")

        ALLOWED_CARDS  = {"grid", "list", "editorial", "rounded"}
        ALLOWED_HEROES = {"split", "minimal", "full", "centred"}
        ALLOWED_DENS   = {"normal", "dense", "sparse"}

        pc = patch["layout"].get("product_card")
        if pc and pc not in ALLOWED_CARDS:
            raise HTTPException(status_code=400, detail=f"Unknown product_card: {pc}")
        h = patch["layout"].get("hero")
        if h and h not in ALLOWED_HEROES:
            raise HTTPException(status_code=400, detail=f"Unknown hero: {h}")
        gd = patch["layout"].get("grid_density")
        if gd and gd not in ALLOWED_DENS:
            raise HTTPException(status_code=400, detail=f"Unknown grid_density: {gd}")

    # Colour sanity — must look like #rrggbb
    if "branding" in patch:
        for key in ("primary_color", "accent_color", "background", "text_color"):
            val = patch["branding"].get(key)
            if val and not re.match(r'^#[0-9a-fA-F]{6}$', val):
                raise HTTPException(status_code=400, detail=f"Invalid colour for {key}")

    # Food config: validate fulfillment modes
    if "food_config" in patch and patch["food_config"]:
        fm = patch["food_config"].get("fulfillment_modes")
        if fm and isinstance(fm, dict):
            for mode_name, mode_cfg in fm.items():
                if mode_name not in ("delivery", "pickup", "dine_in"):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unknown fulfillment mode: {mode_name}",
                    )
                if isinstance(mode_cfg, dict) and "prep_time_minutes" in mode_cfg:
                    try:
                        p = int(mode_cfg["prep_time_minutes"])
                    except (TypeError, ValueError):
                        raise HTTPException(
                            status_code=400,
                            detail="prep_time_minutes must be an integer 0–300",
                        )
                    if p < 0 or p > 300:
                        raise HTTPException(
                            status_code=400,
                            detail="prep_time_minutes must be 0–300",
                        )

    # Sections validation — order + type whitelist
    if "sections" in patch and patch["sections"] is not None:
        if not isinstance(patch["sections"], list):
            raise HTTPException(status_code=400, detail="'sections' must be an array")

        ALLOWED_SECTION_TYPES = {
            "hero", "benefits", "categories", "top-picks",
            "needs", "products", "about", "cta",
        }
        for i, sec in enumerate(patch["sections"]):
            if not isinstance(sec, dict):
                raise HTTPException(status_code=400, detail=f"sections[{i}] must be an object")
            t = sec.get("type")
            if not t or t not in ALLOWED_SECTION_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"sections[{i}].type must be one of: {sorted(ALLOWED_SECTION_TYPES)}",
                )

    # Deep-merge the patch into the stored config
    for section, values in patch.items():
        if (
            section in current
            and isinstance(current[section], dict)
            and isinstance(values, dict)
        ):
            current[section].update(values)
        else:
            current[section] = values

    write_res = await run_sync_db_call(
        client.table("organisations")
        .update({
            "storefront_config": current,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", org_id)
        .execute
    )
    if not write_res.data:
        raise HTTPException(status_code=500, detail="Failed to save config")

    return {"config": merge_storefront_config(current)}
    
@app.post("/storefront/publish")
async def publish_own_storefront(
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"])),
):
    _, org_id, _ = user_data
    client = get_supabase()

    res = await run_sync_db_call(
        client.table("organisations")
        .select("slug, storefront_config")
        .eq("id", org_id)
        .maybe_single()
        .execute
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Organisation not found")

    org = res.data
    if not org.get("slug"):
        raise HTTPException(status_code=400, detail="Set a URL slug before publishing")

    cfg = merge_storefront_config(org.get("storefront_config"))

    # Minimum content check — the storefront should not be blank.
    if not cfg["branding"].get("logo_url") and not cfg["hero"].get("image_url"):
        raise HTTPException(
            status_code=400,
            detail="Upload a logo or a hero image before publishing.",
        )

    pub_res = await run_sync_db_call(
        client.table("organisations")
        .update({
            "storefront_published": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", org_id)
        .execute
    )
    if not pub_res.data:
        raise HTTPException(status_code=500, detail="Failed to publish")

    return {
        "published": True,
        "slug":      org["slug"],
        "url":       f"{PRODUCTION_HOST}/store/{org['slug']}",
    }


@app.post("/storefront/unpublish")
async def unpublish_own_storefront(
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"])),
):
    _, org_id, _ = user_data
    res = await run_sync_db_call(
        get_supabase().table("organisations")
        .update({
            "storefront_published": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", org_id)
        .execute
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to unpublish")
    return {"published": False}


# ─────────────────────────────────────────────────────────────────
# STOREFRONT — image upload
# ─────────────────────────────────────────────────────────────────

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "svg"}


@app.post("/storefront/upload")
async def upload_storefront_asset(
    file: UploadFile = File(...),
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"])),
):
    _, org_id, _ = user_data

    contents = await file.read()
    if len(contents) > 3 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image must be under 3MB")

    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(
            status_code=400,
            detail="Unsupported format. Use PNG, JPG, WEBP, or SVG.",
        )

    mime = {
        "png":  "image/png",
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "svg":  "image/svg+xml",
    }[ext]

    path = f"{org_id}/{uuid.uuid4().hex}.{ext}"
    client = get_supabase()

    try:
        await run_sync_db_call(
            client.storage.from_("storefront").upload,
            path,
            contents,
            {"content-type": mime, "upsert": "false"},
        )
    except Exception as e:
        logger.error(f"Storage upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    public_url = client.storage.from_("storefront").get_public_url(path)
    return {"url": public_url, "path": path}



# ─────────────────────────────────────────────────────────────────
# STOREFRONT — guest checkout
# ─────────────────────────────────────────────────────────────────

class PublicCartItem(BaseModel):
    inventory_id: int
    quantity: int = Field(..., gt=0)
    notes: Optional[str] = Field(None, max_length=300)


class PublicCheckoutRequest(BaseModel):
    org_id: Optional[str] = None       # ← was: str
    items: List[PublicCartItem] = Field(..., min_length=1)
    customer_name: str = Field(..., min_length=1, max_length=200)
    customer_email: Optional[str] = None
    customer_phone: str = Field(..., min_length=1, max_length=50)
    fulfillment_mode: str = "delivery"
    shipping_address: Optional[str] = Field(None, max_length=500)
    delivery_fee: float = 0.0
    handling_fee: float = 0.0
    notes: Optional[str] = Field(None, max_length=500)
    callback_url: Optional[str] = None

@app.post("/public/checkout")
async def public_storefront_checkout(
    request: Request,
    req: PublicCheckoutRequest,
):
    await rate_limit(get_client_ip(request))

    # Fall back to the public store org when the storefront didn't pass one.
    resolved_org_id = req.org_id or PUBLIC_STORE_ORG_ID
    if not resolved_org_id:
        raise HTTPException(status_code=400, detail="Organisation not specified")

    if req.fulfillment_mode not in ("delivery", "pickup", "dine_in"):
        raise HTTPException(status_code=400, detail="Invalid fulfillment_mode")
    if req.fulfillment_mode == "delivery" and not (req.shipping_address or "").strip():
        raise HTTPException(status_code=400, detail="Delivery address is required")

    # Feature gate: ecommerce (guest checkout is an ecommerce feature)
    await check_org_feature(resolved_org_id, "ecommerce")

    client = get_supabase()
    org_res = await run_sync_db_call(
        client.table("organisations")
        .select(
            "id, org_name, slug, vertical, storefront_published, "
            "payment_gateway_config, subaccount_code"
        )
        .eq("id", resolved_org_id)     # ← use resolved_org_id
        .maybe_single()
        .execute
    )
    # ... rest of the handler stays exactly as it is, using resolved_org_id everywhere


    if not org_res or not org_res.data:
        raise HTTPException(status_code=404, detail="Organisation not found")
    org = org_res.data
    if not org.get("storefront_published"):
        raise HTTPException(status_code=404, detail="Store is not accepting orders")

    ids = [item.inventory_id for item in req.items]
    inv_res = await run_sync_db_call(
        client.table("inventory")
        .select("id, description, item_code, price_naira")
        .eq("org_id", org["id"])
        .in_("id", ids)
        .execute
    )
    inv_map = {p["id"]: p for p in (inv_res.data or [])}

    sale_items = []
    product_total = 0.0
    for item in req.items:
        prod = inv_map.get(item.inventory_id)
        if not prod:
            raise HTTPException(status_code=400, detail=f"Product {item.inventory_id} not available")
        unit_price = float(prod.get("price_naira") or 0)
        subtotal = unit_price * item.quantity
        product_total += subtotal
        sale_items.append({
            "inventory_id": item.inventory_id,
            "product_name": prod.get("description") or "",
            "quantity": item.quantity,
            "unit_price": unit_price,
            "subtotal": subtotal,
        })

    total = product_total + float(req.delivery_fee or 0) + float(req.handling_fee or 0)

    receipt_num  = f"WEB-{org['id'][:4]}-{uuid.uuid4().hex[:8].upper()}"
    payment_ref  = str(uuid.uuid4())

    online_location_id = await get_location_for_channel(org["id"], "online")
    branch_id_for_sale = await resolve_branch_for_write(org["id"])

    sale_data = {
        "org_id":              org["id"],
        "branch_id":           branch_id_for_sale,
        "location_id":         online_location_id,
        "user_id":             None,
        "total_amount":        total,
        "payment_method":      "paystack",
        "payment_reference":   payment_ref,
        "status":              "pending",
        "customer_name":       req.customer_name,
        "customer_phone":      req.customer_phone,
        "customer_email":      req.customer_email,
        "receipt_number":      receipt_num,
        "shipping_address":    req.shipping_address,
        "delivery_fee":        float(req.delivery_fee or 0),
        "handling_fee":        float(req.handling_fee or 0),
        "fulfillment_mode":    req.fulfillment_mode,
        "fulfillment_notes":   req.notes,
        "shipping_status":     "processing",
        "created_at":          datetime.now(timezone.utc).isoformat(),
    }

    sale_res = await run_sync_db_call(client.table("sales").insert(sale_data).execute)
    if not sale_res.data:
        raise HTTPException(status_code=500, detail="Failed to create order")
    sale_id = sale_res.data[0]["id"]

    if sale_items:
        for si in sale_items:
            si["sale_id"] = sale_id
        await run_sync_db_call(client.table("sale_items").insert(sale_items).execute)

    gateway_config = org.get("payment_gateway_config") or {"provider": "paystack", "credentials": {}}
    gateway = get_payment_gateway_from_config(gateway_config)

    email_for_gateway = req.customer_email or f"guest_{payment_ref[:8]}@example.com"
    callback = req.callback_url or f"{PRODUCTION_HOST}/store/{org['slug']}?receipt={receipt_num}&email={email_for_gateway}"

    try:
        payment_data = await gateway.initialize_transaction(
            email=email_for_gateway,
            amount_naira=total,
            reference=payment_ref,
            metadata={
                "sale_id": str(sale_id),
                "org_id":  str(org["id"]),
                "receipt": receipt_num,
                "source":  "storefront",
            },
            subaccount_code=org.get("subaccount_code"),
            callback_url=callback,
        )
    except Exception as e:
        logger.error(f"Storefront gateway init failed: {e}")
        await run_sync_db_call(
            client.table("sales")
            .update({"status": "cancelled", "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", sale_id)
            .execute
        )
        raise HTTPException(status_code=400, detail=f"Payment initialization failed: {e}")

    return {
        "sale_id":        str(sale_id),
        "receipt_number": receipt_num,
        "total":          total,
        "payment_url":    payment_data["payment_url"],
        "reference":      payment_ref,
    }


@app.get("/public/order-status/{receipt_number}")
async def public_order_status(
    receipt_number: str,
    request: Request,
    email: Optional[str] = Query(None),
):
    """Public order lookup by receipt number. If email is provided it must match."""
    await rate_limit(get_client_ip(request))
    client = get_supabase()

    q = client.table("sales").select(
        "receipt_number, status, shipping_status, total_amount, "
        "customer_name, customer_email, created_at, "
        "tracking_number, shipping_carrier, estimated_delivery, "
        "fulfillment_mode, shipping_address"
    ).eq("receipt_number", receipt_number)
    if email:
        q = q.eq("customer_email", email)

    res = await run_sync_db_call(q.maybe_single().execute)
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Order not found")

    order = res.data
    return {
        "receipt_number":  order["receipt_number"],
        "status":          order["status"],
        "shipping_status": order.get("shipping_status"),
        "total_amount":    order.get("total_amount"),
        "customer_name":   order.get("customer_name"),
        "fulfillment_mode": order.get("fulfillment_mode"),
        "shipping_address": order.get("shipping_address"),
        "tracking_number":  order.get("tracking_number"),
        "shipping_carrier": order.get("shipping_carrier"),
        "estimated_delivery": order.get("estimated_delivery"),
        "created_at":      order.get("created_at"),
    }





@app.get("/public/org-info")
async def org_info(request: Request, invite_code: str):
    await rate_limit(get_client_ip(request))
    client = get_supabase()
    result = await run_sync_db_call(client.table("organisations").select("org_name").eq("invite_code", invite_code).maybe_single().execute)
    if not result or not result.data:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return {"org_name": result.data["org_name"]}

# ------------------------------------------------------------------
# KNOWLEDGE BASE MANAGEMENT
# ------------------------------------------------------------------
@app.get("/admin/knowledge")
async def list_knowledge(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("general_knowledge")
        .select("id, title, category, content, keywords, created_at")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .execute
    )
    return {"items": result.data}

@app.post("/admin/knowledge")
async def create_knowledge(
    request: Request,
    kb: KnowledgeBaseCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data

    validate_knowledge_content(kb.content, kb.title)
    embedding = get_embedding(kb.content)

    client = get_supabase()
    data = {
        "org_id": org_id,
        "title": kb.title,
        "category": kb.category,
        "content": kb.content,
        "keywords": kb.keywords,
        "embedding": embedding,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    result = await run_sync_db_call(client.table("general_knowledge").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create knowledge entry")

    doc_id = result.data[0]["id"]
    try:
        await run_sync_db_call(
            client.table("knowledge_audit").insert({
                "doc_id": doc_id,
                "org_id": org_id,
                "user_id": user_id,
                "action": "create",
                "new_content": kb.content[:500]
            }).execute
        )
    except Exception as audit_err:
        logger.warning(f"Audit log failed: {audit_err}")

    return result.data[0]

@app.put("/admin/knowledge/{doc_id}")
async def update_knowledge(
    request: Request,
    doc_id: int,
    kb: KnowledgeBaseUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    existing = await run_sync_db_call(
        client.table("general_knowledge")
        .select("content, title")
        .eq("id", doc_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Document not found")

    update_data = {k: v for k, v in kb.dict().items() if v is not None}
    if "content" in update_data:
        title = update_data.get("title", existing.data.get("title", ""))
        validate_knowledge_content(update_data["content"], title)
        embedding = get_embedding(update_data["content"])
        if embedding:
            update_data["embedding"] = embedding

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(
        client.table("general_knowledge")
        .update(update_data)
        .eq("id", doc_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Update failed")

    try:
        await run_sync_db_call(
            client.table("knowledge_audit").insert({
                "doc_id": doc_id,
                "org_id": org_id,
                "user_id": user_id,
                "action": "update",
                "old_content": existing.data.get("content", "")[:500],
                "new_content": update_data.get("content", "")[:500] if "content" in update_data else None
            }).execute
        )
    except Exception as audit_err:
        logger.warning(f"Audit log failed: {audit_err}")

    return result.data[0]

@app.delete("/admin/knowledge/{doc_id}")
async def delete_knowledge(
    request: Request,
    doc_id: int,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    existing = await run_sync_db_call(
        client.table("general_knowledge")
        .select("content")
        .eq("id", doc_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )

    result = await run_sync_db_call(
        client.table("general_knowledge")
        .delete()
        .eq("id", doc_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        await run_sync_db_call(
            client.table("knowledge_audit").insert({
                "doc_id": doc_id,
                "org_id": org_id,
                "user_id": user_id,
                "action": "delete",
                "old_content": existing.data.get("content", "")[:500] if existing.data else None
            }).execute
        )
    except Exception as audit_err:
        logger.warning(f"Audit log failed: {audit_err}")

    return {"message": "Deleted successfully"}

@app.post("/admin/backfill-embeddings")
async def backfill_embeddings_endpoint(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    await backfill_knowledge_embeddings()
    return {"message": "Embedding backfill completed."}

@app.post("/api/compute-embedding")
async def compute_embedding(request: Request, x_admin_key: str = Header(..., alias="X-Admin-Key")):
    if x_admin_key != ADMIN_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    data = await request.json()
    record_id = data.get("id")
    title = data.get("title", "")
    content = data.get("content", "")

    if not record_id:
        raise HTTPException(status_code=400, detail="Missing record id")

    embedder = get_embedder()
    if not embedder:
        raise HTTPException(status_code=500, detail="Embedder not available")

    text = f"{title} {content}".strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text to embed")

    embedding = embedder.encode(text).tolist()

    client = get_supabase()
    result = await run_sync_db_call(client.table("general_knowledge").update({"embedding": embedding}).eq("id", record_id).execute)
    if not result.data:
        raise HTTPException(status_code=404, detail="Record not found")

    return {"status": "updated", "id": record_id}

# ------------------------------------------------------------------
# DEBUG ENDPOINTS
# ------------------------------------------------------------------
@app.get("/debug/check-org-members")
async def debug_org_members(
    request: Request,
    user_id: str,
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    # Admin key required. This endpoint dumps a user's full
    # org_members rows, which is an information-disclosure surface if
    # left open. _require_admin_key raises 403 when the key is missing
    # or wrong, so nothing below runs for unauthenticated callers.
    _require_admin_key(x_admin_key)

    client = get_supabase()
    try:
        result = await run_sync_db_call(client.table("org_members").select("*").eq("user_id", user_id).execute)
        return {
            "user_id_queried": user_id,
            "count": len(result.data),
            "data": result.data,
            "client_using_service_key": SUPABASE_SERVICE_ROLE_KEY is not None,
            "service_key_present": bool(SUPABASE_SERVICE_ROLE_KEY)
        }
    except Exception as e:
        return {"error": str(e), "user_id_queried": user_id}

@app.get("/debug/key-info")
async def debug_key_info(
    request: Request,
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    await rate_limit(get_client_ip(request))
    # Admin key required. This endpoint returns the first 20 characters
    # of the service role key and the Supabase URL, which together are
    # a partial credential disclosure. _require_admin_key raises 403
    # on missing or wrong key.
    _require_admin_key(x_admin_key)

    return {
        "has_service_key": bool(SUPABASE_SERVICE_ROLE_KEY),
        "key_prefix": (SUPABASE_SERVICE_ROLE_KEY[:20] if SUPABASE_SERVICE_ROLE_KEY else "none"),
        "has_anon_key": bool(SUPABASE_ANON_KEY),
        "anon_prefix": (SUPABASE_ANON_KEY[:20] if SUPABASE_ANON_KEY else "none"),
        "supabase_url": SUPABASE_URL
    }


@app.get("/auth/org")
async def get_org_name(request: Request, user_org: Tuple[str, str] = Depends(get_current_org)):
    await rate_limit(get_client_ip(request))
    _, org_id = user_org
    client = get_supabase()
    result = await run_sync_db_call(client.table("organisations").select("org_name").eq("id", org_id).maybe_single().execute)
    return {"org_name": result.data["org_name"] if result and result.data else "Unknown Org"}


# ==================================================================
# SUPPLIERS
# ==================================================================
@app.get("/suppliers")
async def list_suppliers(
    request: Request,
    status: Optional[str] = None,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    query = client.table("suppliers").select("id, name, contact_person, email, phone, address, tax_id, payment_terms, status, rating, created_at").eq("org_id", org_id)
    if status:
        query = query.eq("status", status)

    result = await run_sync_db_call(query.order("name", desc=False).execute)
    return {"suppliers": result.data}

@app.post("/suppliers")
async def create_supplier(
    request: Request,
    supplier: SupplierCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    data = supplier.dict()
    data["org_id"] = org_id
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = await run_sync_db_call(client.table("suppliers").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create supplier")
    return {"supplier": result.data[0]}

@app.get("/suppliers/{supplier_id}")
async def get_supplier(
    request: Request,
    supplier_id: UUID,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    result = await run_sync_db_call(
        client.table("suppliers")
        .select("id, name, contact_person, email, phone, address, tax_id, payment_terms, status, rating, created_at, updated_at")
        .eq("id", supplier_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {"supplier": result.data[0]}

@app.put("/suppliers/{supplier_id}")
async def update_supplier(
    request: Request,
    supplier_id: UUID,
    supplier: SupplierUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    update_data = {k: v for k, v in supplier.dict(exclude_unset=True).items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = await run_sync_db_call(
        client.table("suppliers")
        .update(update_data)
        .eq("id", supplier_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {"supplier": result.data[0]}

@app.delete("/suppliers/{supplier_id}")
async def delete_supplier(
    request: Request,
    supplier_id: UUID,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    po_check = await run_sync_db_call(
        client.table("purchase_orders")
        .select("id")
        .eq("supplier_id", supplier_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute
    )
    if po_check.data:
        raise HTTPException(status_code=400, detail="Cannot delete supplier with existing purchase orders")

    result = await run_sync_db_call(
        client.table("suppliers")
        .delete()
        .eq("id", supplier_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {"message": "Supplier deleted successfully"}


# ==================================================================
# PURCHASE ORDERS
# ==================================================================
@app.get("/purchase-orders")
async def list_purchase_orders(
    request: Request,
    status: Optional[str] = None,
    supplier_id: Optional[UUID] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 50,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    query = client.table("purchase_orders").select(
        "id, po_number, order_date, expected_delivery_date, status, total_amount, notes, "
        "supplier:supplier_id(name, id), created_by, created_at"
    ).eq("org_id", org_id)

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            query = query.eq("status", statuses[0])
        else:
            query = query.in_("status", statuses)

    if supplier_id:
        query = query.eq("supplier_id", supplier_id)
    if from_date:
        query = query.gte("order_date", from_date.isoformat())
    if to_date:
        query = query.lte("order_date", to_date.isoformat())

    result = await run_sync_db_call(query.order("created_at", desc=True).range(offset, offset + limit - 1).execute)
    return {"purchase_orders": result.data, "total": len(result.data) if result.data else 0}

@app.post("/purchase-orders")
async def create_purchase_order(
    request: Request,
    po: POCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    supplier = await run_sync_db_call(
        client.table("suppliers").select("id").eq("id", po.supplier_id).eq("org_id", org_id).maybe_single().execute
    )
    if not supplier.data:
        raise HTTPException(status_code=400, detail="Supplier not found in this organisation")

    inventory_ids = [item.inventory_id for item in po.items]
    existing_inv = await run_sync_db_call(
        client.table("inventory")
        .select("id")
        .eq("org_id", org_id)
        .in_("id", inventory_ids)
        .execute
    )
    existing_set = {row["id"] for row in existing_inv.data}
    missing = set(inventory_ids) - existing_set
    if missing:
        raise HTTPException(status_code=400, detail=f"Inventory IDs not found: {missing}")

    po_count = await run_sync_db_call(
        client.table("purchase_orders").select("id", count="exact").eq("org_id", org_id).execute
    )
    po_number = f"PO-{org_id[:4]}-{po_count.count + 1:04d}"

    total_amount = float(sum(item.unit_cost * item.quantity_ordered for item in po.items))

    branch_id_for_po = await resolve_branch_for_write(org_id)
    po_data = {
        "org_id": org_id,
        "branch_id": branch_id_for_po,
        "supplier_id": str(po.supplier_id),
        "po_number": po_number,
        "order_date": datetime.now(timezone.utc).date().isoformat(),
        "expected_delivery_date": po.expected_delivery_date.isoformat(),
        "status": "draft",
        "total_amount": total_amount,
        "notes": po.notes,
        "created_by": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    po_result = await run_sync_db_call(client.table("purchase_orders").insert(po_data).execute)
    if not po_result.data:
        raise HTTPException(status_code=500, detail="Failed to create purchase order")
    po_id = po_result.data[0]["id"]

    items_to_insert = [
        {
            "po_id": po_id,
            "inventory_id": item.inventory_id,
            "quantity_ordered": item.quantity_ordered,
            "unit_cost": float(item.unit_cost)
        }
        for item in po.items
    ]
    if items_to_insert:
        await run_sync_db_call(client.table("purchase_order_items").insert(items_to_insert).execute)

    full_po = await run_sync_db_call(
        client.table("purchase_orders")
        .select("*, purchase_order_items(*, inventory:inventory_id(item_code, description))")
        .eq("id", po_id)
        .maybe_single()
        .execute
    )
    return {"purchase_order": jsonable_encoder(full_po.data)}

@app.get("/purchase-orders/{po_id}")
async def get_purchase_order(
    request: Request,
    po_id: UUID,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    result = await run_sync_db_call(
        client.table("purchase_orders")
        .select("*, supplier:supplier_id(*), purchase_order_items(*, inventory:inventory_id(item_code, description))")
        .eq("id", po_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return {"purchase_order": jsonable_encoder(result.data)}

@app.put("/purchase-orders/{po_id}")
async def update_purchase_order(
    request: Request,
    po_id: UUID,
    po: POUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    existing = await run_sync_db_call(
        client.table("purchase_orders").select("status").eq("id", po_id).eq("org_id", org_id).maybe_single().execute
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if existing.data["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft orders can be edited")

    update_data = {k: v for k, v in po.dict(exclude_unset=True).items() if v is not None}
    for key, value in update_data.items():
        if isinstance(value, UUID):
            update_data[key] = str(value)
    if "supplier_id" in update_data:
        supplier = await run_sync_db_call(
            client.table("suppliers").select("id").eq("id", update_data["supplier_id"]).eq("org_id", org_id).maybe_single().execute
        )
        if not supplier.data:
            raise HTTPException(status_code=400, detail="Supplier not found")
    if "expected_delivery_date" in update_data:
        update_data["expected_delivery_date"] = update_data["expected_delivery_date"].isoformat()

    if po.items is not None:
        new_inv_ids = [item.inventory_id for item in po.items if item.inventory_id]
        if new_inv_ids:
            existing_inv = await run_sync_db_call(
                client.table("inventory")
                .select("id")
                .eq("org_id", org_id)
                .in_("id", new_inv_ids)
                .execute
            )
            existing_set = {row["id"] for row in existing_inv.data}
            missing = set(new_inv_ids) - existing_set
            if missing:
                raise HTTPException(status_code=400, detail=f"Inventory IDs not found: {missing}")

        await run_sync_db_call(client.table("purchase_order_items").delete().eq("po_id", po_id).execute)
        new_items = []
        for item in po.items:
            new_items.append({
                "po_id": po_id,
                "inventory_id": item.inventory_id,
                "quantity_ordered": item.quantity_ordered,
                "unit_cost": float(item.unit_cost) if item.unit_cost is not None else 0.0
            })
        if new_items:
            await run_sync_db_call(client.table("purchase_order_items").insert(new_items).execute)
        total = float(sum(i.unit_cost * i.quantity_ordered for i in po.items))
        update_data["total_amount"] = total

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(
        client.table("purchase_orders")
        .update(update_data)
        .eq("id", po_id)
        .eq("org_id", org_id)
        .execute
    )
    return {"purchase_order": jsonable_encoder(result.data[0]) if result.data else None}

@app.delete("/purchase-orders/{po_id}")
async def delete_purchase_order(
    request: Request,
    po_id: UUID,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    existing = await run_sync_db_call(
        client.table("purchase_orders").select("status").eq("id", po_id).eq("org_id", org_id).maybe_single().execute
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if existing.data["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft orders can be deleted")

    result = await run_sync_db_call(
        client.table("purchase_orders").delete().eq("id", po_id).eq("org_id", org_id).execute
    )
    return {"message": "Purchase order deleted"}

@app.patch("/purchase-orders/{po_id}/status")
async def update_po_status(
    request: Request,
    po_id: UUID,
    status_update: POStatusUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    existing = await run_sync_db_call(
        client.table("purchase_orders").select("status").eq("id", po_id).eq("org_id", org_id).maybe_single().execute
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    current = existing.data["status"]
    new_status = status_update.status
    valid_transitions = {
        "draft": ["sent", "cancelled"],
        "sent": ["partially_received", "received", "cancelled"],
        "partially_received": ["received", "cancelled"],
        "received": [],
        "cancelled": []
    }
    if new_status not in valid_transitions.get(current, []):
        raise HTTPException(status_code=400, detail=f"Invalid status transition from {current} to {new_status}")

    result = await run_sync_db_call(
        client.table("purchase_orders")
        .update({"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", po_id)
        .eq("org_id", org_id)
        .execute
    )
    return {
        "message": f"Status updated to {new_status}",
        "purchase_order": jsonable_encoder(result.data[0]) if result.data else None
    }


# ==================================================================
# GOODS RECEIVED NOTES (GRN)
# ==================================================================
@app.get("/grn")
async def list_grn(
    request: Request,
    po_id: Optional[UUID] = None,
    status: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 50,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    query = client.table("grn").select(
        "id, grn_number, received_date, status, notes, "
        "po:purchase_orders(po_number, supplier:supplier_id(name)), "
        "location:location_id(name), created_by, created_at"
    ).eq("org_id", org_id)

    if po_id:
        query = query.eq("po_id", po_id)
    if status:
        query = query.eq("status", status)
    if from_date:
        query = query.gte("received_date", from_date.isoformat())
    if to_date:
        query = query.lte("received_date", to_date.isoformat())

    result = await run_sync_db_call(query.order("created_at", desc=True).range(offset, offset + limit - 1).execute)
    return {"grn": result.data}

@app.post("/grn")
async def create_grn(
    request: Request,
    grn: GRNCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    po = await run_sync_db_call(
        client.table("purchase_orders")
        .select("id, status")
        .eq("id", grn.po_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not po.data:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.data["status"] in ["cancelled", "received"]:
        raise HTTPException(status_code=400, detail=f"Cannot receive against a {po.data['status']} order")

    location = await run_sync_db_call(
        client.table("locations").select("id").eq("id", grn.location_id).eq("org_id", org_id).maybe_single().execute
    )
    if not location.data:
        raise HTTPException(status_code=400, detail="Location not found")

    po_items = await run_sync_db_call(
        client.table("purchase_order_items")
        .select("id, inventory_id")
        .eq("po_id", grn.po_id)
        .execute
    )
    # Normalise both sides to strings — Pydantic gives us UUID objects,
    # PostgREST gives us JSON strings. UUID("…") != "…".
    po_item_ids     = {str(item["id"]) for item in (po_items.data or [])}
    grn_po_item_ids = {str(item.po_item_id) for item in grn.items}
    if not grn_po_item_ids.issubset(po_item_ids):
        raise HTTPException(status_code=400, detail="Some items do not belong to this purchase order")

    grn_count = await run_sync_db_call(
        client.table("grn").select("id", count="exact").eq("org_id", org_id).execute
    )
    grn_number = f"GRN-{org_id[:4]}-{grn_count.count + 1:04d}"

    branch_id_for_grn = await resolve_branch_for_write(org_id)
    grn_data = {
        "org_id": org_id,
        "branch_id": branch_id_for_grn,
        "po_id": str(grn.po_id),
        "grn_number": grn_number,
        "received_date": grn.received_date.isoformat(),
        "location_id": str(grn.location_id),
        "status": "draft",
        "notes": grn.notes,
        "created_by": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    grn_result = await run_sync_db_call(client.table("grn").insert(grn_data).execute)
    if not grn_result.data:
        raise HTTPException(status_code=500, detail="Failed to create GRN")
    grn_id = grn_result.data[0]["id"]

    items_to_insert = [
        {
            "grn_id": grn_id,
            "po_item_id": str(item.po_item_id),
            "received_quantity": item.received_quantity,
            "accepted_quantity": item.accepted_quantity,
            "rejected_quantity": item.rejected_quantity,
            "rejection_reason": item.rejection_reason,
            "batch_number": item.batch_number,
            "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
            "cost_price_naira": float(item.cost_price_naira) if item.cost_price_naira is not None else None
        }
        for item in grn.items
    ]
    if items_to_insert:
        await run_sync_db_call(client.table("grn_items").insert(items_to_insert).execute)

    full_grn = await run_sync_db_call(
        client.table("grn")
        .select("*, grn_items(*), po:purchase_orders(po_number, supplier:supplier_id(name))")
        .eq("id", grn_id)
        .maybe_single()
        .execute
    )
    return {"grn": full_grn.data}

@app.get("/grn/{grn_id}")
async def get_grn(
    request: Request,
    grn_id: UUID,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    result = await run_sync_db_call(
        client.table("grn")
        .select("*, grn_items(*, po_item:purchase_order_items(inventory_id, quantity_ordered)), po:purchase_orders(po_number, expected_delivery_date, supplier:supplier_id(name))")
        .eq("id", grn_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="GRN not found")
    return {"grn": result.data}

@app.put("/grn/{grn_id}")
async def update_grn(
    request: Request,
    grn_id: UUID,
    grn: GRNUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    existing = await run_sync_db_call(
        client.table("grn").select("status").eq("id", grn_id).eq("org_id", org_id).maybe_single().execute
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="GRN not found")
    if existing.data["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft GRNs can be edited")

    update_data = {k: v for k, v in grn.dict(exclude_unset=True).items() if v is not None}
    if "received_date" in update_data:
        update_data["received_date"] = update_data["received_date"].isoformat()
    if "location_id" in update_data:
        location = await run_sync_db_call(
            client.table("locations").select("id").eq("id", update_data["location_id"]).eq("org_id", org_id).maybe_single().execute
        )
        if not location.data:
            raise HTTPException(status_code=400, detail="Location not found")
        # Normalise UUID object -> string before it hits the JSON serializer.
        update_data["location_id"] = str(update_data["location_id"])

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    if grn.items is not None:
        await run_sync_db_call(client.table("grn_items").delete().eq("grn_id", grn_id).execute)
        new_items = []
        for item in grn.items:
            new_items.append({
                "grn_id": grn_id,
                "po_item_id": str(item.po_item_id),
                "received_quantity": item.received_quantity,
                "accepted_quantity": item.accepted_quantity,
                "rejected_quantity": item.rejected_quantity,
                "rejection_reason": item.rejection_reason,
                "batch_number": item.batch_number,
                "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                "cost_price_naira": float(item.cost_price_naira) if item.cost_price_naira is not None else None
            })
        if new_items:
            await run_sync_db_call(client.table("grn_items").insert(new_items).execute)

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = await run_sync_db_call(
        client.table("grn").update(update_data).eq("id", grn_id).eq("org_id", org_id).execute
    )
    return {"grn": result.data[0] if result.data else None}

@app.delete("/grn/{grn_id}")
async def delete_grn(
    request: Request,
    grn_id: UUID,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    existing = await run_sync_db_call(
        client.table("grn").select("status").eq("id", grn_id).eq("org_id", org_id).maybe_single().execute
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="GRN not found")
    if existing.data["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft GRNs can be deleted")

    result = await run_sync_db_call(
        client.table("grn").delete().eq("id", grn_id).eq("org_id", org_id).execute
    )
    return {"message": "GRN deleted"}

@app.post("/grn/{grn_id}/post")
async def post_grn(
    request: Request,
    grn_id: UUID,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    grn_check = await run_sync_db_call(
        client.table("grn").select("org_id").eq("id", grn_id).eq("org_id", org_id).maybe_single().execute
    )
    if not grn_check.data:
        raise HTTPException(status_code=404, detail="GRN not found in this organisation")

    try:
        result = await run_sync_db_call(
            client.rpc('post_grn', {'p_grn_id': str(grn_id)}).execute
        )

        po_status = result.data.get("po_status")
        if po_status == "received":
            po_info = await run_sync_db_call(
                client.table("purchase_orders")
                .select("supplier_id")
                .eq("id", result.data.get("po_id"))
                .maybe_single()
                .execute
            )
            if po_info and po_info.data:
                await create_ap_from_po(
                    po_id=result.data.get("po_id"),
                    org_id=org_id,
                    supplier_id=po_info.data["supplier_id"]
                )

        return {
            "message": "GRN posted successfully",
            "grn_id": str(grn_id),
            "po_id": result.data.get("po_id"),
            "po_status": result.data.get("po_status"),
            "grn_number": result.data.get("grn_number"),
            "fully_received": result.data.get("fully_received"),
            "posted_at": result.data.get("posted_at")
        }

    except Exception as e:
        logger.error(f"GRN post RPC failed: {e}")
        detail = str(e)
        if "GRN already posted" in detail:
            raise HTTPException(status_code=400, detail="GRN already posted")
        if "GRN not found" in detail:
            raise HTTPException(status_code=404, detail="GRN not found")
        raise HTTPException(status_code=500, detail=f"Failed to post GRN: {detail}")

# ------------------------------------------------------------------
# INVENTORY MANAGEMENT
# ------------------------------------------------------------------
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

@app.get("/inventory")
async def get_inventory(request: Request, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "sales_rep", "finance"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    result = await run_sync_db_call(client.table("inventory").select("*").eq("org_id", org_id).order("id", desc=False).execute)
    return result.data

@app.post("/inventory")
async def create_inventory_item(
    request: Request,
    item: InventoryItem,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    data = item.dict()
    data["org_id"] = org_id
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    expiry_date = data.get("expiry_date")
    batch_number = data.get("batch_number")
    lot_number = data.get("lot_number")

    if expiry_date and not batch_number:
        batch_number = await get_next_auto_batch_number()
        data["batch_number"] = batch_number
        if not lot_number:
            lot_number = "LEGACY-IMPORT"
            data["lot_number"] = lot_number

    inv_result = await run_sync_db_call(client.table("inventory").insert(data).execute)
    if not inv_result.data:
        raise HTTPException(status_code=500, detail="Failed to create inventory item")
    new_inv = inv_result.data[0]

    if expiry_date and data.get("batch_number"):
        batch_data = {
            "inventory_id": new_inv["id"],
            "batch_number": data["batch_number"],
            "lot_number": data.get("lot_number") or "LEGACY-IMPORT",
            "quantity": data.get("current_qty", 0),
            "expiry_date": expiry_date,
            "cost_price_naira": data.get("cost_price_naira", 0.0),
            "supplier_name": data.get("supplier_name"),
            "manufacture_date": data.get("manufacture_date"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        await run_sync_db_call(client.table("inventory_batches").insert(batch_data).execute)
        logger.info(f"Auto‑batch {data['batch_number']} created for inventory {new_inv['id']}")

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
            await run_sync_db_call(
                client.table("location_stocks").upsert({
                    "location_id": main_location.data["id"],
                    "inventory_id": new_inv["id"],
                    "quantity": data.get("current_qty", 0),
                    "reserved_quantity": 0,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }, on_conflict="location_id,inventory_id").execute
            )
    except Exception as loc_err:
        logger.error(f"Failed to create location stock for inv={new_inv['id']}: {loc_err}")

    return new_inv

@app.put("/inventory/{item_id}")
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
        .select("id, expiry_date, batch_number, current_qty")
        .eq("id", item_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )

    if not existing.data:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    update_data = {k: v for k, v in item.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    new_expiry = update_data.get("expiry_date")
    new_batch = update_data.get("batch_number")
    new_lot = update_data.get("lot_number")
    new_qty = update_data.get("current_qty", existing.data.get("current_qty", 0))

    if new_expiry:
        existing_batch_number = existing.data.get("batch_number")
        if new_batch and new_batch.strip():
            target_batch_number = new_batch.strip()
        elif existing_batch_number:
            target_batch_number = existing_batch_number
        else:
            try:
                any_batch_query = await run_sync_db_call(
                    client.table("inventory_batches")
                    .select("batch_number")
                    .eq("inventory_id", item_id)
                    .limit(1)
                    .execute
                )
                if any_batch_query.data:
                    target_batch_number = any_batch_query.data[0]["batch_number"]
                    logger.info(f"Found existing batch {target_batch_number} for inventory {item_id}")
                else:
                    target_batch_number = await get_next_auto_batch_number()
            except Exception as e:
                logger.warning(f"Error checking for existing batches: {e}")
                target_batch_number = await get_next_auto_batch_number()

        try:
            batch_query = await run_sync_db_call(
                client.table("inventory_batches")
                .select("id, quantity, expiry_date")
                .eq("inventory_id", item_id)
                .eq("batch_number", target_batch_number)
                .maybe_single()
                .execute
            )
            existing_batch = batch_query.data if batch_query else None
        except Exception as e:
            logger.error(f"Error querying existing batch: {e}")
            existing_batch = None

        if existing_batch:
            await run_sync_db_call(
                client.table("inventory_batches")
                .update({
                    "quantity": new_qty,
                    "expiry_date": new_expiry,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
                .eq("id", existing_batch["id"])
                .execute
            )
            logger.info(f"✅ Updated batch {target_batch_number} for inventory {item_id}")
            if target_batch_number != existing.data.get("batch_number"):
                await run_sync_db_call(
                    client.table("inventory")
                    .update({"batch_number": target_batch_number})
                    .eq("id", item_id)
                    .execute
                )
        else:
            if not new_lot:
                new_lot = "LEGACY-IMPORT"
            batch_data = {
                "inventory_id": item_id,
                "batch_number": target_batch_number,
                "lot_number": new_lot,
                "quantity": new_qty,
                "expiry_date": new_expiry,
                "cost_price_naira": update_data.get("cost_price_naira", 0.0),
                "supplier_name": update_data.get("supplier_name"),
                "manufacture_date": update_data.get("manufacture_date"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            await run_sync_db_call(
                client.table("inventory_batches")
                .insert(batch_data)
                .execute
            )
            logger.info(f"🆕 Inserted new batch {target_batch_number} for inventory {item_id}")
            if target_batch_number != existing.data.get("batch_number"):
                await run_sync_db_call(
                    client.table("inventory")
                    .update({"batch_number": target_batch_number})
                    .eq("id", item_id)
                    .execute
                )
    else:
        pass

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

@app.delete("/inventory/{item_id}")
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

@app.get("/inventory/public-list")
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

    resolved_org_id = org_id or PUBLIC_STORE_ORG_ID
    if not resolved_org_id:
        raise HTTPException(status_code=400, detail="Organisation not specified")

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
        return {
            "items": fallback.data or [],
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
    return {
        "items": items,
        "total": total,
        "location_id": str(online_location_id),
        "org_id": resolved_org_id,
    }


@app.get("/inventory/public-categories")
async def public_categories(
    request: Request,
    org_id: Optional[str] = Query(None),
):
    await rate_limit(get_client_ip(request))
    resolved_org_id = org_id or PUBLIC_STORE_ORG_ID
    if not resolved_org_id:
        raise HTTPException(status_code=400, detail="Organisation not specified")

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


@app.get("/inventory/pos")
async def pos_inventory(
    request: Request,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None, description="Override the POS channel's default location"),
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data

    resolved_location_id = location_id
    if not resolved_location_id:
        resolved_location_id = await get_location_for_channel(org_id, "pos")

    if not resolved_location_id:
        logger.warning(f"/inventory/pos: no location resolved for org {org_id}, falling back to global inventory")
        client = get_supabase()
        query = client.table("inventory").select("*", count="exact").eq("org_id", org_id)
        if q:
            or_condition = f"description.ilike.%{q}%,item_code.ilike.%{q}%,product_group.ilike.%{q}%"
            query = query.or_(or_condition)
        result = await run_sync_db_call(query.range(offset, offset + limit - 1).execute)
        return {"items": result.data or [], "total": result.count or 0, "location_id": None}

    items, total = await fetch_inventory_scoped_to_location(
        org_id=org_id,
        location_id=str(resolved_location_id),
        limit=limit,
        offset=offset,
        q=q,
        sort_by="newest",
        require_positive_stock=False,
    )
    return {"items": items, "total": total, "location_id": str(resolved_location_id)}


# ------------------------------------------------------------------
# PUBLIC STOREFRONT ENDPOINTS
# ------------------------------------------------------------------
@app.get("/public/top-products")
async def get_top_products(
    request: Request,
    org_id: Optional[str] = Query(None),
):
    await rate_limit(get_client_ip(request))
    resolved_org_id = org_id or PUBLIC_STORE_ORG_ID
    if not resolved_org_id:
        raise HTTPException(status_code=400, detail="Organisation not specified")

    client = get_supabase()
    try:
        result = await run_sync_db_call(
            client.table("top_selling_products")
            .select("inventory_id, product_name, price_naira, image_url")
            .eq("org_id", resolved_org_id)
            .order("units_sold", desc=True)
            .limit(20)
            .execute
        )
    except Exception as e:
        logger.error(f"Public top-products error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Unable to fetch top products")

    top_items = result.data or []
    if not top_items:
        return {"products": [], "message": "No sales data yet – check back soon"}

    online_location_id = await get_location_for_channel(resolved_org_id, "online")
    if online_location_id:
        inventory_ids = [p["inventory_id"] for p in top_items if p.get("inventory_id")]
        stock_map: Dict[int, int] = {}
        if inventory_ids:
            ls_result = await run_sync_db_call(
                client.table("location_stocks")
                .select("inventory_id, quantity")
                .eq("location_id", str(online_location_id))
                .in_("inventory_id", inventory_ids)
                .execute
            )
            for row in (ls_result.data or []):
                stock_map[row["inventory_id"]] = int(row.get("quantity") or 0)

        enriched: List[Dict] = []
        for p in top_items:
            inv_id = p.get("inventory_id")
            qty = stock_map.get(inv_id, 0)
            if qty <= 0:
                continue
            p["current_qty"]  = qty
            p["location_qty"] = qty
            p["location_id"]  = str(online_location_id)
            enriched.append(p)

        return {
            "products": enriched[:6],
            "location_id": str(online_location_id),
            "org_id": resolved_org_id,
        }

    return {"products": top_items[:6], "location_id": None, "org_id": resolved_org_id}

# ------------------------------------------------------------------
# BULK INVENTORY UPLOAD (CSV)
# ------------------------------------------------------------------
@app.post("/inventory/bulk-upload")
async def bulk_upload_inventory(
    request: Request,
    file: UploadFile = File(...),
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data

    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    try:
        contents = await file.read()
        try:
            decoded = contents.decode('utf-8')
        except UnicodeDecodeError:
            decoded = contents.decode('latin-1')

        csv_reader = csv.DictReader(io.StringIO(decoded))
        rows = list(csv_reader)
        if not rows:
            raise HTTPException(status_code=400, detail="Empty CSV file")

        client = get_supabase()

        existing_items = await run_sync_db_call(
            client.table("inventory")
            .select("id, item_code, current_qty, cost_price_naira")
            .eq("org_id", org_id)
            .execute
        )
        existing_map = {}
        for item in existing_items.data:
            if item.get("item_code"):
                existing_map[item["item_code"]] = item

        new_items = []
        updates = []
        errors = []

        main_location = await run_sync_db_call(client.table("locations").select("id").eq("org_id", org_id).eq("is_warehouse", True).maybe_single().execute)
        main_location_id = main_location.data["id"] if main_location and main_location.data else None

        for row_num, row in enumerate(rows, start=2):
            description = row.get("description", "").strip()
            if not description:
                errors.append(f"Row {row_num}: Missing 'description'")
                continue

            try:
                price_naira = float(row.get("price_naira", 0))
                if price_naira <= 0:
                    errors.append(f"Row {row_num}: 'price_naira' must be > 0")
                    continue
            except ValueError:
                errors.append(f"Row {row_num}: 'price_naira' invalid number")
                continue

            weight_str = row.get("weight_kg", "").strip()
            if not weight_str:
                errors.append(f"Row {row_num}: 'weight_kg' is required")
                continue
            try:
                weight_kg = float(weight_str)
                if weight_kg < 0:
                    errors.append(f"Row {row_num}: 'weight_kg' cannot be negative")
                    continue
            except ValueError:
                errors.append(f"Row {row_num}: 'weight_kg' must be a number")
                continue

            handling_category = row.get("handling_category", "").strip().lower()
            if handling_category not in ["standard", "fragile", "bulky", "hazardous"]:
                errors.append(f"Row {row_num}: 'handling_category' must be one of: standard, fragile, bulky, hazardous")
                continue

            size_str = row.get("size_factor", "").strip()
            if not size_str:
                errors.append(f"Row {row_num}: 'size_factor' is required")
                continue
            try:
                size_factor = float(size_str)
                if size_factor < 1.0:
                    errors.append(f"Row {row_num}: 'size_factor' must be >= 1.0")
                    continue
            except ValueError:
                errors.append(f"Row {row_num}: 'size_factor' must be a number")
                continue

            item_code = row.get("item_code", "").strip()
            if not item_code:
                errors.append(f"Row {row_num}: 'item_code' is required")
                continue

            cost_str = row.get("cost_price_naira", "").strip()
            if not cost_str:
                errors.append(f"Row {row_num}: 'cost_price_naira' is required")
                continue
            try:
                cost_price_naira = float(cost_str)
                if cost_price_naira < 0:
                    errors.append(f"Row {row_num}: 'cost_price_naira' cannot be negative")
                    continue
            except ValueError:
                errors.append(f"Row {row_num}: 'cost_price_naira' invalid number")
                continue

            product_group = row.get("product_group", "").strip()
            if not product_group:
                errors.append(f"Row {row_num}: 'product_group' is required")
                continue

            qty_str = row.get("current_qty", "").strip()
            if not qty_str:
                errors.append(f"Row {row_num}: 'current_qty' is required")
                continue
            try:
                csv_qty = int(qty_str)
                if csv_qty < 0:
                    errors.append(f"Row {row_num}: 'current_qty' cannot be negative")
                    continue
            except ValueError:
                errors.append(f"Row {row_num}: 'current_qty' must be an integer")
                continue

            image_url = row.get("image_url", "").strip()

            if item_code in existing_map:
                existing = existing_map[item_code]
                new_qty = existing["current_qty"] + csv_qty
                if new_qty < 0:
                    errors.append(f"Row {row_num}: Quantity would become negative ({new_qty}) – not allowed")
                    continue

                update_data = {
                    "description": description,
                    "price_naira": price_naira,
                    "current_qty": new_qty,
                    "cost_price_naira": cost_price_naira,
                    "product_group": product_group,
                    "image_url": image_url,
                    "weight_kg": weight_kg,
                    "handling_category": handling_category,
                    "size_factor": size_factor,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }

                if update_data["cost_price_naira"] != existing.get("cost_price_naira", 0):
                    try:
                        await run_sync_db_call(
                            client.table("inventory_cost_history").insert({
                                "item_code": item_code,
                                "org_id": org_id,
                                "old_cost": existing.get("cost_price_naira", 0),
                                "new_cost": update_data["cost_price_naira"],
                                "changed_at": datetime.now(timezone.utc).isoformat()
                            }).execute
                        )
                    except Exception as log_err:
                        logger.warning(f"Failed to log cost history for {item_code}: {log_err}")

                updates.append((item_code, update_data))
            else:
                new_item = {
                    "org_id": org_id,
                    "item_code": item_code,
                    "description": description,
                    "product_group": product_group,
                    "price_naira": price_naira,
                    "current_qty": csv_qty,
                    "image_url": image_url,
                    "cost_price_naira": cost_price_naira,
                    "weight_kg": weight_kg,
                    "handling_category": handling_category,
                    "size_factor": size_factor,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
                new_items.append(new_item)

        if errors:
            raise HTTPException(status_code=400, detail="; ".join(errors[:10]))

        updated_count = 0
        for item_code, update_data in updates:
            result = await run_sync_db_call(
                client.table("inventory")
                .update(update_data)
                .eq("org_id", org_id)
                .eq("item_code", item_code)
                .execute
            )
            if result.data:
                updated_count += 1

        inserted_count = 0
        for new_item in new_items:
            result = await run_sync_db_call(
                client.table("inventory").insert(new_item).execute
            )
            if result.data:
                inserted_count += 1
                if main_location_id:
                    try:
                        await run_sync_db_call(
                            client.table("location_stocks").upsert({
                                "location_id": main_location_id,
                                "inventory_id": result.data[0]["id"],
                                "quantity": new_item["current_qty"],
                                "reserved_quantity": 0,
                                "updated_at": datetime.now(timezone.utc).isoformat()
                            }, on_conflict="location_id,inventory_id").execute
                        )
                    except Exception as loc_err:
                        logger.error(f"Failed to create location stock for inv={result.data[0]['id']}: {loc_err}")

        return {
            "message": "Bulk upload completed",
            "updated": updated_count,
            "inserted": inserted_count,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Bulk upload failed: {str(e)}")


class BatchEntry(BaseModel):
    batch_number: str = Field(..., min_length=1, max_length=100)
    lot_number: Optional[str] = None
    quantity: int = Field(..., gt=0)
    manufacture_date: Optional[str] = None
    expiry_date: str = Field(..., description="YYYY-MM-DD format")
    cost_price_naira: Optional[float] = 0
    supplier_name: Optional[str] = None
    supplier_invoice: Optional[str] = None

class InventoryWithExpiry(BaseModel):
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
    manufacture_date: Optional[str] = None
    lot_number: Optional[str] = None

class BatchTransferRequest(BaseModel):
    from_location_id: str    # UUID
    to_location_id: str      # UUID
    batch_id: int
    quantity: int = Field(..., gt=0)
    request_notes: Optional[str] = None

class ExpiryAlertResponse(BaseModel):
    inventory_id: int
    product_name: str
    batch_number: str
    expiry_date: str
    days_until_expiry: int
    alert_level: Literal["critical", "warning", "info", "good"]
    current_stock: int
    location_id: Optional[int] = None
    location_name: Optional[str] = None

# ===================== ACCOUNTING MODELS =====================
class AccountType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"

class ChartAccountCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=100)
    type: AccountType
    parent_id: Optional[UUID] = None
    description: Optional[str] = None

class ChartAccountUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=20)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[AccountType] = None
    parent_id: Optional[UUID] = None
    description: Optional[str] = None

class JournalEntryCreate(BaseModel):
    entry_date: date
    description: str
    reference: Optional[str] = None
    lines: List[Dict[str, Any]]

class JournalEntryUpdate(BaseModel):
    entry_date: Optional[date] = None
    description: Optional[str] = None
    reference: Optional[str] = None
    status: Optional[Literal["draft", "posted", "cancelled"]] = None

class ARCreate(BaseModel):
    sale_id: UUID
    customer_id: Optional[UUID] = None
    amount: float
    due_date: date

class APCreate(BaseModel):
    purchase_order_id: Optional[UUID] = None
    supplier_id: UUID
    amount: float
    due_date: date

class PaymentRegister(BaseModel):
    amount: float
    reference: Optional[str] = None
    notes: Optional[str] = None

class PLRequest(BaseModel):
    period_start: date
    period_end: date

class ExportRequest(BaseModel):
    entity: Literal["accounts_receivable", "accounts_payable", "journal_entries", "profit_loss"]
    format: Literal["csv", "json"]
    period_start: Optional[date] = None
    period_end: Optional[date] = None


# ------------------------------------------------------------------
# ACCOUNTING HELPERS
# ------------------------------------------------------------------
async def create_journal_entry(
    org_id: str,
    entry_date: date,
    description: str,
    lines: List[Dict],
    reference: Optional[str] = None,
    created_by: Optional[str] = None,
    status: str = "draft"
) -> Dict:
    total_debit = sum(l.get("debit", 0) for l in lines)
    total_credit = sum(l.get("credit", 0) for l in lines)
    if abs(total_debit - total_credit) > 0.01:
        raise HTTPException(status_code=400, detail="Debits and credits do not balance")

    client = get_supabase()
    entry_data = {
        "org_id": org_id,
        "branch_id": await resolve_branch_for_write(org_id),
        "entry_date": entry_date.isoformat(),
        "description": description,
        "reference": reference,
        "status": status,
        "created_by": created_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    entry_res = await run_sync_db_call(client.table("journal_entries").insert(entry_data).execute)
    if not entry_res.data:
        raise HTTPException(status_code=500, detail="Failed to create journal entry")
    entry_id = entry_res.data[0]["id"]

    line_objs = []
    for line in lines:
        line_objs.append({
            "journal_entry_id": entry_id,
            "account_id": line["account_id"],
            "debit": line.get("debit", 0),
            "credit": line.get("credit", 0),
            "description": line.get("description", "")
        })
    if line_objs:
        await run_sync_db_call(client.table("journal_lines").insert(line_objs).execute)

    await _log_audit_event(org_id, created_by, "journal_entry", "create", entry_id, None, entry_res.data[0])

    return entry_res.data[0]

async def post_journal_entry(entry_id: UUID, org_id: str, user_id: str) -> Dict:
    client = get_supabase()
    entry = await run_sync_db_call(
        client.table("journal_entries")
        .select("*")
        .eq("id", entry_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not entry.data:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    if entry.data["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft entries can be posted")

    update_data = {
        "status": "posted",
        "posted_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    result = await run_sync_db_call(
        client.table("journal_entries")
        .update(update_data)
        .eq("id", entry_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to post entry")

    await _log_audit_event(org_id, user_id, "journal_entry", "post", entry_id, None, result.data[0])
    return result.data[0]

async def generate_profit_loss(org_id: str, start_date: date, end_date: date) -> Dict:
    client = get_supabase()
    accounts = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id, type")
        .eq("org_id", org_id)
        .in_("type", ["revenue", "expense"])
        .execute
    )
    account_ids = [a["id"] for a in accounts.data] if accounts.data else []
    if not account_ids:
        return {"revenue": 0, "cogs": 0, "gross_profit": 0, "operating_expenses": 0, "net_income": 0}

    cogs_ids = []
    cogs_total = 0
    try:
        cogs_accounts = await run_sync_db_call(
            client.table("chart_of_accounts")
            .select("id")
            .eq("org_id", org_id)
            .eq("is_cogs", True)
            .execute
        )
        cogs_ids = [a["id"] for a in cogs_accounts.data] if cogs_accounts.data else []
        if cogs_ids:
            cogs_lines = await run_sync_db_call(
                client.table("journal_lines")
                .select("debit, credit")
                .in_("account_id", cogs_ids)
                .eq("journal_entry.status", "posted")
                .gte("journal_entry.entry_date", start_date.isoformat())
                .lte("journal_entry.entry_date", end_date.isoformat())
                .execute
            )
            cogs_total = sum((line["debit"] - line["credit"]) for line in cogs_lines.data) if cogs_lines.data else 0
    except Exception as e:
        logger.warning(f"COGS column missing (is_cogs), assuming all expenses are operating: {e}")

    rev_accounts = [a["id"] for a in accounts.data if a["type"] == "revenue"]
    rev_lines = await run_sync_db_call(
        client.table("journal_lines")
        .select("debit, credit, journal_entry:journal_entry_id(entry_date, status)")
        .in_("account_id", rev_accounts)
        .eq("journal_entry.status", "posted")
        .gte("journal_entry.entry_date", start_date.isoformat())
        .lte("journal_entry.entry_date", end_date.isoformat())
        .execute
    )
    revenue_total = sum((line["credit"] - line["debit"]) for line in rev_lines.data) if rev_lines.data else 0

    expense_accounts = [a["id"] for a in accounts.data if a["type"] == "expense" and a["id"] not in cogs_ids]
    exp_lines = await run_sync_db_call(
        client.table("journal_lines")
        .select("debit, credit, journal_entry:journal_entry_id(entry_date, status)")
        .in_("account_id", expense_accounts)
        .eq("journal_entry.status", "posted")
        .gte("journal_entry.entry_date", start_date.isoformat())
        .lte("journal_entry.entry_date", end_date.isoformat())
        .execute
    )
    operating_expenses = sum((line["debit"] - line["credit"]) for line in exp_lines.data) if exp_lines.data else 0

    gross_profit = revenue_total - cogs_total
    net_income = gross_profit - operating_expenses

    summary_data = {
        "org_id": org_id,
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "revenue": revenue_total,
        "cogs": cogs_total,
        "gross_profit": gross_profit,
        "operating_expenses": operating_expenses,
        "net_income": net_income,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await run_sync_db_call(client.table("profit_loss_summary").insert(summary_data).execute)

    return {
        "revenue": revenue_total,
        "cogs": cogs_total,
        "gross_profit": gross_profit,
        "operating_expenses": operating_expenses,
        "net_income": net_income
    }

async def _log_audit_event(org_id: str, user_id: str, table_name: str, action: str, record_id: UUID, old_vals: Optional[dict], new_vals: Optional[dict]):
    client = get_admin_supabase()
    branch_id_for_event = await resolve_branch_for_write(org_id)
    event_data = {
        "event_type": f"{table_name}.{action}",
        "event_version": 1,
        "payload": {
            "record_id": str(record_id),
            "old_values": old_vals,
            "new_values": new_vals
        },
        "user_id": user_id,
        "org_id": org_id,
        "branch_id": branch_id_for_event,
        "session_id": str(uuid.uuid4()),
        "source_ip": "0.0.0.0",
        "user_agent": "system",
        "local_created_at": datetime.now(timezone.utc).isoformat(),
        "table_name": table_name,
        "record_id": str(record_id),
        "old_values": old_vals,
        "new_values": new_vals
    }
    await run_sync_db_call(client.table("audit_events").insert(event_data).execute)

# ===================== A/R and A/P Helpers =====================
async def create_ar_from_sale(sale_id: str, org_id: str, customer_id: Optional[str] = None):
    client = get_admin_supabase()
    sale = await run_sync_db_call(
        client.table("sales")
        .select("total_amount, created_at, user_id, branch_id")
        .eq("id", sale_id)
        .maybe_single()
        .execute
    )
    if not sale.data:
        logger.warning(f"Sale {sale_id} not found for A/R creation")
        return

    existing = await run_sync_db_call(
        client.table("accounts_receivable")
        .select("id")
        .eq("sale_id", sale_id)
        .maybe_single()
        .execute
    )
    if existing and existing.data:
        logger.info(f"A/R already exists for sale {sale_id}, skipping")
        return

    due_date = (datetime.fromisoformat(sale.data["created_at"]) + timedelta(days=30)).date()
    ar_data = {
        "org_id": org_id,
        "branch_id": sale.data.get("branch_id"),
        "sale_id": sale_id,
        "customer_id": customer_id or sale.data.get("user_id"),
        "amount": sale.data["total_amount"],
        "paid_amount": 0,
        "status": "pending",
        "due_date": due_date.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await run_sync_db_call(client.table("accounts_receivable").insert(ar_data).execute)

    revenue_acc = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "revenue")
        .limit(1)
        .execute
    )
    ar_acc = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "asset")
        .ilike("name", "%accounts receivable%")
        .limit(1)
        .execute
    )
    if revenue_acc.data and ar_acc.data:
        lines = [
            {"account_id": ar_acc.data[0]["id"], "debit": sale.data["total_amount"], "credit": 0},
            {"account_id": revenue_acc.data[0]["id"], "debit": 0, "credit": sale.data["total_amount"]}
        ]
        await create_journal_entry(
            org_id=org_id,
            entry_date=date.today(),
            description=f"Sale {sale_id} revenue",
            lines=lines,
            reference=f"SALE-{sale_id[:8]}",
            created_by=customer_id or sale.data.get("user_id"),
            status="posted"
        )
    else:
        logger.warning(f"Missing revenue or A/R account for org {org_id} – journal entry skipped")

async def mark_ar_paid_for_sale(sale_id: str, org_id: str) -> Optional[str]:
    """
    Flip the A/R record for a given sale to status='paid' with
    paid_amount = amount. Idempotent: safe to call multiple times.
    Returns the A/R id on success, None if no record found.
    """
    client = get_admin_supabase()
    ar_res = await run_sync_db_call(
        client.table("accounts_receivable")
        .select("id, amount, paid_amount, status")
        .eq("sale_id", sale_id)
        .maybe_single()
        .execute
    )
    if not ar_res or not ar_res.data:
        logger.warning(f"mark_ar_paid_for_sale: no A/R record for sale {sale_id}")
        return None

    ar = ar_res.data
    if ar.get("status") == "paid":
        return ar["id"]  # already done, idempotent

    await run_sync_db_call(
        client.table("accounts_receivable")
        .update({
            "paid_amount": ar["amount"],
            "status": "paid",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", ar["id"])
        .execute
    )
    logger.info(f"A/R {ar['id']} marked paid for sale {sale_id} (₦{ar['amount']})")
    return ar["id"]



async def finalize_online_order(sale_id: str, org_id: str) -> Dict:
    """
    Call the finalize_online_order RPC. One round trip, one Postgres
    transaction. Returns:
        { success, skipped, sale_id, status, ar_id, short }
    """
    resp = await run_sync_db_call(
        get_supabase().rpc("finalize_online_order", {
            "p_sale_id": sale_id,
            "p_org_id":  org_id,
        }).execute
    )
    return resp.data or {}

async def create_ap_from_po(po_id: str, org_id: str, supplier_id: str):
    client = get_admin_supabase()
    po = await run_sync_db_call(
        client.table("purchase_orders")
        .select("total_amount, order_date, supplier_id, branch_id")
        .eq("id", po_id)
        .maybe_single()
        .execute
    )
    if not po.data:
        logger.warning(f"PO {po_id} not found for A/P creation")
        return

    existing = await run_sync_db_call(
        client.table("accounts_payable")
        .select("id")
        .eq("purchase_order_id", po_id)
        .maybe_single()
        .execute
    )
    if existing and existing.data:
        logger.info(f"A/P already exists for PO {po_id}, skipping")
        return

    due_date = (datetime.fromisoformat(po.data["order_date"]) + timedelta(days=30)).date()
    ap_data = {
        "org_id": org_id,
        "branch_id": po.data.get("branch_id"),
        "purchase_order_id": po_id,
        "supplier_id": supplier_id,
        "amount": po.data["total_amount"],
        "paid_amount": 0,
        "status": "pending",
        "due_date": due_date.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await run_sync_db_call(client.table("accounts_payable").insert(ap_data).execute)

    expense_acc = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "expense")
        .ilike("name", "%purchases%")
        .limit(1)
        .execute
    )
    ap_acc = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "liability")
        .ilike("name", "%accounts payable%")
        .limit(1)
        .execute
    )
    if not expense_acc.data:
        expense_acc = await run_sync_db_call(
            client.table("chart_of_accounts")
            .select("id")
            .eq("org_id", org_id)
            .eq("type", "expense")
            .limit(1)
            .execute
        )
    if expense_acc.data and ap_acc.data:
        lines = [
            {"account_id": expense_acc.data[0]["id"], "debit": po.data["total_amount"], "credit": 0},
            {"account_id": ap_acc.data[0]["id"], "debit": 0, "credit": po.data["total_amount"]}
        ]
        await create_journal_entry(
            org_id=org_id,
            entry_date=date.today(),
            description=f"Purchase Order {po_id} received",
            lines=lines,
            reference=f"PO-{po_id[:8]}",
            created_by=None,
            status="posted"
        )
    else:
        logger.warning(f"Missing expense or A/P account for org {org_id} – journal entry skipped")


async def create_ap_from_grn(grn_id: str, org_id: str):
    client = get_admin_supabase()

    grn = await run_sync_db_call(
        client.table("grn")
        .select("po_id, supplier_id, branch_id")
        .eq("id", grn_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not grn.data:
        logger.warning(f"GRN {grn_id} not found for A/P creation")
        return

    items = await run_sync_db_call(
        client.table("grn_items")
        .select("accepted_quantity, cost_price_naira")
        .eq("grn_id", grn_id)
        .execute
    )
    total_cost = sum(
        (item.get("accepted_quantity") or 0) * (item.get("cost_price_naira") or 0)
        for item in (items.data or [])
    )
    if total_cost == 0:
        logger.warning(f"GRN {grn_id} has zero total cost – skipping A/P")
        return

    existing = await run_sync_db_call(
        client.table("accounts_payable")
        .select("id")
        .eq("purchase_order_id", grn.data["po_id"])
        .eq("grn_id", grn_id)
        .maybe_single()
        .execute
    )
    if existing and existing.data:
        logger.info(f"A/P already exists for GRN {grn_id}, skipping")
        return

    due_date = (date.today() + timedelta(days=45))
    ap_data = {
        "org_id": org_id,
        "branch_id": grn.data.get("branch_id"),
        "purchase_order_id": grn.data["po_id"],
        "grn_id": grn_id,
        "supplier_id": grn.data["supplier_id"],
        "amount": total_cost,
        "paid_amount": 0,
        "status": "pending",
        "due_date": due_date.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await run_sync_db_call(client.table("accounts_payable").insert(ap_data).execute)

    inventory_acc = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "asset")
        .ilike("name", "%inventory%")
        .limit(1)
        .execute
    )
    ap_acc = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "liability")
        .ilike("name", "%accounts payable%")
        .limit(1)
        .execute
    )
    if not inventory_acc.data:
        inventory_acc = await run_sync_db_call(
            client.table("chart_of_accounts")
            .select("id")
            .eq("org_id", org_id)
            .eq("type", "asset")
            .limit(1)
            .execute
        )
    if not ap_acc.data:
        ap_acc = await run_sync_db_call(
            client.table("chart_of_accounts")
            .select("id")
            .eq("org_id", org_id)
            .eq("type", "liability")
            .limit(1)
            .execute
        )

    if inventory_acc.data and ap_acc.data:
        lines = [
            {"account_id": inventory_acc.data[0]["id"], "debit": total_cost, "credit": 0},
            {"account_id": ap_acc.data[0]["id"], "debit": 0, "credit": total_cost}
        ]
        await create_journal_entry(
            org_id=org_id,
            entry_date=date.today(),
            description=f"Purchase from GRN {grn_id}",
            lines=lines,
            reference=f"GRN-{grn_id[:8]}",
            created_by=None,
            status="posted"
        )
    else:
        logger.warning(f"Missing inventory or A/P account for org {org_id} – journal entry skipped")


# ===================== EXPIRY AND BATCH MANAGEMENT ENDPOINTS =====================
@app.get("/inventory/expiring-products")
@app.get("/inventory/expiring-products")
async def get_expiring_products(
    request: Request,
    days_threshold: int = Query(180, ge=1, le=365),
    alert_level: Optional[str] = Query(None),
    location_id: Optional[str] = None,
    limit: int = Query(500, ge=1, le=2000),
    user_data: Tuple[str, str, str] = Depends(
        require_feature("expiry_tracking", allowed_roles=["owner", "admin", "inventory_manager"])
    )
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    today = datetime.now(timezone.utc).date()
    threshold_date = today + timedelta(days=days_threshold)

    # !inner forces PostgREST to use an INNER JOIN. Combined with the
    # org_id filter on the joined table, this drops batches whose
    # inventory_id points at a deleted row or a foreign org at the
    # database — they never travel over the wire and never reach the
    # Python loop. Without !inner the join is LEFT, the filter on
    # inventory.org_id is decorative, and every orphan comes back with
    # "inventory": null.
    #
    # The explicit column list on the embed keeps the response small.
    # The limit caps the total row count regardless of how many
    # batches are in scope.
    query = client.table("inventory_batches") \
        .select(
            "*, "
            "inventory:inventory_id!inner(id, org_id, description, item_code, product_group)"
        ) \
        .eq("inventory.org_id", org_id) \
        .lte("expiry_date", threshold_date.isoformat()) \
        .gt("quantity", 0) \
        .order("expiry_date", desc=False) \
        .limit(limit)

    result = await run_sync_db_call(query.execute)

    if not result.data:
        return {"expiring_products": [], "summary": {"total_expiring": 0, "critical_count": 0, "warning_count": 0, "info_count": 0}}

    expiring_products = []
    critical_count = 0
    warning_count = 0
    info_count = 0

    for batch in result.data:
        inventory = batch.get("inventory")
        if inventory is None:
            # !inner should have filtered these out at the database.
            # Kept as a safety net for genuinely malformed rows.
            logger.warning(f"Skipping batch {batch.get('id')} with missing inventory reference")
            continue

        expiry_date = datetime.strptime(batch["expiry_date"], "%Y-%m-%d").date() if isinstance(batch["expiry_date"], str) else batch["expiry_date"]
        days_until = (expiry_date - today).days

        if days_until <= 90:
            level = "critical"
            critical_count += 1
        elif days_until <= 120:
            level = "warning"
            warning_count += 1
        elif days_until <= 180:
            level = "info"
            info_count += 1
        else:
            level = "good"

        if alert_level and level != alert_level:
            continue

        location_stock = None
        location_name = None
        location_id_val = None

        if location_id:
            stock_result = await run_sync_db_call(
                client.table("location_stocks")
                .select("location_id, locations(name)")
                .eq("batch_id", batch["id"])
                .eq("location_id", location_id)
                .maybe_single()
                .execute
            )
            if stock_result.data:
                location_id_val = location_id
                location_name = stock_result.data.get("locations", {}).get("name") if stock_result.data.get("locations") else None

        expiring_products.append({
            "inventory_id": inventory.get("id"),
            "product_name": inventory.get("description"),
            "product_code": inventory.get("item_code"),
            "batch_id": batch["id"],
            "batch_number": batch["batch_number"],
            "lot_number": batch.get("lot_number"),
            "expiry_date": batch["expiry_date"],
            "days_until_expiry": days_until,
            "alert_level": level,
            "current_stock": batch["quantity"],
            "manufacture_date": batch.get("manufacture_date"),
            "cost_price_naira": float(batch.get("cost_price_naira", 0)),
            "location_id": location_id_val,
            "location_name": location_name
        })

    return {
        "expiring_products": expiring_products,
        "summary": {
            "total_expiring": len(expiring_products),
            "critical_count": critical_count,
            "warning_count": warning_count,
            "info_count": info_count
        },
        "threshold_days": days_threshold,
        "truncated": len(result.data) >= limit
    }

@app.get("/inventory/batches/{inventory_id}")
async def get_inventory_batches(
    request: Request,
    inventory_id: int,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "sales_rep"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    inventory = await run_sync_db_call(
        client.table("inventory")
        .select("id")
        .eq("id", inventory_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )

    if not inventory.data:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    batches = await run_sync_db_call(
        client.table("inventory_batches")
        .select("*")
        .eq("inventory_id", inventory_id)
        .order("expiry_date", desc=False)
        .execute
    )

    today = datetime.now(timezone.utc).date()
    for batch in (batches.data or []):
        expiry_date = datetime.strptime(batch["expiry_date"], "%Y-%m-%d").date() if isinstance(batch["expiry_date"], str) else batch["expiry_date"]
        days_until = (expiry_date - today).days

        if days_until <= 120:
            batch["alert_level"] = "critical"
        elif days_until <= 180:
            batch["alert_level"] = "warning"
        elif days_until <= 240:
            batch["alert_level"] = "info"
        else:
            batch["alert_level"] = "good"
        batch["days_until_expiry"] = days_until

    return {"batches": batches.data or [], "inventory_id": inventory_id}

@app.post("/inventory/batches")
async def add_inventory_batch(
    request: Request,
    inventory_id: int,
    batch: BatchEntry,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    inventory = await run_sync_db_call(
        client.table("inventory")
        .select("id, current_qty, description")
        .eq("id", inventory_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )

    if not inventory.data:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    existing = await run_sync_db_call(
        client.table("inventory_batches")
        .select("id")
        .eq("inventory_id", inventory_id)
        .eq("batch_number", batch.batch_number)
        .maybe_single()
        .execute
    )

    if existing and existing.data:
        raise HTTPException(status_code=400, detail=f"Batch number {batch.batch_number} already exists for this product")

    try:
        expiry_date_obj = datetime.strptime(batch.expiry_date, "%Y-%m-%d").date()
        if expiry_date_obj <= datetime.now(timezone.utc).date():
            raise HTTPException(status_code=400, detail="Expiry date must be in the future")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid expiry date format. Use YYYY-MM-DD")

    batch_data = {
        "inventory_id": inventory_id,
        "batch_number": batch.batch_number,
        "lot_number": batch.lot_number,
        "quantity": batch.quantity,
        "expiry_date": batch.expiry_date,
        "manufacture_date": batch.manufacture_date,
        "cost_price_naira": batch.cost_price_naira,
        "supplier_name": batch.supplier_name,
        "supplier_invoice": batch.supplier_invoice,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    result = await run_sync_db_call(client.table("inventory_batches").insert(batch_data).execute)

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create batch")

    new_total_qty = inventory.data["current_qty"] + batch.quantity
    await run_sync_db_call(client.table("inventory").update({"current_qty": new_total_qty}).eq("id", inventory_id).execute)

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
            stock_exists = await run_sync_db_call(
                client.table("location_stocks")
                .select("id")
                .eq("location_id", main_location.data["id"])
                .eq("inventory_id", inventory_id)
                .eq("batch_id", result.data[0]["id"])
                .maybe_single()
                .execute
            )

            if stock_exists.data:
                await run_sync_db_call(
                    client.table("location_stocks").update({
                        "quantity": stock_exists.data["quantity"] + batch.quantity,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }).eq("id", stock_exists.data["id"]).execute
                )
            else:
                await run_sync_db_call(
                    client.table("location_stocks").insert({
                        "location_id": main_location.data["id"],
                        "inventory_id": inventory_id,
                        "batch_id": result.data[0]["id"],
                        "quantity": batch.quantity,
                        "reserved_quantity": 0,
                        "expiry_date": batch.expiry_date,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }).execute
                )
    except Exception as loc_err:
        logger.warning(f"Failed to assign batch to location: {loc_err}")

    days_until = (expiry_date_obj - datetime.now(timezone.utc).date()).days
    if days_until <= 90:
        await run_sync_db_call(
            client.table("expiry_alert_log").insert({
                "inventory_id": inventory_id,
                "batch_id": result.data[0]["id"],
                "expiry_date": batch.expiry_date,
                "alert_level": "critical" if days_until <= 90 else "warning" if days_until <= 120 else "info",
                "notes": f"Batch {batch.batch_number} added with expiry in {days_until} days"
            }).execute
        )

    return {
        "message": f"Batch {batch.batch_number} added successfully",
        "batch": result.data[0],
        "new_total_quantity": new_total_qty
    }

@app.put("/inventory/batches/{batch_id}/quantity")
async def update_batch_quantity(
    request: Request,
    batch_id: int,
    quantity_adjustment: int,
    reason: str = "manual_adjustment",
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    batch = await run_sync_db_call(
        client.table("inventory_batches")
        .select("*, inventory:inventory_id(org_id, description)")
        .eq("id", batch_id)
        .maybe_single()
        .execute
    )

    if not batch.data:
        raise HTTPException(status_code=404, detail="Batch not found")

    if batch.data.get("inventory", {}).get("org_id") != org_id:
        raise HTTPException(status_code=403, detail="Access denied to this batch")

    new_quantity = batch.data["quantity"] + quantity_adjustment

    if new_quantity < 0:
        raise HTTPException(status_code=400, detail=f"Cannot reduce quantity below 0. Current: {batch.data['quantity']}")

    result = await run_sync_db_call(
        client.table("inventory_batches").update({
            "quantity": new_quantity,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", batch_id).execute
    )

    total_qty_result = await run_sync_db_call(
        client.table("inventory_batches")
        .select("quantity")
        .eq("inventory_id", batch.data["inventory_id"])
        .execute
    )

    total_qty = sum(b["quantity"] for b in (total_qty_result.data or []))
    await run_sync_db_call(client.table("inventory").update({"current_qty": total_qty}).eq("id", batch.data["inventory_id"]).execute)

    if quantity_adjustment < 0 and reason in ["damaged", "expired", "waste"]:
        await run_sync_db_call(
            client.table("expiry_alert_log").insert({
                "inventory_id": batch.data["inventory_id"],
                "batch_id": batch_id,
                "expiry_date": batch.data["expiry_date"],
                "alert_level": "critical",
                "notes": f"Quantity reduced by {abs(quantity_adjustment)} due to {reason}"
            }).execute
        )

    return {
        "message": f"Batch quantity updated",
        "old_quantity": batch.data["quantity"],
        "new_quantity": new_quantity,
        "adjustment": quantity_adjustment,
        "total_inventory_quantity": total_qty
    }

@app.get("/inventory/expiry-fefo-recommendations")
async def get_fefo_recommendations(
    request: Request,
    inventory_id: Optional[int] = None,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "sales_rep"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    query = client.table("inventory_batches") \
        .select("*, inventory:inventory_id(*)") \
        .gt("quantity", 0) \
        .eq("inventory.org_id", org_id) \
        .order("expiry_date", desc=False)

    if inventory_id:
        query = query.eq("inventory_id", inventory_id)

    result = await run_sync_db_call(query.execute)

    if not result.data:
        return {"recommendations": [], "message": "No batches with stock found"}

    recommendations = []
    today = datetime.now(timezone.utc).date()

    for batch in result.data:
        inventory = batch.get("inventory")
        if inventory is None:
            continue
        expiry_date = datetime.strptime(batch["expiry_date"], "%Y-%m-%d").date() if isinstance(batch["expiry_date"], str) else batch["expiry_date"]
        days_until = (expiry_date - today).days

        if days_until <= 90:
            priority = "URGENT - Must sell immediately"
            color_code = "red"
        elif days_until <= 120:
            priority = "HIGH - Priority sell"
            color_code = "orange"
        elif days_until <= 180:
            priority = "MEDIUM - Monitor closely"
            color_code = "yellow"
        else:
            priority = "LOW - OK"
            color_code = "green"

        recommendations.append({
            "inventory_id": inventory.get("id"),
            "product_name": inventory.get("description"),
            "product_code": inventory.get("item_code"),
            "batch_id": batch["id"],
            "batch_number": batch["batch_number"],
            "expiry_date": batch["expiry_date"],
            "days_until_expiry": days_until,
            "quantity_available": batch["quantity"],
            "priority": priority,
            "priority_color": color_code,
            "recommended_action": _get_fefo_action(days_until),
            "cost_price": float(batch.get("cost_price_naira", 0))
        })

    return {
        "recommendations": recommendations,
        "total_batches": len(recommendations),
        "fefo_principle": "First Expiry First Out - Always pick batches with earliest expiry dates first",
        "critical_batches_count": sum(1 for r in recommendations if r["days_until_expiry"] <= 90)
    }

def _get_fefo_action(days_until: int) -> str:
    if days_until <= 30:
        return "⚠️ IMMEDIATE ACTION: Run flash sale / Donate / Return to supplier"
    elif days_until <= 60:
        return "🔴 URGENT: Bundle with bestsellers / Offer discount"
    elif days_until <= 90:
        return "🟠 CRITICAL: Create promotion / Move to front of store"
    elif days_until <= 120:
        return "🟡 Plan promotion within 30 days"
    else:
        return "✅ Monitor regularly"

@app.post("/inventory/transfer-batch")
async def transfer_batch_between_locations(
    request: Request,
    transfer: BatchTransferRequest,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    batch = await run_sync_db_call(
        client.table("inventory_batches")
        .select("*, inventory:inventory_id(org_id)")
        .eq("id", transfer.batch_id)
        .maybe_single()
        .execute
    )

    if not batch.data:
        raise HTTPException(status_code=404, detail="Batch not found")

    if batch.data.get("inventory", {}).get("org_id") != org_id:
        raise HTTPException(status_code=403, detail="Access denied to this batch")

    if batch.data["quantity"] < transfer.quantity:
        raise HTTPException(status_code=400, detail=f"Insufficient quantity in batch. Available: {batch.data['quantity']}")

    from_loc = await run_sync_db_call(client.table("locations").select("id").eq("id", transfer.from_location_id).eq("org_id", org_id).maybe_single().execute)
    if not from_loc.data:
        raise HTTPException(status_code=404, detail="Source location not found")

    to_loc = await run_sync_db_call(client.table("locations").select("id").eq("id", transfer.to_location_id).eq("org_id", org_id).maybe_single().execute)
    if not to_loc.data:
        raise HTTPException(status_code=404, detail="Destination location not found")

    source_stock = await run_sync_db_call(
        client.table("location_stocks")
        .select("id, quantity")
        .eq("location_id", transfer.from_location_id)
        .eq("batch_id", transfer.batch_id)
        .maybe_single()
        .execute
    )

    if source_stock.data:
        new_source_qty = source_stock.data["quantity"] - transfer.quantity
        if new_source_qty < 0:
            raise HTTPException(status_code=400, detail="Insufficient stock at source location")

        if new_source_qty == 0:
            await run_sync_db_call(client.table("location_stocks").delete().eq("id", source_stock.data["id"]).execute)
        else:
            await run_sync_db_call(
                client.table("location_stocks").update({
                    "quantity": new_source_qty,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", source_stock.data["id"]).execute
            )

    dest_stock = await run_sync_db_call(
        client.table("location_stocks")
        .select("id, quantity")
        .eq("location_id", transfer.to_location_id)
        .eq("batch_id", transfer.batch_id)
        .maybe_single()
        .execute
    )

    if dest_stock.data:
        await run_sync_db_call(
            client.table("location_stocks").update({
                "quantity": dest_stock.data["quantity"] + transfer.quantity,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", dest_stock.data["id"]).execute
        )
    else:
        await run_sync_db_call(
            client.table("location_stocks").insert({
                "location_id": transfer.to_location_id,
                "inventory_id": batch.data["inventory_id"],
                "batch_id": transfer.batch_id,
                "quantity": transfer.quantity,
                "reserved_quantity": 0,
                "expiry_date": batch.data["expiry_date"],
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).execute
        )

    return {
        "message": f"Transferred {transfer.quantity} units of batch {batch.data['batch_number']}",
        "from_location_id": transfer.from_location_id,
        "to_location_id": transfer.to_location_id,
        "batch_id": transfer.batch_id,
        "quantity": transfer.quantity
    }

@app.get("/inventory/expiry-dashboard")
async def expiry_dashboard(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(
        require_feature("expiry_tracking", allowed_roles=["owner", "admin", "inventory_manager"])
    )
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    today = datetime.now(timezone.utc).date()

    batches = await run_sync_db_call(
        client.table("inventory_batches")
        .select("*, inventory:inventory_id!inner(description, item_code, product_group)")
        .eq("inventory.org_id", org_id)
        .execute
    )

    stats = {
        "total_batches": len(batches.data) if batches.data else 0,
        "critical_expiring_30d": 0,
        "critical_expiring_60d": 0,
        "warning_expiring_90d": 0,
        "info_expiring_180d": 0,
        "expired_stock": 0,
        "total_at_risk_value": 0.0,
        "products_by_category": {},
        "recommendations": []
    }

    if batches.data:
        for batch in batches.data:
            inventory = batch.get("inventory")
            if inventory is None:
                continue
            expiry_date = datetime.strptime(batch["expiry_date"], "%Y-%m-%d").date() if isinstance(batch["expiry_date"], str) else batch["expiry_date"]
            days_until = (expiry_date - today).days

            if days_until < 0:
                stats["expired_stock"] += batch["quantity"]
            elif days_until <= 30:
                stats["critical_expiring_30d"] += batch["quantity"]
                stats["total_at_risk_value"] += batch["quantity"] * float(batch.get("cost_price_naira", 0))
            elif days_until <= 60:
                stats["critical_expiring_60d"] += batch["quantity"]
                stats["total_at_risk_value"] += batch["quantity"] * float(batch.get("cost_price_naira", 0)) * 0.7
            elif days_until <= 90:
                stats["warning_expiring_90d"] += batch["quantity"]
                stats["total_at_risk_value"] += batch["quantity"] * float(batch.get("cost_price_naira", 0)) * 0.5
            elif days_until <= 180:
                stats["info_expiring_180d"] += batch["quantity"]

            product_group = inventory.get("product_group", "Uncategorized")
            if product_group not in stats["products_by_category"]:
                stats["products_by_category"][product_group] = {"total_quantity": 0, "expiring_soon": 0}
            stats["products_by_category"][product_group]["total_quantity"] += batch["quantity"]
            if days_until <= 90:
                stats["products_by_category"][product_group]["expiring_soon"] += batch["quantity"]

    if stats["critical_expiring_30d"] > 0:
        stats["recommendations"].append({
            "type": "urgent",
            "message": f"⚠️ {stats['critical_expiring_30d']} units expiring within 30 days! Immediate action required.",
            "action": "Run flash sale, create bundles, or consider donation"
        })

    if stats["expired_stock"] > 0:
        stats["recommendations"].append({
            "type": "critical",
            "message": f"❌ {stats['expired_stock']} units have expired and must be disposed.",
            "action": "Remove from inventory and update stock records"
        })

    stats["recommendations"].append({
        "type": "best_practice",
        "message": "📦 FEFO (First Expiry First Out) is recommended for shelf stacking",
        "action": "Always pick batches with earliest expiry dates first during order fulfillment"
    })

    stats["total_at_risk_value"] = round(stats["total_at_risk_value"], 2)

    return {"dashboard": stats, "as_of_date": today.isoformat()}

# ------------------------------------------------------------------
# SALES SUMMARY & TREND
# ------------------------------------------------------------------
@app.get("/sales/product-stats")
async def product_stats(request: Request, start_date: str, end_date: str, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    items_result = await run_sync_db_call(
        client.table("sale_items")
        .select("product_name, quantity, subtotal, inventory_id, sales!inner(org_id, created_at)")
        .eq("sales.org_id", org_id)
        .gte("sales.created_at", start_date)
        .lte("sales.created_at", end_date)
        .execute
    )
    items_data = items_result.data if hasattr(items_result, 'data') else []

    if not items_data:
        return {"product_stats": []}

    inventory_ids = list(set([it["inventory_id"] for it in items_data if it.get("inventory_id")]))
    inv_query = await run_sync_db_call(client.table("inventory").select("id, cost_price_naira").in_("id", inventory_ids).execute)
    inv_data = inv_query.data if hasattr(inv_query, 'data') else []
    cost_map = {row["id"]: float(row["cost_price_naira"]) for row in inv_data}

    aggregated = {}
    for it in items_data:
        name = it["product_name"]
        qty = int(it["quantity"])
        subtotal = float(it["subtotal"])
        inv_id = it.get("inventory_id")
        unit_cost = cost_map.get(inv_id, 0.0)
        total_cogs = unit_cost * qty
        gross_profit = subtotal - total_cogs

        if name not in aggregated:
            aggregated[name] = {
                "quantity_sold": 0,
                "revenue": 0.0,
                "cost_of_goods_sold": 0.0,
                "gross_profit": 0.0
            }
        aggregated[name]["quantity_sold"] += qty
        aggregated[name]["revenue"] += subtotal
        aggregated[name]["cost_of_goods_sold"] += total_cogs
        aggregated[name]["gross_profit"] += gross_profit

    product_stats_list = []
    for name, vals in aggregated.items():
        product_stats_list.append({
            "product_name": name,
            "quantity_sold": vals["quantity_sold"],
            "revenue": round(vals["revenue"], 2),
            "cost_of_goods_sold": round(vals["cost_of_goods_sold"], 2),
            "gross_profit": round(vals["gross_profit"], 2),
            "profit_margin_pct": round((vals["gross_profit"] / vals["revenue"]) * 100, 2) if vals["revenue"] > 0 else 0.0
        })
    return {"product_stats": product_stats_list}

@app.get("/sales/summary")
async def sales_summary(request: Request, start_date: str, end_date: str, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    sales_result = await run_sync_db_call(
        client.table("sales").select("id, total_amount")
        .eq("org_id", org_id)
        .gte("created_at", start_date)
        .lte("created_at", end_date)
        .execute
    )
    sales_data = sales_result.data if hasattr(sales_result, 'data') else []

    if not sales_data:
        return {"total_revenue": 0, "total_cogs": 0, "total_profit": 0, "count": 0}

    items_result = await run_sync_db_call(
        client.table("sale_items")
        .select("quantity, subtotal, inventory_id, sales!inner(org_id, created_at)")
        .eq("sales.org_id", org_id)
        .gte("sales.created_at", start_date)
        .lte("sales.created_at", end_date)
        .execute
    )
    items_data = items_result.data if hasattr(items_result, 'data') else []

    inv_ids = list(set([it["inventory_id"] for it in items_data if it.get("inventory_id")]))
    inv_res = await run_sync_db_call(client.table("inventory").select("id, cost_price_naira").in_("id", inv_ids).execute)
    inv_map = {row["id"]: float(row["cost_price_naira"]) for row in (inv_res.data or [])}

    total_cogs = 0.0
    for it in items_data:
        unit_cost = inv_map.get(it["inventory_id"], 0.0)
        total_cogs += unit_cost * it["quantity"]

    total_rev = sum(float(s["total_amount"]) for s in sales_data)
    total_profit = total_rev - total_cogs

    return {
        "total_revenue": round(total_rev, 2),
        "total_cogs": round(total_cogs, 2),
        "total_profit": round(total_profit, 2),
        "count": len(sales_data)
    }

@app.get("/sales/trend")
async def sales_trend(request: Request, days: int = 30, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = await run_sync_db_call(
        client.table("sales").select("total_amount, created_at")
        .eq("org_id", org_id)
        .gte("created_at", start_date)
        .order("created_at", desc=False)
        .execute
    )
    daily = {}
    for s in result.data:
        date_str = s["created_at"][:10]
        daily[date_str] = daily.get(date_str, 0) + s["total_amount"]
    trend = [{"date": d, "revenue": daily[d]} for d in sorted(daily.keys())]
    return trend

# ------------------------------------------------------------------
# LEADS
# ------------------------------------------------------------------
class LeadCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    status: str = "cold"
    deal_value: Optional[float] = None
    ad_spend: Optional[float] = None
    notes: Optional[str] = None
    acquired_date: Optional[str] = None

class LeadUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    deal_value: Optional[float] = None
    ad_spend: Optional[float] = None
    notes: Optional[str] = None
    conversion_date: Optional[str] = None

@app.post("/leads/upload")
async def upload_leads_csv(
    request: Request,
    file: UploadFile = File(...),
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")
    try:
        contents = await file.read()
        try:
            decoded_content = contents.decode('utf-8')
        except UnicodeDecodeError:
            decoded_content = contents.decode('latin-1')
        csv_reader = csv.DictReader(io.StringIO(decoded_content))
        leads_to_insert = []
        branch_id_for_upload = await resolve_branch_for_write(org_id)
        for row in csv_reader:
            name = row.get("name", "").strip()
            if not name:
                continue
            status = row.get("status", "cold").strip().lower()
            if status not in ["cold", "warm", "converted"]:
                status = "cold"
            def safe_float(val):
                if not val or str(val).strip() == "":
                    return None
                try:
                    return float(str(val).replace(",", "").strip())
                except ValueError:
                    return None
            def safe_date(val):
                clean_val = str(val).strip() if val else ""
                if not clean_val or clean_val.lower() == "null":
                    return None
                return clean_val
            lead_data = {
                "org_id": org_id,
                "branch_id": branch_id_for_upload,
                "name": name,
                "email": row.get("email", "").strip() or None,
                "phone": row.get("phone", "").strip() or None,
                "source": row.get("source", "").strip() or None,
                "status": status,
                "deal_value": safe_float(row.get("deal_value")),
                "ad_spend": safe_float(row.get("ad_spend")),
                "notes": row.get("notes", "").strip() or None,
                "acquired_date": safe_date(row.get("acquired_date")),
                "conversion_date": safe_date(row.get("conversion_date")),
            }
            leads_to_insert.append(lead_data)
        if not leads_to_insert:
            return {"message": "Uploaded 0 leads. No valid rows containing a 'name' field were found.", "leads": []}
        result = await run_sync_db_call(get_supabase().table("org_leads").insert(leads_to_insert).execute)
        inserted_records = result.data if hasattr(result, 'data') else []
        logger.info(f"Successfully batch-inserted {len(inserted_records)} leads")
        return {"message": f"Successfully uploaded {len(inserted_records)} leads.", "count": len(inserted_records)}
    except Exception as e:
        logger.error(f"Error parsing CSV: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"CSV processing failed: {str(e)}")

@app.get("/leads")
async def get_leads(
    request: Request,
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    query = client.table("org_leads").select("*").eq("org_id", org_id)
    if status:
        query = query.eq("status", status)
    if source:
        query = query.eq("source", source)
    result = await run_sync_db_call(query.order("created_at", desc=True).range(offset, offset + limit - 1).execute)
    return {"leads": result.data}

@app.post("/leads")
async def create_lead(request: Request, lead: LeadCreate, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    data = lead.dict()
    data["org_id"] = org_id
    data["branch_id"] = await resolve_branch_for_write(org_id)
    if not data.get("acquired_date"):
        data["acquired_date"] = datetime.now(timezone.utc).date().isoformat()
    result = await run_sync_db_call(client.table("org_leads").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create lead")
    return result.data[0]

@app.patch("/leads/{lead_id}")
async def update_lead(request: Request, lead_id: str, lead: LeadUpdate, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    data = {k: v for k, v in lead.dict().items() if v is not None}
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(client.table("org_leads").update(data).eq("id", lead_id).eq("org_id", org_id).execute)
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    return result.data[0]

@app.delete("/leads/{lead_id}")
async def delete_lead(request: Request, lead_id: str, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    result = await run_sync_db_call(client.table("org_leads").delete().eq("id", lead_id).eq("org_id", org_id).execute)
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"message": "Lead deleted"}

@app.get("/leads/metrics")
async def get_lead_metrics(request: Request, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep", "finance"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    leads = await run_sync_db_call(client.table("org_leads").select("*").eq("org_id", org_id).execute)
    total = len(leads.data)
    converted = sum(1 for l in leads.data if l.get("status") == "converted")
    conversion_rate = round((converted / total) * 100, 2) if total > 0 else 0
    pipeline = sum(l.get("deal_value", 0) for l in leads.data if l.get("status") in ["warm", "converted"])
    total_ad_spend = sum(l.get("ad_spend", 0) for l in leads.data if l.get("status") == "converted")
    cac = total_ad_spend / converted if converted > 0 else 0
    total_deal = sum(l.get("deal_value", 0) for l in leads.data if l.get("status") == "converted")
    roi = ((total_deal - total_ad_spend) / total_ad_spend) * 100 if total_ad_spend > 0 else 0
    complete = sum(1 for l in leads.data if l.get("name") and l.get("email") and l.get("phone"))
    data_quality = round((complete / total) * 100, 2) if total > 0 else 0
    source_stats = {}
    for l in leads.data:
        src = l.get("source", "unknown")
        if src not in source_stats:
            source_stats[src] = {"total": 0, "converted": 0}
        source_stats[src]["total"] += 1
        if l.get("status") == "converted":
            source_stats[src]["converted"] += 1
    top_sources = [
        {"source": s, "total": stats["total"], "converted": stats["converted"], "conv_rate": round((stats["converted"]/stats["total"])*100,2) if stats["total"]>0 else 0}
        for s, stats in source_stats.items()
    ]
    top_sources.sort(key=lambda x: x["conv_rate"], reverse=True)
    return {
        "metrics": {
            "total_leads": total,
            "conversion_rate": conversion_rate,
            "actual_cac": round(cac, 2),
            "roi": round(roi, 2),
            "pipeline_value": round(pipeline, 2),
            "data_quality": data_quality
        },
        "top_sources": top_sources[:5]
    }

# ------------------------------------------------------------------
# FORECAST & CAC TARGET
# ------------------------------------------------------------------
class ForecastRequest(BaseModel):
    months: int = 6
    target_growth_rate: Optional[float] = None
    additional_ad_spend: Optional[float] = None

@app.post("/analytics/forecast")
async def forecast(request: Request, req: ForecastRequest, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    sales = await run_sync_db_call(client.table("sales").select("total_amount, sale_date").eq("org_id", org_id).eq("status", "completed").order("sale_date", desc=True).limit(10).execute)
    if sales.data and len(sales.data) >= 3:
        amounts = [s["total_amount"] for s in sales.data[-3:]]
        base_revenue = amounts[-1]
    else:
        base_revenue = 50000
    growth = req.target_growth_rate if req.target_growth_rate is not None else 5
    forecast_data = []
    cumulative = 0
    current_rev = base_revenue
    for m in range(1, req.months + 1):
        if req.additional_ad_spend and m == 1:
            current_rev += req.additional_ad_spend * 0.3
        else:
            current_rev = current_rev * (1 + growth/100)
        leads_gen = int(current_rev / (5000 if current_rev > 0 else 1))
        conv = int(leads_gen * 0.15)
        cumulative += current_rev
        forecast_data.append({
            "month": m,
            "revenue": round(current_rev, 2),
            "leads_generated": leads_gen,
            "conversions": conv,
            "cumulative_revenue": round(cumulative, 2)
        })
    return {"forecast": forecast_data}

class CACRequest(BaseModel):
    target_cac: float
    target_revenue: Optional[float] = None
    available_budget: Optional[float] = None

@app.post("/leads/cac-target")
async def cac_target(request: Request, req: CACRequest, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    sales_data = await run_sync_db_call(client.table("sales").select("total_amount").eq("org_id", org_id).eq("status", "completed").execute)
    if sales_data.data and len(sales_data.data) > 0:
        total_historical_revenue = sum(s["total_amount"] for s in sales_data.data)
        average_order_value = total_historical_revenue / len(sales_data.data)
    else:
        average_order_value = 5000.0
    leads = await run_sync_db_call(client.table("org_leads").select("*").eq("org_id", org_id).execute)
    total_ad_spend = sum(l.get("ad_spend", 0) for l in leads.data)
    converted = sum(1 for l in leads.data if l.get("status") == "converted")
    current_cac = total_ad_spend / converted if converted > 0 else 0
    result = {"current_cac": round(current_cac, 2), "target_cac": req.target_cac}
    if req.available_budget:
        leads_needed = req.available_budget / req.target_cac if req.target_cac > 0 else 0
        result["budget_scenario"] = {
            "leads_to_acquire": round(leads_needed),
            "expected_revenue": round(leads_needed * average_order_value, 2)
        }
    if req.target_revenue:
        conversions_needed = req.target_revenue / average_order_value if average_order_value > 0 else 0
        leads_needed = conversions_needed / 0.15 if 0.15 > 0 else 0
        result["revenue_scenario"] = {
            "conversions_needed": round(conversions_needed),
            "leads_needed": round(leads_needed)
        }
    advisory = f"Based on your dynamic Average Order Value of ₦{average_order_value:,.2f}: To reach target CAC of ₦{req.target_cac}, you need to optimize ad spend. Current CAC: ₦{current_cac}."
    if current_cac > req.target_cac:
        advisory += " Consider segmenting high-value user categories or refining your lead sources."
    else:
        advisory += " Performance metrics look strong! Your current acquisition cost remains below your target ceiling."
    return {"analysis": result, "advisory": advisory}

# ------------------------------------------------------------------
# SUPPORT TICKETS
# ------------------------------------------------------------------
class TicketCreate(BaseModel):
    subject: str
    priority: str = "normal"
    message: str

@app.post("/api/support/ticket")
async def create_ticket(request: Request, ticket: TicketCreate, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support", "customer"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()
    ticket_data = {
        "user_id": user_id,
        "org_id": org_id,
        "branch_id": await resolve_branch_for_write(org_id),
        "subject": ticket.subject,
        "priority": ticket.priority,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    res = await run_sync_db_call(client.table("support_tickets").insert(ticket_data).execute)
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create ticket")
    ticket_id = res.data[0]["id"]
    await run_sync_db_call(
        client.table("ticket_messages").insert({
            "ticket_id": ticket_id,
            "sender_type": "user",
            "sender_id": user_id,
            "message": ticket.message,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute
    )
    return {"ticket_id": ticket_id, "confirmation": f"Ticket #{ticket_id[:8]} created"}

@app.get("/support/tickets")
async def get_tickets(request: Request, status: Optional[str] = None, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support", "customer"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()
    query = client.table("support_tickets").select("*").eq("org_id", org_id).eq("user_id", user_id)
    if status:
        query = query.eq("status", status)
    result = await run_sync_db_call(query.order("created_at", desc=True).execute)
    return {"tickets": result.data}

@app.get("/support/tickets/{ticket_id}")
async def get_ticket_detail(request: Request, ticket_id: str, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support", "customer"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()
    ticket = await run_sync_db_call(client.table("support_tickets").select("*").eq("id", ticket_id).eq("org_id", org_id).eq("user_id", user_id).maybe_single().execute)
    if not ticket or not ticket.data:
        raise HTTPException(status_code=404, detail="Ticket not found")
    messages = await run_sync_db_call(client.table("ticket_messages").select("*").eq("ticket_id", ticket_id).order("created_at", desc=False).execute)
    return {"ticket": ticket.data, "messages": messages.data}

class TicketMessageReq(BaseModel):
    message: str

@app.post("/support/tickets/{ticket_id}/message")
async def add_ticket_message(request: Request, ticket_id: str, msg: TicketMessageReq, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support", "customer"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()
    ticket = await run_sync_db_call(client.table("support_tickets").select("id").eq("id", ticket_id).eq("org_id", org_id).eq("user_id", user_id).maybe_single().execute)
    if not ticket or not ticket.data:
        raise HTTPException(status_code=404, detail="Ticket not found")
    await run_sync_db_call(
        client.table("ticket_messages").insert({
            "ticket_id": ticket_id,
            "sender_type": "agent",
            "sender_id": user_id,
            "message": msg.message,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute
    )
    messages = await run_sync_db_call(client.table("ticket_messages").select("*").eq("ticket_id", ticket_id).order("created_at", desc=False).execute)
    return {"messages": messages.data}

class ResolveReq(BaseModel):
    resolution_notes: str

@app.post("/support/tickets/{ticket_id}/resolve")
async def resolve_ticket(request: Request, ticket_id: str, req: ResolveReq, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()
    await run_sync_db_call(
        client.table("support_tickets").update({
            "status": "resolved",
            "resolution_notes": req.resolution_notes,
            "resolved_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", ticket_id).eq("org_id", org_id).eq("user_id", user_id).execute
    )
    return {"message": "Ticket resolved"}

# ------------------------------------------------------------------
# IMMUTABLE AUDIT LOG ENDPOINTS
# ------------------------------------------------------------------
@app.post("/api/audit/event")
async def create_audit_event(
    request: Request,
    event: AuditEventIn,
    user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)
):
    user_id, org_id, role = user_data

    local_created_at = event.local_created_at.isoformat() if event.local_created_at else None

    enriched = {
        "event_type": event.event_type,
        "event_version": event.event_version,
        "payload": event.payload,
        "user_id": user_id,
        "org_id": org_id,
        "session_id": request.headers.get("X-Session-ID") or str(uuid.uuid4()),
        "source_ip": get_client_ip(request),
        "user_agent": request.headers.get("User-Agent"),
        "local_created_at": local_created_at,
    }

    client = get_supabase()
    try:
        result = await run_sync_db_call(
            client.table("audit_events").insert(enriched).execute
        )
        inserted = result.data[0] if result.data else None
        return {"status": "ok", "id": inserted["id"], "hash": inserted["hash"]}
    except Exception as e:
        logger.error(f"Audit insert failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to log event")

@app.post("/api/audit/events")
async def create_audit_events_batch(
    request: Request,
    batch: AuditEventBatchIn,
    user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)
):
    user_id, org_id, role = user_data
    now = datetime.now(timezone.utc)

    records = []
    for ev in batch.events:
        local_created_at = ev.local_created_at.isoformat() if ev.local_created_at else now.isoformat()
        records.append({
            "event_type": ev.event_type,
            "event_version": ev.event_version,
            "payload": ev.payload,
            "user_id": user_id,
            "org_id": org_id,
            "session_id": request.headers.get("X-Session-ID") or str(uuid.uuid4()),
            "source_ip": get_client_ip(request),
            "user_agent": request.headers.get("User-Agent"),
            "local_created_at": local_created_at,
        })

    client = get_supabase()
    try:
        result = await run_sync_db_call(
            client.table("audit_events").insert(records).execute
        )
        return {"status": "ok", "count": len(result.data)}
    except Exception as e:
        logger.error(f"Batch audit insert failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to log events")

# ===================== CUSTOMER CONTEXT =====================
@app.get("/support/customer-context")
async def customer_context(request: Request, target_user_id: Optional[str] = None, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    current_user_id, org_id, _ = user_data
    user_id = target_user_id if target_user_id else current_user_id
    client = get_supabase()
    try:
        if user_id == current_user_id:
            profile = await run_sync_db_call(client.table("profiles").select("*").eq("id", user_id).maybe_single().execute)
            loyalty = None
            if profile and profile.data and profile.data.get("membership_id"):
                try:
                    loyalty = await run_sync_db_call(client.table("customer_points_summary").select("*").eq("membership_id", profile.data["membership_id"]).maybe_single().execute)
                except Exception as e:
                    logger.warning(f"Loyalty table may not exist: {e}")
            return {"profile": profile.data if profile else None, "loyalty": loyalty.data if loyalty else None}
        membership = await run_sync_db_call(client.table("org_members").select("org_id").eq("user_id", user_id).maybe_single().execute)
        if not membership or not membership.data or membership.data["org_id"] != org_id:
            raise HTTPException(status_code=403, detail="Not authorised to access this user's data")
        profile = await run_sync_db_call(client.table("profiles").select("*").eq("id", user_id).maybe_single().execute)
        loyalty = None
        if profile and profile.data and profile.data.get("membership_id"):
            try:
                loyalty = await run_sync_db_call(client.table("customer_points_summary").select("*").eq("membership_id", profile.data["membership_id"]).maybe_single().execute)
            except Exception as e:
                logger.warning(f"Loyalty table may not exist: {e}")
        return {"profile": profile.data if profile else None, "loyalty": loyalty.data if loyalty else None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Customer context error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch customer context")

# ------------------------------------------------------------------
# MULTI‑GATEWAY PAYMENT SYSTEM (Adapter Pattern)
# ------------------------------------------------------------------
class PaymentGatewayAdapter(ABC):
    @abstractmethod
    async def initialize_transaction(self, email: str, amount_naira: float, reference: str, metadata: dict, subaccount_code: Optional[str] = None, callback_url: Optional[str] = None) -> Dict:
        pass

    @abstractmethod
    def verify_webhook_signature(self, raw_body: bytes, signature_header: str) -> bool:
        pass

class PaystackGateway(PaymentGatewayAdapter):
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self.base_url = "https://api.paystack.co"

    async def initialize_transaction(self, email: str, amount_naira: float, reference: str, metadata: dict, subaccount_code: Optional[str] = None, callback_url: Optional[str] = None) -> Dict:
        if not self.secret_key:
            raise HTTPException(status_code=500, detail="Paystack secret key not configured.")
        url = f"{self.base_url}/transaction/initialize"
        headers = {"Authorization": f"Bearer {self.secret_key}", "Content-Type": "application/json"}
        payload = {
            "email": email,
            "amount": int(amount_naira * 100),
            "reference": reference,
            "metadata": metadata,
            "callback_url": callback_url
        }
        if subaccount_code:
            payload["subaccount"] = subaccount_code
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error(f"Paystack init error: {resp.text}")
                raise HTTPException(status_code=400, detail="Failed to initialize Paystack payment.")
            data = resp.json()
            if not data.get("status"):
                raise HTTPException(status_code=400, detail=data.get("message", "Paystack error"))
            return {"payment_url": data["data"]["authorization_url"], "reference": reference}

    def verify_webhook_signature(self, raw_body: bytes, signature_header: str) -> bool:
        if not signature_header or not self.secret_key:
            return False
        expected = hmac.new(key=self.secret_key.encode('utf-8'), msg=raw_body, digestmod=hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    async def verify_transaction(self, reference: str) -> Dict:
        if not self.secret_key:
            raise HTTPException(status_code=500, detail="Paystack secret key not configured.")
        url = f"{self.base_url}/transaction/verify/{reference}"
        headers = {"Authorization": f"Bearer {self.secret_key}"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.error(f"Paystack verify error: {resp.text}")
                raise HTTPException(status_code=400, detail="Failed to verify transaction.")
            data = resp.json()
            if not data.get("status"):
                raise HTTPException(status_code=400, detail=data.get("message", "Verification failed"))
            return data["data"]


class FlutterwaveGateway(PaymentGatewayAdapter):
    def __init__(self, secret_key: str, secret_hash: str):
        self.secret_key = secret_key
        self.secret_hash = secret_hash
        self.base_url = "https://api.flutterwave.com/v3"

    async def initialize_transaction(self, email: str, amount_naira: float, reference: str, metadata: dict, subaccount_code: Optional[str] = None, callback_url: Optional[str] = None) -> Dict:
        if not self.secret_key:
            raise HTTPException(status_code=500, detail="Flutterwave secret key not configured.")
        url = f"{self.base_url}/payments"
        headers = {"Authorization": f"Bearer {self.secret_key}", "Content-Type": "application/json"}
        payload = {
            "tx_ref": reference,
            "amount": amount_naira,
            "currency": "NGN",
            "redirect_url": callback_url or f"{PRODUCTION_HOST}/",
            "customer": {"email": email},
            "meta": metadata
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error(f"Flutterwave init error: {resp.text}")
                raise HTTPException(status_code=400, detail="Failed to initialize Flutterwave payment.")
            data = resp.json()
            if data.get("status") != "success":
                raise HTTPException(status_code=400, detail=data.get("message", "Flutterwave error"))
            return {"payment_url": data["data"]["link"], "reference": reference}

    def verify_webhook_signature(self, raw_body: bytes, signature_header: str) -> bool:
        return signature_header == self.secret_hash

    async def verify_transaction(self, reference: str) -> Dict:
        if not self.secret_key:
            raise HTTPException(status_code=500, detail="Flutterwave secret key not configured.")
        url = f"{self.base_url}/transactions/{reference}/verify"
        headers = {"Authorization": f"Bearer {self.secret_key}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.error(f"Flutterwave verify error: {resp.text}")
                raise HTTPException(status_code=400, detail="Failed to verify transaction.")
            data = resp.json()
            if data.get("status") != "success":
                raise HTTPException(status_code=400, detail=data.get("message", "Verification failed"))
            return data["data"]

def get_payment_gateway_from_config(gateway_config: dict) -> PaymentGatewayAdapter:
    provider = gateway_config.get("provider", "paystack").lower()
    creds = gateway_config.get("credentials", {})
    if provider == "paystack":
        secret = creds.get("secret_key") or PAYSTACK_SECRET_KEY
        return PaystackGateway(secret_key=secret)
    elif provider == "flutterwave":
        secret = creds.get("secret_key") or FLUTTERWAVE_SECRET_KEY
        secret_hash = creds.get("secret_hash") or FLUTTERWAVE_SECRET_HASH
        return FlutterwaveGateway(secret_key=secret, secret_hash=secret_hash)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported payment gateway: {provider}")

class CartItem(BaseModel):
    inventory_id: int
    quantity: int

class CheckoutRequest(BaseModel):
    items: List[CartItem]
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    payment_method: str = "paystack"
    callback_url: Optional[str] = None
    shipping_address: Optional[str] = None
    delivery_fee: float = 0.0
    handling_fee: float = 0.0

class OfflineMeta(BaseModel):
    reference: str
    cashier_id: Optional[str] = None
    created_at: Optional[str] = None

class POSCheckoutRequest(BaseModel):
    items: List[CartItem]
    payment_method: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    shipping_address: Optional[str] = None
    delivery_fee: float = 0.0
    handling_fee: float = 0.0
    offline_meta: Optional[OfflineMeta] = None
    # Deprecated: old clients sent a bare string. Kept for backward compat.
    offline_reference: Optional[str] = None
    receipt_data: Optional[dict] = None
    location_id: Optional[UUID] = None

# ------------------------------------------------------------------
# /pos/checkout
# ------------------------------------------------------------------
@app.post("/pos/checkout")
async def checkout(request: Request, req: CheckoutRequest, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data

    logger.info(f"🔵 /pos/checkout called by user {user_id}")

    client = get_supabase()

    user_email = req.customer_email
    if not user_email:
        profile_res = await run_sync_db_call(
            client.table("profiles")
            .select("email")
            .eq("id", user_id)
            .maybe_single()
            .execute
        )
        if profile_res and profile_res.data:
            user_email = profile_res.data.get("email")
            logger.info(f"📧 Email not sent by frontend – using profile email: {user_email}")
        else:
            logger.warning(f"⚠️ No email found for user {user_id}")

    org = await run_sync_db_call(
        client.table("organisations")
        .select("payment_gateway_config, subaccount_code, org_name")
        .eq("id", org_id)
        .maybe_single()
        .execute
    )
    if not org or not org.data:
        raise HTTPException(status_code=400, detail="Organisation not found")
    gateway_config = org.data.get("payment_gateway_config", {"provider": "paystack", "credentials": {}})
    subaccount_code = org.data.get("subaccount_code")

    product_ids = [item.inventory_id for item in req.items]
    inventory_response = await run_sync_db_call(
        client.table("inventory")
        .select("*")
        .eq("org_id", org_id)
        .in_("id", product_ids)
        .execute
    )
    if not inventory_response.data:
        raise HTTPException(status_code=404, detail="No valid products found")
    inventory_map = {p["id"]: p for p in inventory_response.data}

    product_total = 0
    sale_items_batch = []
    for item in req.items:
        prod = inventory_map.get(item.inventory_id)
        if not prod:
            raise HTTPException(status_code=404, detail=f"Product ID {item.inventory_id} not found in this organisation")
        if prod["current_qty"] < item.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {prod['description']}. Available: {prod['current_qty']}")
        subtotal = prod["price_naira"] * item.quantity
        product_total += subtotal
        sale_items_batch.append({
            "inventory_id": item.inventory_id,
            "product_name": prod["description"],
            "quantity": item.quantity,
            "unit_price": prod["price_naira"],
            "subtotal": subtotal
        })

    total = product_total + req.delivery_fee + req.handling_fee

    receipt_num = f"RCP-{org_id[:4]}-{uuid.uuid4().hex[:8].upper()}"
    payment_ref = str(uuid.uuid4())

    branch_id_for_sale = await resolve_branch_for_write(org_id)
    online_location_id = await get_location_for_channel(org_id, "online")
    sale_data = {
        "org_id": org_id,
        "branch_id": branch_id_for_sale,
        "location_id": online_location_id,
        "user_id": user_id,
        "total_amount": total,
        "payment_method": req.payment_method,
        "payment_reference": payment_ref,
        "status": "pending",
        "customer_name": req.customer_name,
        "customer_phone": req.customer_phone,
        "customer_email": user_email,
        "receipt_number": receipt_num,
        "shipping_address": req.shipping_address,
        "delivery_fee": req.delivery_fee,
        "handling_fee": req.handling_fee,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    logger.info(f"📧 Checkout email (final): {user_email}")

    sale_res = await run_sync_db_call(client.table("sales").insert(sale_data).execute)
    if not sale_res.data:
        raise HTTPException(status_code=500, detail="Failed to create sale")
    sale_id = sale_res.data[0]["id"]

    if sale_items_batch:
        for item in sale_items_batch:
            item["sale_id"] = sale_id
        await run_sync_db_call(client.table("sale_items").insert(sale_items_batch).execute)

    if request.headers.get("X-Load-Test") == "true":
        return {
            "sale_id": str(sale_id),
            "receipt_number": receipt_num,
            "total": total,
            "payment_url": "https://dummy-payment.com/mock",
            "reference": payment_ref,
            "message": "Load test mode – payment skipped"
        }

    gateway = get_payment_gateway_from_config(gateway_config)
    customer_email = user_email or f"guest_{payment_ref}@example.com"

    try:
        payment_data = await gateway.initialize_transaction(
            email=customer_email,
            amount_naira=total,
            reference=payment_ref,
            metadata={"sale_id": str(sale_id), "org_id": str(org_id), "user_id": user_id},
            subaccount_code=subaccount_code,
            callback_url=req.callback_url
        )
    except Exception as e:
        logger.error(f"Gateway init failed: {e}")
        raise HTTPException(status_code=400, detail=f"Payment initialization failed: {str(e)}")

    return {
        "sale_id": str(sale_id),
        "receipt_number": receipt_num,
        "total": total,
        "payment_url": payment_data["payment_url"],
        "reference": payment_ref,
        "message": "Redirect to payment page"
    }

# ------------------------------------------------------------------
# POS TERMINAL CHECKOUT (with points awarding)
# ------------------------------------------------------------------
from fastapi import BackgroundTasks

@app.post("/pos/terminal/checkout")
async def pos_terminal_checkout(
    request: Request,
    req: POSCheckoutRequest,
    background_tasks: BackgroundTasks,
    user_data: Tuple[str, str, str] = Depends(
        require_feature("offline_pos", allowed_roles=["owner", "admin", "sales_rep"])
    )
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data

    items_payload = [{"inventory_id": item.inventory_id, "quantity": item.quantity} for item in req.items]
    receipt_num = f"POS-{org_id[:4]}-{uuid.uuid4().hex[:8].upper()}"

    if req.location_id:
        location_id = req.location_id
        logger.info(f"🆔 Using explicit location_id: {location_id}")
    else:
        location_id = await get_location_for_channel(org_id, "pos")
        logger.info(f"🆔 POS channel resolved to location_id: {location_id}")

    if not location_id:
        raise HTTPException(status_code=400, detail="No location available for this organisation")

    # Build offline metadata payload (new field preferred, old field as fallback)
    offline_meta_payload = None
    if req.offline_meta is not None:
        offline_meta_payload = {
            "reference":  req.offline_meta.reference,
            "cashier_id": req.offline_meta.cashier_id,
            "created_at": req.offline_meta.created_at,
        }
    elif req.offline_reference:
        offline_meta_payload = {"reference": req.offline_reference}

    try:
        rpc_response = await run_sync_db_call(
            get_supabase().rpc(
                "process_batch_checkout_v2",
                {
                    "p_org_id": org_id,
                    "p_user_id": user_id,
                    "p_items": items_payload,
                    "p_payment_method": req.payment_method,
                    "p_receipt_number": receipt_num,
                    "p_customer_name": req.customer_name,
                    "p_customer_phone": req.customer_phone,
                    "p_customer_email": req.customer_email,
                    "p_shipping_address": req.shipping_address,
                    "p_delivery_fee": req.delivery_fee,
                    "p_handling_fee": req.handling_fee,
                    "p_location_id": location_id,
                    "p_offline_meta": offline_meta_payload,
                }
            ).execute
        )

        result = rpc_response.data
        if not result or not result.get("success"):
            error_msg = result.get("error", "Unknown error") if result else "No response"
            logger.error(f"Batch checkout failed: {error_msg}")
            raise HTTPException(status_code=400, detail="Checkout failed – please try again")

        sale_id = result["sale_id"]
        is_duplicate = bool(result.get("duplicate"))

        if is_duplicate:
            logger.info(f"↩️ POS sale {sale_id} already exists (offline ref replay) – skipping side effects")

        # The RPC inserts status='completed' already, but branch_id and
        # shipping_status still need setting. Idempotent to re-apply.
        branch_id_for_sale = await resolve_branch_for_write(org_id)
        await run_sync_db_call(
            get_supabase().table("sales")
            .update({
                "status": "completed",
                "shipping_status": "processing",
                "branch_id": branch_id_for_sale,
            })
            .eq("id", sale_id)
            .execute
        )

        result["status"] = "completed"
        result["sale_status"] = "completed"

        # Side effects: only on the first successful insert.
        # create_ar_from_sale stays outside the guard because it is idempotent
        # and might need to heal a partial failure from a previous attempt.
        if not is_duplicate:
            if user_id and result.get("total_amount"):
                background_tasks.add_task(
                    award_loyalty_points,
                    user_id,
                    result["total_amount"],
                    result["sale_id"],
                    "pos_purchase"
                )

            client = get_supabase()
            sale = await run_sync_db_call(
                client.table("sales")
                .select("customer_email, receipt_number, total_amount")
                .eq("id", result["sale_id"])
                .maybe_single()
                .execute
            )
            if sale and sale.data and sale.data.get("customer_email"):
                items_res = await run_sync_db_call(
                    client.table("sale_items")
                    .select("product_name, quantity, unit_price, subtotal")
                    .eq("sale_id", result["sale_id"])
                    .execute
                )
                background_tasks.add_task(
                    send_order_confirmation_email,
                    sale.data,
                    items_res.data
                )

        await create_ar_from_sale(result["sale_id"], org_id, user_id)

        ar_record = await run_sync_db_call(
            get_supabase().table("accounts_receivable")
            .select("id")
            .eq("sale_id", result["sale_id"])
            .maybe_single()
            .execute
        )
        if ar_record and ar_record.data:
            ar_id = ar_record.data["id"]
            await run_sync_db_call(
                get_supabase().table("accounts_receivable")
                .update({
                    "paid_amount": result["total_amount"],
                    "status": "paid",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
                .eq("id", ar_id)
                .execute
            )
            logger.info(f"✅ A/R record {ar_id} marked as paid for sale {sale_id}")

        return {
            "sale_id": result["sale_id"],
            "receipt_number": receipt_num,
            "total": result["total_amount"],
            "payment_reference": result["payment_reference"],
            "execution_ms": result["execution_ms"],
            "updated_stock": result.get("updated_stock", []),
            "status": result.get("status", "completed"),
            "sale_status": result.get("sale_status", "completed"),
            "message": "Sale completed"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch checkout exception: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error – please contact support")

# ------------------------------------------------------------------
# WEBHOOKS
# ------------------------------------------------------------------
@app.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    logger.info("🔔 Paystack webhook received!")
    logger.info(f"Headers: {dict(request.headers)}")

    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature")
    logger.info(f"🔔 Signature: {signature}")
    logger.info(f"Raw body (first 200 chars): {raw_body[:200]}...")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event")
    logger.info(f"Event: {event}")
    if event != "charge.success":
        logger.info(f"Ignoring event: {event}")
        return {"status": "ignored"}

    data = payload["data"]
    reference = data.get("reference")
    metadata = data.get("metadata", {})
    org_id = metadata.get("org_id")
    logger.info(f"Reference: {reference}, org_id: {org_id}")

    if not org_id:
        logger.error("Webhook missing org_id")
        return {"status": "ignored"}

    client = get_supabase()
    org = await run_sync_db_call(
        client.table("organisations")
        .select("payment_gateway_config")
        .eq("id", org_id)
        .maybe_single()
        .execute
    )
    if not org or not org.data:
        logger.error(f"Org {org_id} not found")
        return {"status": "ignored"}

    gateway = get_payment_gateway_from_config(org.data.get("payment_gateway_config", {}))
    if not gateway.verify_webhook_signature(raw_body, signature):
        logger.error("Invalid Paystack signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

        logger.info("Signature verified successfully")

    payload_hash = hashlib.sha256(raw_body).hexdigest()
    claim_id = await claim_webhook_event(
        provider="paystack",
        event_key=reference,
        event_type=event,
        org_id=org_id,
        payload_hash=payload_hash,
    )
    if claim_id is None:
        logger.info(f"Paystack {reference}: already claimed or processed — skipping")
        return {"status": "already_processed"}

    try:
        sale = await run_sync_db_call(
            client.table("sales")
            .select("*")
            .eq("payment_reference", reference)
            .maybe_single()
            .execute
        )

        if not sale or not sale.data:
            logger.info(f"Paystack {reference}: no matching sale")
            await mark_webhook_event_processed(claim_id)
            return {"status": "ok"}

        items = await run_sync_db_call(
            client.table("sale_items")
            .select("inventory_id, quantity")
            .eq("sale_id", sale.data["id"])
            .execute
        )
        # Prefer the location the sale was created against; fall back to the online channel.
        sale_location = sale.data.get("location_id") if sale.data else None
        default_location_id = sale_location or await get_location_for_channel(org_id, "online")

        result = await finalize_online_order(sale.data["id"], org_id)

        if result.get("skipped"):
            logger.info(
                f"Paystack {reference}: sale {sale.data['id']} already processed "
                f"({result.get('reason')})"
            )
            await mark_webhook_event_processed(claim_id)
            return {"status": "ok"}

        for s in (result.get("short") or []):
            logger.warning(
                f"Paystack {reference}: inventory {s['inventory_id']} short by "
                f"{s['short_by']} units at finalize"
            )

        logger.info(
            f"finalize_online_order: sale {sale.data['id']} completed, "
            f"AR {result.get('ar_id')} marked paid"
        )

        # Non-critical side effects — safe to fail independently.
        if sale.data.get("user_id") and sale.data.get("total_amount"):
            try:
                await award_loyalty_points(
                    sale.data["user_id"],
                    sale.data["total_amount"],
                    sale.data["id"],
                    "purchase",
                )
            except Exception as pts_err:
                logger.error(f"Paystack {reference}: loyalty points failed: {pts_err}")

        if sale.data.get("customer_email"):
            try:
                await send_order_confirmation_email(sale.data, items.data)
            except Exception as email_err:
                logger.error(
                    f"Paystack {reference}: email failed but sale is complete: {email_err}"
                )

        await mark_webhook_event_processed(claim_id)
        logger.info(f"Paystack {reference}: sale {sale.data['id']} processed")
        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Paystack {reference} failed: {e}", exc_info=True)
        await release_webhook_event_claim(claim_id)
        raise HTTPException(status_code=500, detail="Webhook processing failed")

@app.post("/webhook/flutterwave")
async def flutterwave_webhook(request: Request):
    logger.info("🔔 Flutterwave webhook received!")
    logger.info(f"Headers: {dict(request.headers)}")

    raw_body = await request.body()
    signature = request.headers.get("x-verif-hash")
    logger.info(f"🔔 Signature: {signature}")
    logger.info(f"Raw body (first 200 chars): {raw_body[:200]}...")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event")
    logger.info(f"Event: {event}")
    if event != "charge.completed":
        logger.info(f"Ignoring event: {event}")
        return {"status": "ignored"}

    data = payload["data"]
    reference = data.get("tx_ref")
    meta = data.get("meta", {})
    org_id = meta.get("org_id")
    logger.info(f"Reference: {reference}, org_id: {org_id}")

    if not org_id:
        logger.error("Flutterwave webhook missing org_id")
        return {"status": "ignored"}

    client = get_supabase()
    org = await run_sync_db_call(
        client.table("organisations")
        .select("payment_gateway_config")
        .eq("id", org_id)
        .maybe_single()
        .execute
    )
    if not org or not org.data:
        logger.error(f"Org {org_id} not found")
        return {"status": "ignored"}

    gateway = get_payment_gateway_from_config(org.data.get("payment_gateway_config", {}))
    if not gateway.verify_webhook_signature(raw_body, signature):
        logger.error("Invalid Flutterwave signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

        logger.info("Signature verified successfully")

    payload_hash = hashlib.sha256(raw_body).hexdigest()
    claim_id = await claim_webhook_event(
        provider="flutterwave",
        event_key=reference,
        event_type=event,
        org_id=org_id,
        payload_hash=payload_hash,
    )
    if claim_id is None:
        logger.info(f"Flutterwave {reference}: already claimed or processed — skipping")
        return {"status": "already_processed"}

    try:
        sale = await run_sync_db_call(
            client.table("sales")
            .select("*")
            .eq("payment_reference", reference)
            .maybe_single()
            .execute
        )

        if not sale or not sale.data:
            logger.info(f"Flutterwave {reference}: no matching sale")
            await mark_webhook_event_processed(claim_id)
            return {"status": "ok"}

        items = await run_sync_db_call(
            client.table("sale_items")
            .select("inventory_id, quantity")
            .eq("sale_id", sale.data["id"])
            .execute
        )
        # Prefer the location the sale was created against; fall back to the online channel.
        sale_location = sale.data.get("location_id") if sale.data else None
        default_location_id = sale_location or await get_location_for_channel(org_id, "online")

        result = await finalize_online_order(sale.data["id"], org_id)

        if result.get("skipped"):
            logger.info(
                f"Flutterwave {reference}: sale {sale.data['id']} already processed "
                f"({result.get('reason')})"
            )
            await mark_webhook_event_processed(claim_id)
            return {"status": "ok"}

        for s in (result.get("short") or []):
            logger.warning(
                f"Flutterwave {reference}: inventory {s['inventory_id']} short by "
                f"{s['short_by']} units at finalize"
            )

        logger.info(
            f"finalize_online_order: sale {sale.data['id']} completed, "
            f"AR {result.get('ar_id')} marked paid"
        )

        if sale.data.get("user_id") and sale.data.get("total_amount"):
            try:
                await award_loyalty_points(
                    sale.data["user_id"],
                    sale.data["total_amount"],
                    sale.data["id"],
                    "purchase",
                )
            except Exception as pts_err:
                logger.error(f"Flutterwave {reference}: loyalty points failed: {pts_err}")

        if sale.data.get("customer_email"):
            try:
                await send_order_confirmation_email(sale.data, items.data)
            except Exception as email_err:
                logger.error(
                    f"Flutterwave {reference}: email failed but sale is complete: {email_err}"
                )

        await mark_webhook_event_processed(claim_id)
        logger.info(f"Flutterwave {reference}: sale {sale.data['id']} processed")
        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Flutterwave {reference} failed: {e}", exc_info=True)
        await release_webhook_event_claim(claim_id)
        raise HTTPException(status_code=500, detail="Webhook processing failed")

# ------------------------------------------------------------------
# BACKGROUND SYNC – Retry pending orders
# ------------------------------------------------------------------
@app.post("/api/retry-pending-orders")
async def retry_pending_orders(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "customer"]))
):
    """
    Retry pending orders that were created offline (status='pending_sync')
    or stuck in 'pending' state for more than 5 minutes.
    """
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    threshold = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    # NOTE: the `items` column does not exist on `sales` – select only real columns.
    pending = await run_sync_db_call(
        client.table("sales")
        .select("id, receipt_number, total_amount, payment_reference, payment_method, customer_email, created_at, location_id")
        .eq("user_id", user_id)
        .eq("org_id", org_id)
        .eq("status", "pending")
        .lt("created_at", threshold)
        .execute
    )

    if not pending.data:
        return {"synced": [], "message": "No pending orders to sync"}

    org = await run_sync_db_call(
        client.table("organisations")
        .select("payment_gateway_config")
        .eq("id", org_id)
        .maybe_single()
        .execute
    )
    if not org or not org.data:
        logger.error(f"Org {org_id} not found for retry")
        return {"synced": [], "error": "Organisation not found"}

    gateway_config = org.data.get("payment_gateway_config", {"provider": "paystack", "credentials": {}})
    gateway = get_payment_gateway_from_config(gateway_config)

    results = []
    for order in pending.data:
        try:
            payment_ref = order.get("payment_reference")
            if not payment_ref:
                results.append({"id": order["id"], "status": "skipped", "reason": "No payment reference"})
                continue

            if isinstance(gateway, PaystackGateway):
                verify_data = await gateway.verify_transaction(payment_ref)
                gateway_status = verify_data.get("status")
            elif isinstance(gateway, FlutterwaveGateway):
                verify_data = await gateway.verify_transaction(payment_ref)
                gateway_status = verify_data.get("status")
            else:
                results.append({"id": order["id"], "status": "skipped", "reason": "Unsupported gateway"})
                continue

            if gateway_status == "success":
                items_res = await run_sync_db_call(
                    client.table("sale_items")
                    .select("inventory_id, quantity")
                    .eq("sale_id", order["id"])
                    .execute
                )
                items = items_res.data or []

                finalize_result = await finalize_online_order(order["id"], org_id)

                if finalize_result.get("skipped"):
                    results.append({
                        "id": order["id"],
                        "status": "skipped",
                        "reason": finalize_result.get("reason"),
                    })
                    continue

                for s in (finalize_result.get("short") or []):
                    logger.warning(
                        f"retry_pending_orders: inventory {s['inventory_id']} short by "
                        f"{s['short_by']} units at finalize"
                    )

                if order.get("total_amount"):
                    try:
                        await award_loyalty_points(user_id, order["total_amount"], order["id"], "sync_purchase")
                    except Exception as pts_err:
                        logger.error(f"retry_pending_orders: loyalty points failed for {order['id']}: {pts_err}")

                if order.get("customer_email"):
                    items_for_email = await run_sync_db_call(
                        client.table("sale_items")
                        .select("product_name, quantity, unit_price, subtotal")
                        .eq("sale_id", order["id"])
                        .execute
                    )
                    try:
                        await send_order_confirmation_email(order, items_for_email.data)
                    except Exception as email_err:
                        logger.error(f"retry_pending_orders: email failed for {order['id']}: {email_err}")

                results.append({"id": order["id"], "status": "synced"})
            else:
                results.append({"id": order["id"], "status": "pending", "reason": f"Gateway status: {gateway_status}"})

        except Exception as e:
            logger.error(f"Error processing order {order['id']}: {e}")
            results.append({"id": order["id"], "status": "failed", "error": str(e)})

    return {"synced": results}

# ------------------------------------------------------------------
# CHAT STREAM (public for guests)
# ------------------------------------------------------------------
class ChatStreamReq(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=2000)
    # Optional tenant hint. The storefront widget sends this so an
    # unauthenticated visitor chats against the store they are actually
    # browsing, not an arbitrary org. Ignored for authenticated callers.
    org_slug: Optional[str] = Field(None, min_length=1, max_length=60)


async def get_current_user_with_role_optional(authorization: Optional[str] = Header(None)) -> Optional[Tuple[str, str, str]]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return await get_current_user_with_role(authorization, None)
    except HTTPException:
        return None

@app.post("/support/chat-stream")
async def chat_stream(
    request: Request,
    req: ChatStreamReq,
    authorization: Optional[str] = Header(None)
):
    await rate_limit(get_client_ip(request))

    if not re.match(r'^[a-zA-Z0-9_-]+$', req.session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    user_org = await get_current_user_with_role_optional(authorization)
    client = get_supabase()

    if user_org:
        # Authenticated caller. The JWT is authoritative. Any org_slug
        # the client may have sent is deliberately ignored — a logged-in
        # user must not be able to re-scope their own chat to a tenant
        # they do not belong to.
        user_id, org_id, role = user_org
    else:
        # Guest caller. Resolve the tenant from the slug the storefront
        # widget sent. Never guess: the previous code called
        # .limit(1) on organisations with no ordering, so guests were
        # routed to whichever tenant Postgres returned first — a real
        # cross-tenant leak once more than one org was live.

        if req.org_slug:
            # Explicit slug. The widget is embedded on a tenant
            # storefront page. If the slug does not resolve to a
            # published store, refuse with the same 404 the public
            # storefront returns — do NOT silently fall back to the
            # public store org, because a visitor who landed on
            # /store/foo should never be answered by bar's assistant.
            org_res = await run_sync_db_call(
                client.table("organisations")
                .select("id, storefront_published")
                .eq("slug", req.org_slug)
                .maybe_single()
                .execute
            )
            if (
                not org_res
                or not org_res.data
                or not org_res.data.get("storefront_published")
            ):
                # Same shape as /public/storefront/{slug} so this
                # endpoint does not become a tenant-existence oracle.
                raise HTTPException(status_code=404, detail="Store not found")
            org_id = org_res.data["id"]
        else:
            # No slug. Caller is on the general URL (kdstore.html not
            # served via /store/{slug}). Fall back to the designated
            # public store org.
            if not PUBLIC_STORE_ORG_ID:
                raise HTTPException(
                    status_code=500,
                    detail="Public store organisation not configured",
                )
            org_id = PUBLIC_STORE_ORG_ID

        user_id = f"guest_{get_client_ip(request)}"
        role = "guest"

    reply, ticket_id = await get_strategic_reply(
        req.message, user_id, org_id, req.session_id, "web_widget"
    )
    await save_conversation(user_id, org_id, req.session_id, req.message, reply, "web_widget")
    response = {"response": reply}
    if ticket_id:
        response["ticket_id"] = ticket_id
    return response

# ------------------------------------------------------------------
# WHATSAPP WEBHOOK
# ------------------------------------------------------------------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException)))
async def send_whatsapp_message_with_retry(to: str, text: str):
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_ID:
        logger.warning("WhatsApp credentials missing")
        return
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"WhatsApp message sent to {to}")

async def send_whatsapp_message(to: str, text: str):
    try:
        await send_whatsapp_message_with_retry(to, text)
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message after retries: {e}", exc_info=True)

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == WHATSAPP_VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Verification Failed", status_code=403)

@app.post("/webhook")
async def handle_whatsapp(request: Request):
    data = await request.json()
    try:
        entry = data['entry'][0]['changes'][0]['value']
        if 'messages' in entry:
            message = entry['messages'][0]
            from_phone = message['from']
            text_body = message.get('text', {}).get('body', '')
            session_id = f"whatsapp_{from_phone}"
            client = get_supabase()
            profile = await run_sync_db_call(client.table("profiles").select("id").eq("phone", from_phone).maybe_single().execute)
            if profile and profile.data:
                membership = await run_sync_db_call(client.table("org_members").select("org_id").eq("user_id", profile.data["id"]).maybe_single().execute)
                if membership and membership.data:
                    org_id = membership.data["org_id"]
                    user_id = profile.data["id"]
                    await rate_limit(from_phone, org_id)
                    reply, _ = await get_strategic_reply(text_body, user_id, org_id, session_id, "whatsapp")
                    await save_conversation(user_id, org_id, session_id, text_body, reply, "whatsapp")
                    await send_whatsapp_message(from_phone, reply)
                else:
                    await send_whatsapp_message(from_phone, "Phone not linked to an organisation.")
            else:
                await send_whatsapp_message(from_phone, "Please register first.")
    except Exception as e:
        logger.error(f"WhatsApp webhook error: {e}", exc_info=True)
    return {"status": "ok"}

# ------------------------------------------------------------------
# ORDER TRACKING (public)
# ------------------------------------------------------------------
@app.get("/track-order")
async def track_order(request: Request, receipt_number: str, email: str):
    await rate_limit(get_client_ip(request))
    client = get_supabase()
    try:
        result = await run_sync_db_call(
            client.table("sales")
            .select("receipt_number, total_amount, shipping_status, tracking_number, shipping_carrier, estimated_delivery, created_at")
            .eq("receipt_number", receipt_number)
            .eq("customer_email", email)
            .execute
        )
        if result and result.data and len(result.data) > 0:
            return result.data[0]
        else:
            raise HTTPException(status_code=404, detail="Order not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Track order error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

# ------------------------------------------------------------------
# SHIPPING STATUS (role-protected for logistics)
# ------------------------------------------------------------------
class ShippingUpdate(BaseModel):
    shipping_status: str
    tracking_number: Optional[str] = None
    shipping_carrier: Optional[str] = None
    estimated_delivery: Optional[str] = None

@app.patch("/pos/sale/{sale_id}/shipping")
async def update_shipping(request: Request, sale_id: str, update: ShippingUpdate, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "logistics"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    sale = await run_sync_db_call(client.table("sales").select("*").eq("id", sale_id).eq("org_id", org_id).maybe_single().execute)
    if not sale.data:
        raise HTTPException(status_code=404, detail="Sale not found")
    data = {k: v for k, v in update.dict().items() if v is not None}
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    await run_sync_db_call(client.table("sales").update(data).eq("id", sale_id).execute)
    return {"message": "Shipping updated"}

# ------------------------------------------------------------------
# DELIVERY ESTIMATION
# ------------------------------------------------------------------
class DeliveryEstimateRequest(BaseModel):
    address: str
    items: List[Dict]

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371
    lat1, lat2 = radians(lat1), radians(lat2)
    dlat = lat2 - lat1
    dlon = radians(lon2) - radians(lon1)
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

@app.post("/delivery/estimate")
async def estimate_delivery(request: Request, req: DeliveryEstimateRequest, user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data

    store_lat = float(os.environ.get("STORE_LAT", "6.5244"))
    store_lng = float(os.environ.get("STORE_LNG", "3.3792"))
    client = get_supabase()

    org_result = await run_sync_db_call(
        client.table("organisations").select(
            "latitude, longitude, delivery_base_fee, delivery_per_km_rate, delivery_per_kg_rate, "
            "handling_surcharge_fragile, handling_surcharge_bulky, handling_surcharge_hazardous"
        ).eq("id", org_id).maybe_single().execute
    )
    if org_result and org_result.data:
        org_data = org_result.data
        if org_data.get("latitude") is not None and org_data.get("longitude") is not None:
            store_lat = float(org_data["latitude"])
            store_lng = float(org_data["longitude"])
        base_fee = float(org_data.get("delivery_base_fee") or 300)
        per_km_rate = float(org_data.get("delivery_per_km_rate") or 80)
        per_kg_rate = float(org_data.get("delivery_per_kg_rate") or 50)
        surcharge_fragile = float(org_data.get("handling_surcharge_fragile") or 200)
        surcharge_bulky = float(org_data.get("handling_surcharge_bulky") or 500)
        surcharge_hazardous = float(org_data.get("handling_surcharge_hazardous") or 1000)
    else:
        base_fee = float(os.environ.get("DELIVERY_BASE_FEE", "300"))
        per_km_rate = float(os.environ.get("DELIVERY_PER_KM_RATE", "80"))
        per_kg_rate = float(os.environ.get("DELIVERY_PER_KG_RATE", "50"))
        surcharge_fragile = 200
        surcharge_bulky = 500
        surcharge_hazardous = 1000

    surcharge_map = {
        "fragile": surcharge_fragile,
        "bulky": surcharge_bulky,
        "hazardous": surcharge_hazardous,
        "standard": 0
    }

    geocode_url = "https://nominatim.openstreetmap.org/search"
    params = {"q": req.address, "format": "json", "limit": 1}
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            geo_resp = await http.get(geocode_url, params=params, headers={"User-Agent": "KevsDigital/1.0"})
            if geo_resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Geocoding failed")
            geo_data = geo_resp.json()
            if not geo_data:
                raise HTTPException(status_code=400, detail="Address not located")
            dest_lat, dest_lng = float(geo_data[0]["lat"]), float(geo_data[0]["lon"])
    except Exception as e:
        logger.error(f"Geocoding error: {e}")
        raise HTTPException(status_code=502, detail="Geocoding service error")

    distance_km = haversine(store_lat, store_lng, dest_lat, dest_lng)

    if not req.items:
        raise HTTPException(status_code=400, detail="No items provided")
    inventory_ids = [item["inventory_id"] for item in req.items]
    inventory_items = await run_sync_db_call(client.table("inventory").select("id, weight_kg, handling_category").in_("id", inventory_ids).execute)
    if not inventory_items.data:
        raise HTTPException(status_code=404, detail="Products not found")
    inv_map = {item["id"]: item for item in inventory_items.data}

    total_weight_kg = 0.0
    handling_surcharge = 0
    for cart_item in req.items:
        inv_id = cart_item["inventory_id"]
        qty = cart_item["quantity"]
        product = inv_map.get(inv_id)
        if not product:
            continue
        weight = product.get("weight_kg", 0.0) or 0.0
        total_weight_kg += weight * qty
        category = product.get("handling_category", "standard")
        handling_surcharge += surcharge_map.get(category, 0) * qty

    delivery_fee = (
        base_fee
        + (distance_km * per_km_rate)
        + (total_weight_kg * per_kg_rate)
        + handling_surcharge
    )
    delivery_fee = round(delivery_fee / 50) * 50
    handling_fee = 200

    return {
        "delivery_fee_naira": delivery_fee,
        "handling_fee_naira": handling_fee,
        "distance_km": round(distance_km, 1),
        "total_weight_kg": round(total_weight_kg, 2),
        "breakdown": {
            "base_fee": base_fee,
            "distance_cost": round(distance_km * per_km_rate, 2),
            "weight_cost": round(total_weight_kg * per_kg_rate, 2),
            "handling_surcharge": handling_surcharge
        }
    }

# ------------------------------------------------------------------
# FULFILLMENT DASHBOARD ENDPOINTS
# ------------------------------------------------------------------
class FulfillmentUpdate(BaseModel):
    shipping_status: str
    tracking_number: Optional[str] = None
    shipping_carrier: Optional[str] = None
    estimated_delivery: Optional[str] = None
    notes: Optional[str] = None
    confirm_payment: bool = False

@app.get("/fulfillment/orders")
async def list_fulfillment_orders(
    request: Request,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_pending: bool = False,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "logistics"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    query = client.table("sales").select("*, sale_items(id, product_name, quantity, unit_price)") \
        .eq("org_id", org_id)
    if not include_pending:
        query = query.neq("status", "pending")
    if status:
        query = query.eq("shipping_status", status)
    result = await run_sync_db_call(query.order("created_at", desc=True).range(offset, offset + limit - 1).execute)
    orders = result.data or []

    user_ids = []
    for order in orders:
        if not order.get("customer_phone") and order.get("user_id"):
            user_ids.append(order["user_id"])

    if user_ids:
        profile_res = await run_sync_db_call(
            client.table("profiles")
            .select("id, phone")
            .in_("id", user_ids)
            .execute
        )
        profile_map = {p["id"]: p.get("phone") for p in (profile_res.data or [])}
        for order in orders:
            if not order.get("customer_phone") and order.get("user_id"):
                order["customer_phone"] = profile_map.get(order["user_id"], "Not provided")

    return {"orders": orders}

@app.get("/fulfillment/order/{order_id}")
async def get_fulfillment_order(request: Request, order_id: str, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "logistics"]))):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    order = await run_sync_db_call(
        client.table("sales")
        .select("*, sale_items(*)")
        .eq("id", order_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not order.data:
        raise HTTPException(status_code=404, detail="Order not found")

    order_data = order.data

    if not order_data.get("customer_phone") and order_data.get("user_id"):
        profile_res = await run_sync_db_call(
            client.table("profiles")
            .select("phone")
            .eq("id", order_data["user_id"])
            .maybe_single()
            .execute
        )
        if profile_res and profile_res.data:
            order_data["customer_phone"] = profile_res.data.get("phone")
        else:
            order_data["customer_phone"] = "Not provided"

    return order_data

@app.put("/fulfillment/order/{order_id}/status")
async def update_fulfillment_status(
    request: Request,
    order_id: str,
    update: FulfillmentUpdate,
    background_tasks: BackgroundTasks,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "logistics"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    order = await run_sync_db_call(client.table("sales").select("shipping_status, customer_email, status").eq("id", order_id).eq("org_id", org_id).maybe_single().execute)
    if not order.data:
        raise HTTPException(status_code=404, detail="Order not found")
    old_status = order.data.get("shipping_status") or "pending"
    new_status = update.shipping_status

    data = {
        "shipping_status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    if update.tracking_number is not None:
        data["tracking_number"] = update.tracking_number
    if update.shipping_carrier is not None:
        data["shipping_carrier"] = update.shipping_carrier
    if update.estimated_delivery is not None:
        data["estimated_delivery"] = update.estimated_delivery
    if update.notes is not None:
        data["fulfillment_notes"] = update.notes

    if update.confirm_payment:
        data["status"] = "completed"
        logger.info(f"Payment confirmed for order {order_id}")

    result = await run_sync_db_call(client.table("sales").update(data).eq("id", order_id).eq("org_id", org_id).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Update failed")

    if new_status in ["shipped", "delivered"] and new_status != old_status:
        tracking_info = {
            "carrier": update.shipping_carrier,
            "tracking_number": update.tracking_number,
            "estimated_delivery": update.estimated_delivery
        }
        background_tasks.add_task(send_status_update_email, order_id, old_status, new_status, tracking_info)

    return {"message": f"Order status updated to {new_status}", "order": result.data[0]}

# ------------------------------------------------------------------
# LOYALTY ENDPOINTS
# ------------------------------------------------------------------
@app.get("/loyalty/balance")
async def loyalty_balance(request: Request, user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, _, _ = user_data
    balance = await get_loyalty_balance(user_id)
    return balance

@app.get("/loyalty/transactions")
async def loyalty_transactions(request: Request, limit: int = 50, offset: int = 0, user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, _, _ = user_data
    txns = await get_loyalty_transactions(user_id, limit, offset)
    return {"transactions": txns, "limit": limit, "offset": offset}

class RedeemRequest(BaseModel):
    points: int = Field(..., gt=0)

@app.post("/loyalty/redeem")
async def redeem_points(request: Request, req: RedeemRequest, user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, _, _ = user_data
    credit_added = await redeem_points_to_credit(user_id, req.points)
    return {"message": f"Redeemed {req.points} points for ₦{credit_added} store credit", "credit_added": credit_added}

# ===================== ACCOUNTING ENDPOINTS =====================
@app.get("/accounts/chart")
async def list_chart_of_accounts(
    request: Request,
    account_type: Optional[AccountType] = None,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "auditor"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    query = client.table("chart_of_accounts").select("*").eq("org_id", org_id)
    if account_type:
        query = query.eq("type", account_type.value)
    result = await run_sync_db_call(query.order("code").execute)
    return {"accounts": result.data}

@app.post("/accounts/chart")
async def create_chart_account(
    request: Request,
    account: ChartAccountCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    data = account.dict()
    data["org_id"] = org_id
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(client.table("chart_of_accounts").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create account")
    return result.data[0]

@app.put("/accounts/chart/{account_id}")
async def update_chart_account(
    request: Request,
    account_id: UUID,
    account: ChartAccountUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    update_data = {k: v for k, v in account.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(
        client.table("chart_of_accounts")
        .update(update_data)
        .eq("id", account_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Account not found")
    return result.data[0]

@app.delete("/accounts/chart/{account_id}")
async def delete_chart_account(
    request: Request,
    account_id: UUID,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    used = await run_sync_db_call(
        client.table("journal_lines").select("id").eq("account_id", account_id).limit(1).execute
    )
    if used.data:
        raise HTTPException(status_code=400, detail="Account is used in journal entries and cannot be deleted")
    result = await run_sync_db_call(
        client.table("chart_of_accounts")
        .delete()
        .eq("id", account_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"message": "Account deleted"}

@app.get("/accounts/journal-entries")
async def list_journal_entries(
    request: Request,
    status: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 50,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "auditor"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    query = client.table("journal_entries").select("*").eq("org_id", org_id)
    if status:
        query = query.eq("status", status)
    if from_date:
        query = query.gte("entry_date", from_date.isoformat())
    if to_date:
        query = query.lte("entry_date", to_date.isoformat())
    result = await run_sync_db_call(query.order("entry_date", desc=True).range(offset, offset + limit - 1).execute)
    return {"entries": result.data, "total": len(result.data) if result.data else 0}

@app.get("/accounts/journal-entries/{entry_id}")
async def get_journal_entry(
    request: Request,
    entry_id: UUID,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "auditor"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    entry = await run_sync_db_call(
        client.table("journal_entries")
        .select("*, journal_lines(*)")
        .eq("id", entry_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not entry.data:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return entry.data[0]

@app.post("/accounts/journal-entries")
async def create_manual_journal_entry(
    request: Request,
    je: JournalEntryCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    for line in je.lines:
        if "account_id" not in line:
            raise HTTPException(status_code=400, detail="Each line must have account_id")
        if "debit" not in line and "credit" not in line:
            raise HTTPException(status_code=400, detail="Each line must have debit or credit")
        debit = line.get("debit", 0)
        credit = line.get("credit", 0)
        if debit and credit:
            raise HTTPException(status_code=400, detail="Line cannot have both debit and credit")
        if debit < 0 or credit < 0:
            raise HTTPException(status_code=400, detail="Debit and credit must be non-negative")
    entry = await create_journal_entry(
        org_id=org_id,
        entry_date=je.entry_date,
        description=je.description,
        lines=je.lines,
        reference=je.reference,
        created_by=user_id,
        status="draft"
    )
    return {"entry": entry}

@app.post("/accounts/journal-entries/{entry_id}/post")
async def post_journal_entry_endpoint(
    request: Request,
    entry_id: UUID,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    posted = await post_journal_entry(entry_id, org_id, user_id)
    return {"message": "Entry posted", "entry": posted}

@app.get("/accounts/ar")
async def list_ar(
    request: Request,
    status: Optional[str] = None,
    customer_id: Optional[UUID] = None,
    limit: int = 50,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "auditor"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    query = client.table("accounts_receivable").select("*").eq("org_id", org_id)
    if status:
        query = query.eq("status", status)
    if customer_id:
        query = query.eq("customer_id", customer_id)
    result = await run_sync_db_call(
        query.order("due_date").range(offset, offset + limit - 1).execute
    )
    rows = result.data or []
    if not rows:
        return {"ar": [], "total": 0}

    # Enrich with cashier info via sales + profiles
    sale_ids = [r["sale_id"] for r in rows if r.get("sale_id")]
    cashier_by_sale = {}
    if sale_ids:
        sales_res = await run_sync_db_call(
            client.table("sales")
            .select("id, user_id, receipt_number")
            .in_("id", sale_ids)
            .execute
        )
        sales_rows = sales_res.data or []
        user_ids = list({s["user_id"] for s in sales_rows if s.get("user_id")})
        profiles_map = {}
        if user_ids:
            prof_res = await run_sync_db_call(
                client.table("profiles")
                .select("id, first_name, last_name")
                .in_("id", user_ids)
                .execute
            )
            for p in (prof_res.data or []):
                profiles_map[p["id"]] = p

        for s in sales_rows:
            uid = s.get("user_id")
            prof = profiles_map.get(uid) if uid else None
            full_name = None
            if prof:
                full_name = " ".join(
                    filter(None, [prof.get("first_name"), prof.get("last_name")])
                ).strip() or None
            cashier_by_sale[s["id"]] = {
                "cashier_id":   uid,
                "cashier_name": full_name,
                "receipt_number": s.get("receipt_number"),
            }

    for r in rows:
        extra = cashier_by_sale.get(r.get("sale_id"), {})
        r["cashier_id"]     = extra.get("cashier_id")
        r["cashier_name"]   = extra.get("cashier_name")
        r["receipt_number"] = extra.get("receipt_number")

    return {"ar": rows, "total": len(rows)}

@app.post("/accounts/ar/{ar_id}/payment")
async def register_ar_payment(
    request: Request,
    ar_id: UUID,
    payment: PaymentRegister,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()
    ar = await run_sync_db_call(
        client.table("accounts_receivable")
        .select("*")
        .eq("id", ar_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not ar or not ar.data:
        raise HTTPException(status_code=404, detail="A/R record not found")
    if ar.data["status"] == "paid":
        raise HTTPException(status_code=400, detail="Already paid")
    new_paid = ar.data["paid_amount"] + payment.amount
    if new_paid > ar.data["amount"]:
        raise HTTPException(status_code=400, detail="Payment exceeds outstanding amount")
    status = "paid" if new_paid >= ar.data["amount"] else "partial"
    update_data = {
        "paid_amount": new_paid,
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    result = await run_sync_db_call(
        client.table("accounts_receivable")
        .update(update_data)
        .eq("id", ar_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update payment")

    cash_acc = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "asset")
        .ilike("name", "%cash%")
        .limit(1)
        .execute
    )
    ar_acc = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "asset")
        .ilike("name", "%accounts receivable%")
        .limit(1)
        .execute
    )
    if cash_acc.data and ar_acc.data:
        lines = [
            {"account_id": cash_acc.data[0]["id"], "debit": payment.amount, "credit": 0},
            {"account_id": ar_acc.data[0]["id"], "debit": 0, "credit": payment.amount}
        ]
        await create_journal_entry(
            org_id=org_id,
            entry_date=date.today(),
            description=f"Payment received for A/R {ar_id}",
            lines=lines,
            reference=f"AR-PAY-{str(ar_id)[:8]}",
            created_by=user_id,
            status="posted"
        )

    await _log_audit_event(org_id, user_id, "accounts_receivable", "payment", ar_id, ar.data, result.data[0])
    return {"message": "Payment registered", "ar": jsonable_encoder(result.data[0])}

@app.get("/accounts/ap")
async def list_ap(
    request: Request,
    status: Optional[str] = None,
    supplier_id: Optional[UUID] = None,
    limit: int = 50,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "auditor"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    query = client.table("accounts_payable").select("*").eq("org_id", org_id)
    if status:
        query = query.eq("status", status)
    if supplier_id:
        query = query.eq("supplier_id", supplier_id)
    result = await run_sync_db_call(query.order("due_date").range(offset, offset + limit - 1).execute)
    return {"ap": result.data, "total": len(result.data) if result.data else 0}

@app.post("/accounts/ap/{ap_id}/payment")
async def register_ap_payment(
    request: Request,
    ap_id: UUID,
    payment: PaymentRegister,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()
    ap = await run_sync_db_call(
        client.table("accounts_payable")
        .select("*")
        .eq("id", ap_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not ap or not ap.data:
        raise HTTPException(status_code=404, detail="A/P record not found")
    if ap.data["status"] == "paid":
        raise HTTPException(status_code=400, detail="Already paid")
    new_paid = ap.data["paid_amount"] + payment.amount
    if new_paid > ap.data["amount"]:
        raise HTTPException(status_code=400, detail="Payment exceeds outstanding amount")
    status = "paid" if new_paid >= ap.data["amount"] else "partial"
    update_data = {
        "paid_amount": new_paid,
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    result = await run_sync_db_call(
        client.table("accounts_payable")
        .update(update_data)
        .eq("id", ap_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update payment")

    cash_acc = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "asset")
        .ilike("name", "%cash%")
        .limit(1)
        .execute
    )
    ap_acc = await run_sync_db_call(
        client.table("chart_of_accounts")
        .select("id")
        .eq("org_id", org_id)
        .eq("type", "liability")
        .ilike("name", "%accounts payable%")
        .limit(1)
        .execute
    )
    if cash_acc.data and ap_acc.data:
        lines = [
            {"account_id": ap_acc.data[0]["id"], "debit": payment.amount, "credit": 0},
            {"account_id": cash_acc.data[0]["id"], "debit": 0, "credit": payment.amount}
        ]
        await create_journal_entry(
            org_id=org_id,
            entry_date=date.today(),
            description=f"Payment made for A/P {ap_id}",
            lines=lines,
            reference=f"AP-PAY-{str(ap_id)[:8]}",
            created_by=user_id,
            status="posted"
        )

    await _log_audit_event(org_id, user_id, "accounts_payable", "payment", ap_id, ap.data, result.data[0])
    return {"message": "Payment registered", "ap": jsonable_encoder(result.data[0])}

@app.post("/accounts/profit-loss")
async def generate_pl(
    request: Request,
    pl_req: PLRequest,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "auditor"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    pl = await generate_profit_loss(org_id, pl_req.period_start, pl_req.period_end)
    return {"profit_loss": pl, "period_start": pl_req.period_start, "period_end": pl_req.period_end}

@app.get("/accounts/profit-loss/summary")
async def get_pl_summary(
    request: Request,
    period_start: date,
    period_end: date,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "auditor"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("profit_loss_summary")
        .select("*")
        .eq("org_id", org_id)
        .eq("period_start", period_start.isoformat())
        .eq("period_end", period_end.isoformat())
        .maybe_single()
        .execute
    )
    if not result or not result.data:
        pl = await generate_profit_loss(org_id, period_start, period_end)
        return {"profit_loss": pl}
    return result.data

@app.post("/accounts/export")
async def export_accounting_data(
    request: Request,
    export_req: ExportRequest,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "auditor"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    table_map = {
        "accounts_receivable": "accounts_receivable",
        "accounts_payable": "accounts_payable",
        "journal_entries": "journal_entries",
        "profit_loss": "profit_loss_summary"
    }
    if export_req.entity not in table_map:
        raise HTTPException(status_code=400, detail="Invalid entity")
    table = table_map[export_req.entity]
    query = client.table(table).select("*").eq("org_id", org_id)
    if export_req.period_start and export_req.period_end:
        query = query.gte("created_at", export_req.period_start.isoformat())
        query = query.lte("created_at", export_req.period_end.isoformat())
    result = await run_sync_db_call(query.execute)
    data = result.data or []

    if export_req.format == "csv":
        if not data:
            return PlainTextResponse("No data", media_type="text/plain")
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
        return PlainTextResponse(output.getvalue(), media_type="text/csv")
    else:
        return JSONResponse(content={"data": data})

@app.post("/accounts/sync-webhook")
async def trigger_sync_webhook(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance"]))
):
    org_id = user_data[1]
    client = get_supabase()
    org = await run_sync_db_call(
        client.table("organisations")
        .select("accounting_webhook_url")
        .eq("id", org_id)
        .maybe_single()
        .execute
    )
    webhook_url = org.data.get("accounting_webhook_url") if org.data else None
    if not webhook_url:
        raise HTTPException(status_code=400, detail="No webhook URL configured for this organisation")

    payload = {"org_id": org_id, "timestamp": datetime.now(timezone.utc).isoformat(), "event": "sync_requested"}
    async with httpx.AsyncClient() as http:
        try:
            resp = await http.post(webhook_url, json=payload, timeout=10.0)
            if resp.status_code >= 400:
                logger.error(f"Webhook failed: {resp.text}")
                raise HTTPException(status_code=502, detail="External service error")
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            raise HTTPException(status_code=502, detail="Failed to reach external service")

    return {"message": "Webhook triggered successfully"}

# ------------------------------------------------------------------
# CUSTOMER REGISTRATION (Admin endpoint)
# ------------------------------------------------------------------
class RegisterCustomerRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str = Field(..., min_length=1, description="Phone number is required")
    date_of_birth: Optional[str] = None
    address: Optional[str] = None
    tier: str = "bronze"
    loyalty_points: int = 0

@app.post("/admin/register-customer")
async def register_customer(
    request: Request,
    customer: RegisterCustomerRequest,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "loyalty_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data

    if not customer.phone or not customer.phone.strip():
        raise HTTPException(status_code=400, detail="Phone number is required to register a customer")

    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=500, detail="Service role key not configured. Cannot create users.")

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as http_client:
        check_url = f"{SUPABASE_URL}/rest/v1/profiles?select=id&email=eq.{customer.email}"
        check_resp = await http_client.get(check_url, headers=headers)

        if check_resp.status_code == 200 and check_resp.json():
            raise HTTPException(status_code=400, detail="A user with this email already exists")

        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))

        admin_url = f"{SUPABASE_URL}/auth/v1/admin/users"
        admin_payload = {
            "email": customer.email,
            "password": temp_password,
            "email_confirm": True,
            "user_metadata": {
                "first_name": customer.first_name,
                "last_name": customer.last_name,
                "phone": customer.phone
            }
        }

        admin_resp = await http_client.post(admin_url, json=admin_payload, headers=headers)

        if admin_resp.status_code != 200:
            logger.error(f"Admin user creation failed: {admin_resp.text}")
            raise HTTPException(status_code=500, detail=f"Failed to create user: {admin_resp.text}")

        user_data_resp = admin_resp.json()
        user_id = user_data_resp.get("id")

        if not user_id:
            raise HTTPException(status_code=500, detail="Failed to get user ID from creation response")

        profile_data = {
            "id": user_id,
            "email": customer.email,
            "first_name": customer.first_name,
            "last_name": customer.last_name,
            "phone": customer.phone,
            "membership_id": f"MEM-{user_id[:8]}",
            "status": "active",
            "current_points": customer.loyalty_points,
            "tier": customer.tier,
            "date_of_birth": customer.date_of_birth,
            "address": customer.address,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        profile_resp = await http_client.post(
            f"{SUPABASE_URL}/rest/v1/profiles",
            json=profile_data,
            headers=headers
        )

        if profile_resp.status_code not in [200, 201]:
            logger.error(f"Profile creation failed: {profile_resp.text}")
            await http_client.delete(f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=headers)
            raise HTTPException(status_code=500, detail="Failed to create profile")

        member_data = {
            "user_id": user_id,
            "org_id": org_id,
            "role": "customer",
            "joined_at": datetime.now(timezone.utc).isoformat()
        }

        member_resp = await http_client.post(
            f"{SUPABASE_URL}/rest/v1/org_members",
            json=member_data,
            headers=headers
        )

        if member_resp.status_code not in [200, 201]:
            logger.error(f"Org member creation failed: {member_resp.text}")
            await http_client.delete(f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}", headers=headers)
            await http_client.delete(f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=headers)
            raise HTTPException(status_code=500, detail="Failed to assign user to organisation")

    await _admin_set_app_metadata(user_id, {
        "org_id": org_id,
        "role": "customer",
        "branch_scope": None,
    })

    login_link = f"{PRODUCTION_HOST}/kdsiginin"
    html_content = f"""
    <h2>Welcome to Kevs Digital!</h2>
    <p>Hello {customer.first_name},</p>
    <p>Your customer account has been created. You can log in using the following credentials:</p>
    <p><strong>Email:</strong> {customer.email}<br>
    <strong>Temporary Password:</strong> <code>{temp_password}</code></p>
    <p>Please login here: <a href="{login_link}">{login_link}</a> and change your password immediately.</p>
    <p>You can view your loyalty points and manage your account after logging in.</p>
    <br>
    <p>Thank you for joining us!</p>
    """
    await send_sendgrid_email(customer.email, "Your customer account has been created", html_content)

    return {
        "message": "Customer registered successfully. Welcome email with temporary password sent.",
        "user_id": user_id,
        "temporary_password": temp_password
    }

# ------------------------------------------------------------------
# DIAGNOSTIC & ROOT
# ------------------------------------------------------------------
@app.get("/api/diagnose")
async def diagnose(request: Request):
    await rate_limit(get_client_ip(request))
    client = get_supabase()
    embedder_status = "loaded" if get_embedder() is not None else "not available"
    return {
        "supabase_ok": client is not None,
        "rag_top_k": RAG_TOP_K,
        "rag_threshold": RAG_THRESHOLD,
        "ai_temperature": AI_TEMPERATURE,
        "paystack_configured": bool(PAYSTACK_SECRET_KEY),
        "flutterwave_configured": bool(FLUTTERWAVE_SECRET_KEY),
        "rate_limiting_enabled": RATE_LIMIT_ENABLED,
        "embedder_status": embedder_status,
        "guardrail_active": True
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/health/deep")
async def health_deep(request: Request):
    """
    Deep health check. Pings every critical subsystem.
    Returns 200 always; the JSON body carries the per-subsystem status.
    Uptime monitors can poll this every 60s.
    """
    await rate_limit(get_client_ip(request))
    checks: Dict[str, Dict] = {}
    client = get_supabase()

    # ── 1. Database connectivity ──
    try:
        await run_sync_db_call(
            client.table("organisations").select("id").limit(1).execute
        )
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "fail", "error": str(e)[:200]}

    # ── 2 & 3. RPCs and tables via health_check_schema RPC ──
    expected_rpcs = [
        "approve_stock_transfer",
        "complete_stock_transfer",
        "decrement_stock_fefo",
        "finalize_online_order",
        "claim_webhook_event",
        "mark_webhook_event_processed",
        "release_webhook_event_claim",
        "audit_stock_drift",
        "heal_stock_drift",
        "match_knowledge_documents",
    ]
    expected_tables = [
        "organisations", "profiles", "org_members",
        "inventory", "locations", "location_stocks", "stock_transfers",
        "sales", "sale_items",
        "accounts_receivable", "accounts_payable",
        "webhook_events", "general_knowledge", "support_tickets",
    ]
    try:
        schema_res = await run_sync_db_call(
            client.rpc("health_check_schema", {}).execute
        )
        schema = schema_res.data if schema_res else None
        if isinstance(schema, list):
            schema = schema[0] if schema else {}
        schema = schema or {}
        found_rpcs = set(schema.get("rpcs") or [])
        found_tables = set(schema.get("tables") or [])

        missing_rpcs = sorted(set(expected_rpcs) - found_rpcs)
        if missing_rpcs:
            checks["rpcs"] = {"status": "fail", "missing": missing_rpcs}
        else:
            checks["rpcs"] = {"status": "ok", "count": len(found_rpcs)}

        missing_tables = sorted(set(expected_tables) - found_tables)
        if missing_tables:
            checks["tables"] = {"status": "fail", "missing": missing_tables}
        else:
            checks["tables"] = {"status": "ok", "count": len(found_tables)}
    except Exception as e:
        checks["rpcs"] = {"status": "fail", "error": str(e)[:200]}
        checks["tables"] = {"status": "fail", "error": str(e)[:200]}

    # ── 4. Storage bucket ──
    try:
        buckets = await run_sync_db_call(client.storage.list_buckets)
        names = set()
        for b in (buckets or []):
            n = getattr(b, "name", None)
            if n is None and isinstance(b, dict):
                n = b.get("name")
            if n:
                names.add(n)
        if "storefront" in names:
            checks["storage"] = {"status": "ok"}
        else:
            checks["storage"] = {"status": "fail", "error": "bucket 'storefront' missing"}
    except Exception as e:
        checks["storage"] = {"status": "fail", "error": str(e)[:200]}

    # ── 5. Embedder (RAG) ──
    if get_embedder() is not None:
        checks["embedder"] = {"status": "ok"}
    else:
        checks["embedder"] = {"status": "fail"}

    # ── Overall ──
    failed = [k for k, v in checks.items() if v.get("status") != "ok"]
    overall = "healthy" if not failed else "degraded"

    return {
        "status": overall,
        "failed": failed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }

@app.get("/chat-widget.js", response_class=PlainTextResponse)
async def widget():
    api_url = PRODUCTION_HOST
    return f"""
    (function(){{
        const apiUrl = '{api_url}';
        let sessionId = localStorage.getItem('pf_session');
        if (!sessionId) {{
            sessionId = 'web_' + Date.now() + '_' + Math.random().toString(36).substr(2, 8);
            localStorage.setItem('pf_session', sessionId);
        }}
        let authToken = localStorage.getItem('pf_auth_token');
        const win = document.createElement('div');
        win.innerHTML = `<div id="pf-btn" style="position:fixed;bottom:20px;right:20px;width:60px;height:60px;background:#6b4b9a;border-radius:50%;cursor:pointer;z-index:10000;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 12px rgba(0,0,0,0.2);"><svg width="30" height="30" viewBox="0 0 24 24" fill="white"><path d="M20 2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h14l4 4V4c0-1.1-.9-2-2-2z"/></svg></div>
        <div id="pf-chat" style="position:fixed;bottom:90px;right:20px;width:350px;height:550px;background:white;display:none;flex-direction:column;border-radius:12px;z-index:10000;box-shadow:0 8px 24px rgba(0,0,0,0.2);overflow:hidden;">
            <div style="background:#6b4b9a;color:white;padding:12px;display:flex;justify-content:space-between;">
                <span>Penafort Assistant</span>
                <div><span id="pf-auth-btn" style="cursor:pointer;margin-right:10px;">🔐</span><span id="pf-close" style="cursor:pointer;">×</span></div>
            </div>
            <div id="pf-msgs" style="flex:1;overflow-y:auto;padding:10px;background:#f8f9fa;"></div>
            <div style="padding:10px;display:flex;gap:8px;border-top:1px solid #ddd;">
                <input id="pf-input" placeholder="Ask a question..." style="flex:1;padding:8px;border-radius:20px;border:1px solid #ddd;">
                <button id="pf-send" style="background:#6b4b9a;color:white;border:none;padding:8px 16px;border-radius:20px;">Send</button>
            </div>
        </div>`;
        document.body.appendChild(win);
        const btn = document.getElementById('pf-btn');
        const chatDiv = document.getElementById('pf-chat');
        const closeBtn = document.getElementById('pf-close');
        const authBtn = document.getElementById('pf-auth-btn');
        const input = document.getElementById('pf-input');
        const sendBtn = document.getElementById('pf-send');
        const msgsDiv = document.getElementById('pf-msgs');
        function addMsg(txt,role){{
            const d = document.createElement('div');
            d.style.padding = '8px 12px'; d.style.borderRadius = '12px'; d.style.margin = '4px'; d.style.maxWidth = '80%'; d.style.wordWrap = 'break-word';
            d.style.alignSelf = role==='user' ? 'flex-end' : 'flex-start';
            d.style.background = role==='user' ? '#6b4b9a' : '#e9ecef';
            d.style.color = role==='user' ? 'white' : 'black';
            d.innerText = txt;
            msgsDiv.appendChild(d);
            msgsDiv.scrollTop = msgsDiv.scrollHeight;
        }}
        async function send(){{
            const val = input.value.trim();
            if(!val) return;
            addMsg(val,'user');
            input.value = '';
            try{{
                const headers = {{'Content-Type':'application/json'}};
                if (authToken) headers['Authorization'] = 'Bearer '+authToken;
                const res = await fetch(apiUrl+'/support/chat-stream',{{method:'POST',headers:headers,body:JSON.stringify({{session_id:sessionId, message:val}})}});
                const data = await res.json();
                addMsg(data.response,'ai');
            }}catch(e){{
                addMsg('Network error','ai');
            }}
        }}
        async function authAction(){{
            if(authToken){{
                try{{
                    await fetch(apiUrl+'/auth/logout',{{method:'POST',headers:{{'Authorization':'Bearer '+authToken}}}});
                }}catch(e){{
                }}
                localStorage.removeItem('pf_auth_token');
                authToken = null;
                addMsg('🔓 Logged out.','system');
                setTimeout(()=>window.location.reload(),1500);
            }}else{{
                const email = prompt('Email:');
                if(!email) return;
                const password = prompt('Password:');
                if(!password) return;
                let action = confirm('Press OK to Login, Cancel to Register');
                let endpoint = action ? '/auth/login' : '/auth/register';
                try{{
                    const res = await fetch(apiUrl+endpoint,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email,password}})}});
                    const data = await res.json();
                    if(res.ok && data.access_token){{
                        authToken = data.access_token;
                        localStorage.setItem('pf_auth_token', authToken);
                        addMsg('✅ Logged in!','system');
                        setTimeout(()=>window.location.reload(),1500);
                    }}else{{
                        addMsg('Auth failed: '+(data.detail||'Error'),'system');
                    }}
                }}catch(e){{
                    addMsg('Login error','system');
                }}
            }}
        }}
        authBtn.onclick = authAction;
        btn.onclick = ()=> chatDiv.style.display = 'flex';
        closeBtn.onclick = ()=> chatDiv.style.display = 'none';
        sendBtn.onclick = send;
        input.onkeypress = e => e.key==='Enter' && send();
        addMsg('Hello! I am your AI assistant. Ask me anything.','ai');
        if(authToken) addMsg('🔐 Logged in.','system');
        else addMsg('🔓 Guest.','system');
    }})();
    """

# ------------------------------------------------------------------
# NEW INTELLIGENCE MODULE
# ------------------------------------------------------------------
class ReportMode(str, Enum):
    CHAT = "chat"
    REPORT = "report"
    DASHBOARD = "dashboard"

class ChatRequest(BaseModel):
    message: str
    history: List[Dict] = []
    report_mode: ReportMode = ReportMode.CHAT
    force_pillar: Optional[int] = None

class MetricsEngine:
    @staticmethod
    def compute(org_id: str, budget: Optional[int] = None) -> Dict:
        client = get_supabase()
        leads = client.table("org_leads").select("*").eq("org_id", org_id).execute().data or []
        total = len(leads)
        converted = sum(1 for l in leads if l.get("status") == "converted")
        conv_rate = round((converted / total) * 100, 2) if total > 0 else 0
        pipeline = sum(l.get("deal_value", 0) for l in leads if l.get("status") in ["warm", "converted"])
        ad_spend = sum(l.get("ad_spend", 0) for l in leads if l.get("status") == "converted")
        cac = ad_spend / converted if converted > 0 else 0
        deal_sum = sum(l.get("deal_value", 0) for l in leads if l.get("status") == "converted")
        roi = ((deal_sum - ad_spend) / ad_spend) * 100 if ad_spend > 0 else 0
        complete = sum(1 for l in leads if l.get("name") and l.get("email") and l.get("phone"))
        data_quality = round((complete / total) * 100, 2) if total > 0 else 0

        source_stats = {}
        for l in leads:
            src = l.get("source", "unknown")
            if src not in source_stats:
                source_stats[src] = {"total": 0, "converted": 0}
            source_stats[src]["total"] += 1
            if l.get("status") == "converted":
                source_stats[src]["converted"] += 1
        top_sources = [
            {"source": s, "total": stats["total"], "converted": stats["converted"], "conv_rate": round((stats["converted"]/stats["total"])*100,2) if stats["total"]>0 else 0}
            for s, stats in source_stats.items()
        ]
        top_sources.sort(key=lambda x: x["conv_rate"], reverse=True)
        return {
            "total_leads": total,
            "conversion_rate": conv_rate,
            "actual_cac": round(cac, 2),
            "roi": round(roi, 2),
            "pipeline_value": round(pipeline, 2),
            "data_quality": data_quality,
            "top_sources": top_sources[:5]
        }

class StrategyEngine:
    PILLAR_KEYWORDS = {
        1: ["who", "customer", "student", "buy", "need", "journey", "segment", "persona", "audience"],
        2: ["competitor", "market", "threat", "opportunity", "industry", "rivalry", "swot", "pestle"],
        3: ["strength", "resource", "capability", "operations", "value chain", "model", "efficiency"],
        4: ["revenue", "profit", "cac", "clv", "ltv", "unit economics", "roi", "margin", "leads", "conversion"],
    }
    PILLAR_CONFIG = {
        1: {"frameworks": ["Customer Journey Mapping", "Jobs to be Done"], "goal": "Mapping customer psychology", "message": "Customer intelligence lens"},
        2: {"frameworks": ["SWOT", "Porter's Five Forces"], "goal": "Competitive positioning", "message": "Market intelligence lens"},
        3: {"frameworks": ["VRIO", "Value Chain"], "goal": "Internal capabilities audit", "message": "Operational lens"},
        4: {"frameworks": ["Unit Economics", "TAM-SAM-SOM"], "goal": "Growth economics", "message": "Growth economics lens"},
    }

    @classmethod
    def select_pillar(cls, query: str, metrics: dict, force_pillar: Optional[int] = None) -> dict:
        if force_pillar and force_pillar in cls.PILLAR_CONFIG:
            cfg = cls.PILLAR_CONFIG[force_pillar]
            return {**cfg, "pillar": force_pillar, "status": "READY"}
        q_lower = query.lower()
        scores = {p: sum(1 for kw in kws if kw in q_lower) for p, kws in cls.PILLAR_KEYWORDS.items()}
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return {"pillar": 3, "status": "SYNTHESIS", "frameworks": ["Business Model Canvas"], "goal": "Cross-functional optimisation", "message": "Synthesis mode"}
        cfg = cls.PILLAR_CONFIG[best]
        has_leads = metrics.get("total_leads", 0) > 0
        has_converted = metrics.get("conversion_rate", 0) > 0
        if best == 1 and not has_leads:
            status = "DATA_MISSING"
        elif best == 4 and not has_converted:
            status = "PARTIAL"
        else:
            status = "READY"
        return {**cfg, "pillar": best, "status": status}

class MemoryService:
    @staticmethod
    async def retrieve(query: str, org_id: str) -> str:
        client = get_supabase()
        result = await run_sync_db_call(
            client.table("intelligence_history")
            .select("query, response")
            .eq("org_id", org_id)
            .order("created_at", desc=True)
            .limit(3)
            .execute
        )
        if not result.data:
            return ""
        memories = []
        for row in reversed(result.data):
            memories.append(f"Past Q: {row['query']}\nPast A: {row['response'][:300]}")
        return "\n\n".join(memories)

class UsageService:
    @staticmethod
    async def check_usage_gate(org_id: str) -> Dict:
        client = get_supabase()
        org = await run_sync_db_call(
            client.table("organisations")
            .select("plan")
            .eq("id", org_id)
            .maybe_single()
            .execute
        )
        plan = org.data.get("plan", "free") if org and org.data else "free"
        is_premium = plan in ["pro", "enterprise"]
        if is_premium:
            return {"remaining": -1, "is_premium": True, "plan": plan, "request_count": 0}

        now = datetime.now(timezone.utc)
        month_year = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).date().isoformat()

        usage = await run_sync_db_call(
            client.table("intelligence_usage")
            .select("request_count")
            .eq("org_id", org_id)
            .eq("month_year", month_year)
            .maybe_single()
            .execute
        )
        count = usage.data["request_count"] if usage and usage.data else 0
        remaining = max(0, 50 - count)
        return {"remaining": remaining, "is_premium": False, "plan": plan, "request_count": count}

    @staticmethod
    async def increment_usage(org_id: str):
        client = get_supabase()
        now = datetime.now(timezone.utc)
        month_year = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).date().isoformat()

        existing = await run_sync_db_call(
            client.table("intelligence_usage")
            .select("request_count")
            .eq("org_id", org_id)
            .eq("month_year", month_year)
            .maybe_single()
            .execute
        )

        if existing and existing.data:
            new_count = existing.data["request_count"] + 1
            await run_sync_db_call(
                client.table("intelligence_usage")
                .update({"request_count": new_count, "updated_at": now.isoformat()})
                .eq("org_id", org_id)
                .eq("month_year", month_year)
                .execute
            )
            return

        try:
            await run_sync_db_call(
                client.table("intelligence_usage")
                .insert({
                    "org_id": org_id,
                    "month_year": month_year,
                    "request_count": 1,
                    "updated_at": now.isoformat()
                })
                .execute
            )
        except Exception as e:
            if 'duplicate key' in str(e).lower():
                existing2 = await run_sync_db_call(
                    client.table("intelligence_usage")
                    .select("request_count")
                    .eq("org_id", org_id)
                    .maybe_single()
                    .execute
                )
                if existing2 and existing2.data:
                    new_count = existing2.data["request_count"] + 1
                    await run_sync_db_call(
                        client.table("intelligence_usage")
                        .update({
                            "request_count": new_count,
                            "updated_at": now.isoformat(),
                            "month_year": month_year
                        })
                        .eq("org_id", org_id)
                        .execute
                    )
                else:
                    raise
            else:
                raise

class AIOrchestrator:
    @staticmethod
    async def generate(system_prompt: str, user_prompt: str) -> Tuple[str, str, float]:
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        start = time.time()
        model = "openai/gpt-oss-120b" if GROQ_API_KEY else "gemini"
        answer = await call_llm(full_prompt)
        latency = time.time() - start
        return answer, model, latency

class OutputValidator:
    FRAMEWORK_SUBS = {
        r"\bSWOT\b": "a strategic review",
        r"\bPESTLE\b": "an environmental scan",
        r"\bVRIO\b": "a capability assessment",
        r"\bBCG\s*[Mm]atrix\b": "a portfolio review",
        r"\bAnsoff\b": "a growth pathway analysis",
        r"\bPorter'?s?\b": "a competitive structure analysis",
        r"\bJTBD\b": "a customer needs analysis",
        r"\bTAM[- ]SAM[- ]SOM\b": "a market sizing analysis",
        r"\bNPS\b": "a loyalty score",
        r"\b[Ff]ramework[s]?\b": "approach",
        r"\b[Mm]atrix\b": "model",
        r"\b[Cc]anvas\b": "model",
        r"\bPillar \d\b": "",
        r"\bP[1-4]\b": "",
    }
    OVERCONFIDENCE_PATTERNS = [
        re.compile(r"(guaranteed|certain|definite)\s+(return|profit|revenue)", re.IGNORECASE),
        re.compile(r"(will definitely|will certainly|100%\s+sure)", re.IGNORECASE),
    ]

    @classmethod
    def validate(cls, text: str) -> Tuple[str, List[str]]:
        warnings = []
        cleaned = text
        for pattern, repl in cls.FRAMEWORK_SUBS.items():
            cleaned = re.compile(pattern, re.IGNORECASE).sub(repl, cleaned)
        for pat in cls.OVERCONFIDENCE_PATTERNS:
            if pat.search(cleaned):
                warnings.append(f"Overconfidence detected")
        if re.search(r"₦[\d,]+", cleaned) and not re.search(r"(estimate|approximate|based on|assuming|projection)", cleaned, re.IGNORECASE):
            cleaned += "\n\n_Note: Financial figures are directional estimates. Validate against actual records before acting._"
            warnings.append("Financial disclaimer appended")
        return cleaned, warnings

# ------------------------------------------------------------------
# Intelligence Endpoints
# ------------------------------------------------------------------
@app.post("/intelligence/chat")
async def intelligence_chat(req: ChatRequest, ctx: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "sales_rep"]))):
    user_id, org_id, _ = ctx
    usage = await UsageService.check_usage_gate(org_id)
    if not usage["is_premium"] and usage["remaining"] <= 0:
        raise HTTPException(status_code=429, detail="Monthly strategy chat limit reached. Upgrade your plan.")
    metrics = MetricsEngine.compute(org_id, None)
    pillar_info = StrategyEngine.select_pillar(req.message, metrics, req.force_pillar)
    memory = await MemoryService.retrieve(req.message, org_id)
    history_text = ""
    if req.history:
        recent = req.history[-6:]
        lines = []
        for m in recent:
            role = m.get("role", "user")
            content = m.get("content") or m.get("text") or m.get("message") or ""
            lines.append(f"{role}: {content}")
        history_text = "\n".join(lines)[:1500]
    def build_system_prompt(pillar: dict, org_id: str, metrics: dict, mode: str) -> str:
        return f"""You are a strategic business intelligence advisor for an organisation.
Your persona: data‑driven, concise, actionable.
Strategic lens: {pillar['message']} (Pillar {pillar['pillar']})
Frameworks: {', '.join(pillar.get('frameworks', []))}
Goal: {pillar.get('goal', 'Provide insights')}
Current metrics snapshot:
- Total leads: {metrics['total_leads']}
- Conversion rate: {metrics['conversion_rate']}%
- Actual CAC: ₦{metrics['actual_cac']}
- Pipeline value: ₦{metrics['pipeline_value']}
- Data quality: {metrics['data_quality']}%
Top lead sources: {metrics.get('top_sources', [])}
Mode: {mode} (chat=concise, report=structured, dashboard=highlight KPIs)
Do not repeat framework names. If data is missing, state that clearly. Answer in plain text, no markdown."""
    system = build_system_prompt(pillar_info, org_id, metrics, req.report_mode.value)
    user_prompt = f"HISTORY:\n{history_text}\nMEMORY:\n{memory}\nQUESTION: {req.message}"
    answer, model_used, latency = await AIOrchestrator.generate(system, user_prompt)
    answer, warnings = OutputValidator.validate(answer)
    client = get_supabase()
    await run_sync_db_call(
        client.table("intelligence_history").insert({
            "org_id": org_id,
            "user_id": user_id,
            "query": req.message[:500],
            "response": answer[:2000],
            "pillar": pillar_info["pillar"],
            "model": model_used,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute
    )
    await UsageService.increment_usage(org_id)
    updated_usage = await UsageService.check_usage_gate(org_id)
    return {
        "status": "success",
        "response": answer,
        "mode": req.report_mode,
        "metrics_snapshot": {
            "total_leads": metrics["total_leads"],
            "conversion_rate": metrics["conversion_rate"],
            "actual_cac": metrics["actual_cac"],
            "pipeline_value": metrics["pipeline_value"],
            "data_quality": metrics["data_quality"],
        },
        "usage": {
            "requests_used": updated_usage["request_count"],
            "remaining": updated_usage["remaining"],
            "is_premium": updated_usage["is_premium"],
            "plan": updated_usage["plan"],
        },
        "meta": {
            "model": model_used,
            "data_status": pillar_info.get("status", "READY"),
            "pillar": pillar_info["pillar"],
        },
    }

@app.get("/intelligence/history")
async def get_intelligence_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "sales_rep"]))
):
    _, org_id, _ = ctx
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("intelligence_history")
        .select("id, query, response, created_at, pillar, model")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute
    )
    return {"history": result.data or []}

@app.get("/intelligence/history/{conv_id}")
async def get_intelligence_conversation(conv_id: str, ctx: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "sales_rep"]))):
    _, org_id, _ = ctx
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("intelligence_history")
        .select("*")
        .eq("id", conv_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation": result.data}

# ============================================================
# ALERT MANAGEMENT
# ============================================================
@app.get("/alerts")
async def get_alerts(
    request: Request,
    status: Optional[str] = None,
    alert_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    try:
        query = (
            client.table("alert_log")
            .select(
                "id, alert_type, details, created_at, action_taken, action_date, "
                "batch, item_code, description"
            )
            .eq("org_id", org_id)          # ← the missing line
        )
        if alert_type:
            query = query.eq("alert_type", alert_type)
        if status == "Active":
            query = query.is_("action_taken", "null")
        elif status == "Resolved":
            query = query.not_.is_("action_taken", "null")

        result = await run_sync_db_call(
            query.order("created_at", desc=True).range(offset, offset + limit - 1).execute
        )
        alerts_data = result.data or []

        alerts = []
        for row in alerts_data:
            alerts.append({
                "id": row.get('id'),
                "alert_type": row.get('alert_type', 'Unknown'),
                "details": row.get('details', ''),
                "created_at": row.get('created_at'),
                "is_resolved": row.get('action_taken') is not None,
                "action_taken": row.get('action_taken'),
                "action_date": row.get('action_date'),
                "batch": row.get('batch'),
                "product_name": row.get('description', 'Unknown'),
                "product_sku": row.get('item_code', 'N/A')
            })

        return {
            "alerts": alerts,
            "total": len(alerts),
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        logger.error(f"Error fetching alerts: {e}")
        return {
            "alerts": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "message": "Alert table not configured"
        }
        
@app.get("/alerts/dashboard")
async def get_alert_dashboard(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    try:
        alerts = await run_sync_db_call(
            client.table("alert_log")
            .select("alert_type, action_taken")
            .eq("org_id", org_id)          # ← the missing line
            .execute
        )
        alerts_data = alerts.data or []
        total_alerts = len(alerts_data)
        resolved = sum(1 for a in alerts_data if a.get('action_taken') is not None)
        compliance = round(resolved / total_alerts * 100, 1) if total_alerts else 0
        active = total_alerts - resolved

        type_counts = {}
        for alert in alerts_data:
            alert_type = alert.get('alert_type', 'Unknown')
            type_counts[alert_type] = type_counts.get(alert_type, 0) + 1

        return {
            "total_alerts": total_alerts,
            "active_alerts": active,
            "resolved_alerts": resolved,
            "compliance_rate": compliance,
            "alert_type_breakdown": type_counts,
            "status_counts": {"Active": active, "Resolved": resolved}
        }
    except:
        return {
            "total_alerts": 0,
            "active_alerts": 0,
            "resolved_alerts": 0,
            "compliance_rate": 0,
            "alert_type_breakdown": {},
            "status_counts": {"Active": 0, "Resolved": 0}
        }


@app.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    request: Request,
    alert_id: int,
    action_data: dict,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    # Ownership check first
    existing = await run_sync_db_call(
        client.table("alert_log")
        .select("id")
        .eq("id", alert_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Alert not found")

    try:
        await run_sync_db_call(
            client.table("alert_log").update({
                "action_taken": action_data.get("action_type", "ACKNOWLEDGE"),
                "action_date": datetime.now(timezone.utc).isoformat(),
                "action_notes": action_data.get("notes", f"Resolved by {user_id}")
            }).eq("id", alert_id).eq("org_id", org_id).execute
        )
        return {"success": True, "message": f"Alert {alert_id} resolved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve alert: {str(e)}")


# ============================================================
# RISK SCORES
# ============================================================
@app.get("/risk-scores")
async def get_risk_scores(
    request: Request,
    risk_level: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    try:
        # Primary path. The view already exposes org_id, so this is a
        # straight filter. Without it, a fresh org sees every tenant's
        # inventory risk rows.
        query = client.table("view_risk_list").select("*").eq("org_id", org_id)
        if risk_level:
            query = query.eq("risk_level", risk_level)
        result = await run_sync_db_call(query.range(offset, offset + limit - 1).execute)

        scores = []
        for row in result.data or []:
            scores.append({
                "id": row.get('id'),
                "product_name": row.get('product_name', 'Unknown'),
                "sku": row.get('sku', 'N/A'),
                "batch": row.get('batch'),
                "quantity": row.get('quantity', 0),
                "financial_value": float(row.get('financial_value', 0)),
                "expiry_date": row.get('expiry_date'),
                "days_to_expiry": row.get('days_to_expiry'),
                "risk_score": row.get('risk_score', 0),
                "risk_level": row.get('risk_level', 'LOW')
            })

        return {
            "risk_scores": scores,
            "total": len(scores),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        # Fallback. Rewritten against the live inventory schema. The
        # previous fallback selected inventory.product_id, .batch,
        # .quantity, and .cost — none of which exist — and joined
        # products on a nonexistent column. It always threw, so this
        # block was effectively an empty-list generator. Now it is a
        # real, org-scoped scan with correct column names.
        logger.warning(f"risk-scores primary path failed, falling back: {e}")
        try:
            inventory = await run_sync_db_call(
                client.table("inventory")
                .select("id, description, item_code, batch_number, current_qty, expiry_date, cost_price_naira")
                .eq("org_id", org_id)
                .execute
            )
            inv_data = inventory.data or []

            scores = []
            today = date.today()
            for item in inv_data:
                expiry = item.get('expiry_date')
                days_to_expiry = None
                if expiry:
                    try:
                        expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date() if isinstance(expiry, str) else expiry
                        days_to_expiry = (expiry_date - today).days
                    except Exception:
                        pass

                risk_level_val = "LOW"
                risk_score_val = 10
                if days_to_expiry is not None:
                    if days_to_expiry <= 120:
                        risk_level_val = "CRITICAL"
                        risk_score_val = 100
                    elif days_to_expiry <= 180:
                        risk_level_val = "HIGH"
                        risk_score_val = 90
                    elif days_to_expiry <= 270:
                        risk_level_val = "MODERATE"
                        risk_score_val = 75

                qty = int(item.get('current_qty') or 0)
                cost = float(item.get('cost_price_naira') or 0)

                scores.append({
                    "id": item.get('id'),
                    "product_name": item.get('description', 'Unknown'),
                    "sku": item.get('item_code', 'N/A'),
                    "batch": item.get('batch_number'),
                    "quantity": qty,
                    "financial_value": float(qty * cost),
                    "expiry_date": item.get('expiry_date'),
                    "days_to_expiry": days_to_expiry,
                    "risk_score": risk_score_val,
                    "risk_level": risk_level_val
                })

            if risk_level:
                scores = [s for s in scores if s['risk_level'] == risk_level]

            return {
                "risk_scores": scores,
                "total": len(scores),
                "limit": limit,
                "offset": offset
            }
        except Exception as e2:
            logger.error(f"risk-scores fallback also failed: {e2}")
            return {
                "risk_scores": [],
                "total": 0,
                "limit": limit,
                "offset": offset
            }

@app.get("/risk-scores/summary")
async def get_risk_summary(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data

    try:
        data = await get_risk_scores(request, user_data=user_data)
        scores = data.get("risk_scores", [])

        risk_counts = {"CRITICAL": 0, "HIGH": 0, "MODERATE": 0, "LOW": 0}
        critical_items = []
        total_value = 0

        for row in scores:
            level = row.get('risk_level', 'LOW')
            if level in risk_counts:
                risk_counts[level] += 1

            if level == "CRITICAL" and row.get('days_to_expiry', 999) <= 120:
                critical_items.append(row)

            total_value += float(row.get('financial_value', 0))

        return {
            "risk_distribution": risk_counts,
            "critical_items_count": len(critical_items),
            "total_financial_value": round(total_value, 2),
            "critical_items": critical_items[:20]
        }
    except:
        return {
            "risk_distribution": {"CRITICAL": 0, "HIGH": 0, "MODERATE": 0, "LOW": 0},
            "critical_items_count": 0,
            "total_financial_value": 0,
            "critical_items": []
        }


# ============================================================
# STOCK LIMITS
# ============================================================
@app.get("/stock-limits")
async def get_stock_limits(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    try:
        # org_id scoping is the only boundary. The service-role client
        # bypasses RLS, so without this filter a fresh org would see
        # every stock_limits row in the platform.
        #
        # Selected columns are the ones that actually exist on
        # stock_limits (verified 2026-10-13 via information_schema).
        # The previous shape returned branch_id and product_id, neither
        # of which exists on this table — they were always null.
        query = (
            client.table("stock_limits")
            .select(
                "id, org_id, location_id, inventory_id, "
                "avg_daily_demand, safety_stock, reorder_point, max_stock, "
                "calculated_at, updated_at"
            )
            .eq("org_id", org_id)
        )
        result = await run_sync_db_call(query.range(offset, offset + limit - 1).execute)
        rows = result.data or []

        # ── Enrich with product + location display fields. ──

        # Inventory: both sides are INTEGER (stock_limits.inventory_id
        # and inventory.id), so a bounded .in_() lookup is safe and
        # cheap. Scoped to the org for defence in depth — a stray
        # inventory_id pointing at another tenant's row cannot leak
        # that row's description.
        inventory_ids = list({r["inventory_id"] for r in rows if r.get("inventory_id")})
        inv_map: Dict[int, Dict] = {}
        if inventory_ids:
            inv_res = await run_sync_db_call(
                client.table("inventory")
                .select("id, description, item_code, current_qty")
                .eq("org_id", org_id)
                .in_("id", inventory_ids)
                .execute
            )
            inv_map = {p["id"]: p for p in (inv_res.data or [])}

        # Locations: locations.id type has been inconsistent across
        # this codebase's migrations (INTEGER in some, UUID in others).
        # Rather than bet on one, pull the org's locations once and
        # match on str() for both sides. An org has a handful of
        # locations, so the full pull is cheap and safe regardless of
        # which type is live.
        loc_map: Dict[str, str] = {}
        loc_res = await run_sync_db_call(
            client.table("locations")
            .select("id, name")
            .eq("org_id", org_id)
            .execute
        )
        for l in (loc_res.data or []):
            loc_map[str(l.get("id"))] = l.get("name")

        limits = []
        for row in rows:
            inv = inv_map.get(row.get("inventory_id")) or {}
            loc_name = loc_map.get(str(row.get("location_id")))
            limits.append({
                "id":               row.get("id"),
                "org_id":           row.get("org_id"),
                "inventory_id":     row.get("inventory_id"),
                "location_id":      row.get("location_id"),

                # Enriched display fields. null when the FK points at
                # a missing or foreign inventory/location row.
                "product_name":     inv.get("description"),
                "sku":              inv.get("item_code"),
                "current_qty":      inv.get("current_qty"),
                "location_name":    loc_name,

                "avg_daily_demand": float(row.get("avg_daily_demand") or 0),
                "safety_stock":     int(row.get("safety_stock") or 0),
                "reorder_point":    int(row.get("reorder_point") or 0),
                "max_stock":        int(row.get("max_stock") or 0),
                "calculated_at":    row.get("calculated_at"),
                "updated_at":       row.get("updated_at"),
            })

        return {
            "stock_limits": limits,
            "total": len(limits),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"Error fetching stock limits: {e}")
        return {
            "stock_limits": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "message": "Stock limits table not configured"
        }

# ============================================================
# DASHBOARD METRICS
# ============================================================
@app.get("/dashboard/metrics")
async def get_dashboard_metrics(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    total_val = 0.0
    waste_val = 0.0
    active_alerts = 0
    compliance = 0.0
    total_alerts = 0
    resolved = 0

    try:
        rpc_res = await run_sync_db_call(
            client.rpc("get_total_inventory_value", {"target_org_id": org_id}).execute
        )
        total_val = float(rpc_res.data or 0.0)
        logger.info(f"💰 RPC Computed Total Value (cost): {total_val}")

        risk_rpc_res = await run_sync_db_call(
            client.rpc("get_waste_risk_value", {
                "target_org_id": org_id,
                "days_threshold": 120
            }).execute
        )
        waste_val = float(risk_rpc_res.data or 0.0)
        logger.info(f"🚨 RPC Computed Waste Risk Value (120d): {waste_val}")

        # Two count-only queries, both scoped to the caller's org.
        # Previously this paginated the entire alert_log table 1000 rows at a
        # time and len()-ed the result in Python — no org filter, and the cost
        # grew linearly with total platform-wide alert volume. Now it is two
        # indexed COUNT(*)s constrained to one tenant.
        total_res = await run_sync_db_call(
            client.table("alert_log")
            .select("id", count="exact")
            .eq("org_id", org_id)
            .limit(1)
            .execute
        )
        total_alerts = total_res.count or 0

        resolved_res = await run_sync_db_call(
            client.table("alert_log")
            .select("id", count="exact")
            .eq("org_id", org_id)
            .not_.is_("action_taken", "null")
            .limit(1)
            .execute
        )
        resolved = resolved_res.count or 0

        active_alerts = total_alerts - resolved
        compliance = round(resolved / total_alerts * 100, 1) if total_alerts else 0.0

        logger.info(f"🚨 Alerts: total={total_alerts}, resolved={resolved}, compliance={compliance}%")

    except Exception as e:
        logger.error(f"❌ Dashboard metrics error: {e}", exc_info=True)

    return {
        "total_inventory_value": total_val,
        "waste_risk_120d": waste_val,
        "alert_compliance": compliance,
        "total_alerts": total_alerts,
        "active_alerts": active_alerts,
        "resolved_alerts": resolved,
        "alert_type_breakdown": {},
        "branch_id": None
    }
# ============================================================
# TRANSFER SUGGESTIONS
# ============================================================
@app.get("/transfer-suggestions")
async def get_transfer_suggestions(
    request: Request,
    location_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "logistics"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    try:
        # Primary query: relies on PostgREST FK inference for the
        # locations and inventory joins. org_id scoping is applied
        # here just as it is on the fallback below — if the service
        # role can see every row, the app-layer filter is the only
        # tenant boundary there is.
        query = client.table("transfer_suggestions").select(
            "id, from_location_id, to_location_id, inventory_id, batch, quantity, completed_quantity, "
            "urgency, reason, status, notes, created_at, updated_at, last_updated, "
            "from_location:locations!from_location_id(name), "
            "to_location:locations!to_location_id(name), "
            "inventory:inventory!inventory_id(description, item_code)"
        ).eq("org_id", org_id)

        if location_id:
            query = query.eq("from_location_id", location_id)

        if status and status != "All":
            query = query.eq("status", status)

        result = await run_sync_db_call(query.order("created_at", desc=True).range(offset, offset + limit - 1).execute)

        suggestions = []
        for row in result.data or []:
            inv = row.get("inventory") or {}
            suggestions.append({
                "id": row.get('id'),
                "from_location_id": row.get('from_location_id'),
                "from_location": row.get('from_location', {}).get('name') if row.get('from_location') else None,
                "to_location_id": row.get('to_location_id'),
                "to_location": row.get('to_location', {}).get('name') if row.get('to_location') else None,
                "product_name": inv.get('description'),
                "sku": inv.get('item_code'),
                "batch": row.get('batch'),
                "quantity": row.get('quantity', 0),
                "completed_quantity": row.get('completed_quantity', 0),
                "urgency": row.get('urgency'),
                "reason": row.get('reason'),
                "status": row.get('status', 'Pending'),
                "notes": row.get('notes'),
                "created_at": row.get('created_at'),
                "updated_at": row.get('updated_at'),
                "last_updated": row.get('last_updated')
            })

        return {
            "suggestions": suggestions,
            "total": len(suggestions),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"Error fetching transfer suggestions: {e}")
        # Fallback query. Still org-scoped. Without the org filter
        # here, a PostgREST join failure on the primary path would
        # silently degrade this endpoint to a full-table read.
        try:
            query = client.table("transfer_suggestions").select("*").eq("org_id", org_id)
            if location_id:
                query = query.eq("from_location_id", location_id)
            if status and status != "All":
                query = query.eq("status", status)
            result = await run_sync_db_call(query.order("created_at", desc=True).range(offset, offset + limit - 1).execute)

            suggestions = []
            for row in result.data or []:
                suggestions.append({
                    "id": row.get('id'),
                    "from_location_id": row.get('from_location_id'),
                    "to_location_id": row.get('to_location_id'),
                    "product_name": row.get('product_name'),
                    "sku": row.get('sku'),
                    "batch": row.get('batch'),
                    "quantity": row.get('quantity', 0),
                    "completed_quantity": row.get('completed_quantity', 0),
                    "urgency": row.get('urgency'),
                    "reason": row.get('reason'),
                    "status": row.get('status', 'Pending'),
                    "notes": row.get('notes'),
                    "created_at": row.get('created_at'),
                    "updated_at": row.get('updated_at'),
                    "last_updated": row.get('last_updated')
                })

            return {
                "suggestions": suggestions,
                "total": len(suggestions),
                "limit": limit,
                "offset": offset
            }
        except Exception as e2:
            logger.error(f"Fallback also failed: {e2}")
            return {
                "suggestions": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "message": "Unable to fetch transfer suggestions"
            }

# ============================================================
# PRODUCT MANAGEMENT
# ============================================================
@app.get("/products")
async def get_products(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    search: Optional[str] = None,
    category: Optional[str] = None,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "sales_rep", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    # org_id scoping is the tenant boundary. The service-role client
    # bypasses RLS, so without this filter the endpoint returns every
    # org's products.
    #
    # SELECT columns match the live products schema. The previous
    # definition selected shelf_life_days, which is not a column on
    # products — PostgREST rejected the request with a 400 on every
    # call. Removed. If shelf_life_days does exist on your schema,
    # add it back.
    query = (
        client.table("products")
        .select("id, org_id, sku, name, category, cost, created_at, updated_at")
        .eq("org_id", org_id)
    )

    if search:
        query = query.or_(f"sku.ilike.%{search}%,name.ilike.%{search}%")

    if category:
        query = query.eq("category", category)

    result = await run_sync_db_call(
        query.order("name", desc=False).range(offset, offset + limit - 1).execute
    )

    return {
        "products": result.data or [],
        "total": len(result.data) if result.data else 0,
        "limit": limit,
        "offset": offset
    }


@app.get("/products/search")
async def search_products(
    request: Request,
    q: str = Query(..., min_length=1),
    limit: int = 50,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "sales_rep"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    # Same select-column note as GET /products. Org-scoped.
    result = await run_sync_db_call(
        client.table("products")
        .select("id, org_id, sku, name, category, cost, created_at, updated_at")
        .eq("org_id", org_id)
        .or_(f"sku.ilike.%{q}%,name.ilike.%{q}%")
        .limit(limit)
        .execute
    )

    return {"results": result.data or []}



@app.put("/products/{product_id}")
async def update_product(
    request: Request,
    product_id: int,
    update_data: dict,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    # Ownership pre-flight. product_id is an integer, so a caller could
    # otherwise PUT against any tenant's product by guessing the id.
    # This makes the "not found" path indistinguishable from "belongs
    # to someone else" so the endpoint does not leak which ids exist.
    existing = await run_sync_db_call(
        client.table("products")
        .select("id")
        .eq("id", product_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Product not found")

    # The update itself is scoped too. Belt and braces: the pre-flight
    # covers the common case, and the .eq on the update closes any race
    # where the row is moved to a different org between the two calls.
    result = await run_sync_db_call(
        client.table("products")
        .update(update_data)
        .eq("id", product_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")

    return result.data[0]


@app.delete("/products/{product_id}")
async def delete_product(
    request: Request,
    product_id: int,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    # Ownership pre-flight, same reasoning as PUT.
    existing = await run_sync_db_call(
        client.table("products")
        .select("id")
        .eq("id", product_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Product not found")

    # NOTE: the previous version tried to cascade the delete into
    # inventory by matching inventory.product_id = product_id. That
    # column does not exist on inventory — the .eq() call would 400,
    # raise out of the endpoint, and the DELETE always 500'd. There is
    # no FK relationship between products and inventory in this schema,
    # so there is nothing to cascade. Removed.
    #
    # If your intent was "block the delete when the product is still
    # referenced by inventory", we would need a real linking column on
    # inventory first. That's a schema change, not an endpoint change.
    result = await run_sync_db_call(
        client.table("products")
        .delete()
        .eq("id", product_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")

    return {"message": "Product deleted successfully"}

# ============================================================
# SYSTEM LOGS
# ============================================================
@app.get("/system-logs")
async def get_system_logs(
    request: Request,
    level: Optional[str] = None,
    security_only: bool = False,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    query = client.table("system_logs").select("*").eq("org_id", org_id)

    if level:
        query = query.eq("level", level)

    if security_only:
        query = query.eq("security", True)

    result = await run_sync_db_call(query.order("timestamp", desc=True).range(offset, offset + limit - 1).execute)

    return {
        "logs": result.data,
        "total": len(result.data) or 0,
        "limit": limit,
        "offset": offset
    }

@app.post("/system-logs")
async def create_system_log(
    request: Request,
    log_data: dict,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data

    client = get_supabase()

    data = {
        "org_id": org_id,
        "branch_id": await resolve_branch_for_write(org_id),
        "user_id": user_id,
        "level": log_data.get("level", "INFO"),
        "message": log_data.get("message"),
        "extra": log_data.get("extra", {}),
        "security": log_data.get("security", False),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    result = await run_sync_db_call(client.table("system_logs").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create log entry")

    return {"message": "Log entry created"}

# NOTE: /branches, /branches POST, /branches/{branch_id}, /registered-emails
# have been REMOVED because they queried columns (storekeeper_email,
# procurement_email, inventory_email, auditor_email, manager_email) that do
# not exist on the current branches schema. They would 500 on every call.
# If you need branch CRUD, restore them against the real schema with
# org_id ownership checks.

# ------------------------------------------------------------------
# Serve HTML pages
# ------------------------------------------------------------------
@app.get("/")
async def root():
    return {"message": "Kevs Digital bOS API is running"}

@app.get("/kdstore", response_class=HTMLResponse)
async def serve_store():
    with open("kdstore.html", "r") as f:
        return f.read()


@app.get("/store/{slug}", response_class=HTMLResponse)
async def serve_storefront_for_org(slug: str):
    """
    Serves the storefront shell. The shell reads the slug from the URL
    and hydrates itself with /public/storefront/{slug}.
    """
    client = get_supabase()
    res = await run_sync_db_call(
        client.table("organisations")
        .select("id, slug, storefront_published")
        .eq("slug", slug)
        .maybe_single()
        .execute
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Store not found")

    # Feature gate: ecommerce must be enabled for the org
    await check_org_feature(res.data["id"], "ecommerce")

    with open("kdstore.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/store/{slug}/manifest.json")
async def serve_storefront_manifest(slug: str):
    """
    Per-org PWA manifest. Reads branding from storefront_config so each
    installed app carries the org's name and icon.
    """
    client = get_supabase()
    res = await run_sync_db_call(
        client.table("organisations")
        .select("org_name, storefront_config, storefront_published")
        .eq("slug", slug)
        .maybe_single()
        .execute
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Store not found")

    org = res.data
    if not org.get("storefront_published"):
        raise HTTPException(status_code=404, detail="Store is not yet live")

    cfg = merge_storefront_config(org.get("storefront_config"))
    branding = cfg.get("branding", {})
    store_name = branding.get("store_name") or org["org_name"]
    logo = branding.get("logo_url") or "/images/page_logo.webp"
    accent = branding.get("primary_color") or "#075c3a"

    manifest = {
        "name": store_name,
        "short_name": store_name[:12],
        "description": cfg.get("seo", {}).get("meta_description") or f"Shop at {store_name}",
        "start_url": f"/store/{slug}",
        "scope": f"/store/{slug}/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": branding.get("background") or "#ffffff",
        "theme_color": accent,
        "icons": [
            {"src": logo, "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": logo, "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }

    return JSONResponse(
        content=manifest,
        media_type="application/manifest+json",
    )

@app.get("/kdconc", response_class=HTMLResponse)
async def serve_conc():
    with open("kdconc.html", "r") as f:
        return f.read()

@app.get("/kdadmin", response_class=HTMLResponse)
async def serve_admin():
    with open("kdadmin.html", "r") as f:
        return f.read()

@app.get("/kddashboard", response_class=HTMLResponse)
async def serve_dashboard():
    with open("kddashboard.html", "r") as f:
        return f.read()

@app.get("/kdsiginin", response_class=HTMLResponse)
async def serve_sigin():
    with open("kdsiginin.html", "r") as f:
        return f.read()



@app.get("/kdstore.js")
async def serve_kdstore_js():
    path = os.path.join(BASE_DIR, "kdstore.js")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"kdstore.js not found at {path}")
    return FileResponse(path, media_type="application/javascript")




@app.get("/kdpos", response_class=HTMLResponse)
async def serve_pos():
    with open("kdpos.html", "r") as f:
        return f.read()

@app.get("/kdsupport", response_class=HTMLResponse)
async def serve_support():
    with open("kdsupport.html", "r") as f:
        return f.read()

@app.get("/kdbi", response_class=HTMLResponse)
async def serve_bi():
    with open("kdbi.html", "r") as f:
        return f.read()

@app.get("/kdfulfillment", response_class=HTMLResponse)
async def serve_fulfillment():
    with open("kdfulfillment.html", "r") as f:
        return f.read()

@app.get("/kdteam", response_class=HTMLResponse)
async def serve_team():
    with open("kdteam.html", "r") as f:
        return f.read()

@app.get("/kdknowledge", response_class=HTMLResponse)
async def serve_knowledge():
    with open("kdknowledge.html", "r") as f:
        return f.read()

@app.get("/kdprocurement", response_class=HTMLResponse)
async def serve_accounts():
    with open("kdprocurement.html", "r") as f:
        return f.read()

@app.get("/sw.js", response_class=PlainTextResponse)
async def serve_service_worker():
    with open("sw.js", "r") as f:
        return f.read()

@app.get("/kdaccount", response_class=HTMLResponse)
async def serve_accounts():
    with open("kdaccount.html", "r") as f:
        return f.read()

@app.get("/kdorgs", response_class=HTMLResponse)
async def serve_orgs_portal():
    with open("kdorgs.html", "r") as f:
        return f.read()



@dataclass
class LoadTestStats:
    name: str
    latencies_ms: List[float] = field(default_factory=list)
    successes: int = 0
    errors: Dict[int, int] = field(default_factory=dict)

    def record(self, status_code: int, elapsed_ms: float):
        self.latencies_ms.append(elapsed_ms)
        if 200 <= status_code < 300:
            self.successes += 1
        else:
            self.errors[status_code] = self.errors.get(status_code, 0) + 1

    def to_dict(self) -> dict:
        total = len(self.latencies_ms)
        if total == 0:
            return {"name": self.name, "requests": 0, "success_rate": 0, "p50": 0, "p95": 0, "p99": 0, "mean": 0,
                    "errors": self.errors}
        sorted_lat = sorted(self.latencies_ms)
        return {
            "name": self.name,
            "requests": total,
            "success_rate": round(100 * self.successes / total, 1),
            "p50": round(sorted_lat[int(0.50 * (total - 1))], 0),
            "p95": round(sorted_lat[int(0.95 * (total - 1))], 0),
            "p99": round(sorted_lat[int(0.99 * (total - 1))], 0),
            "mean": round(statistics.mean(self.latencies_ms), 0),
            "errors": self.errors
        }

async def run_load_test_internal(
    base_url: str,
    org_id: str,
    inventory_ids: List[int],
    paystack_secret: str,
    email: str,
    password: str,
    checkout_users: int = 10,
    webhook_bursts: int = 10,
    duration_s: int = 30,
    token: Optional[str] = None,
) -> dict:
    if token:
        auth_token = token
    else:
        async with httpx.AsyncClient() as client:
            login_resp = await client.post(
                f"{base_url}/auth/login",
                json={"email": email, "password": password},
                timeout=10.0
            )
            if login_resp.status_code not in (200, 204):
                raise ValueError(f"Login failed: {login_resp.text}")
            auth_token = login_resp.json().get("access_token")
            if not auth_token:
                raise ValueError("No access token in login response")

    auth_headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}

    def sign_paystack_payload(body: bytes, secret: str) -> str:
        return hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()

    checkout_stats = LoadTestStats("POST /pos/checkout")
    webhook_stats = LoadTestStats("POST /webhook/paystack")
    inventory_stats = LoadTestStats("GET /inventory/public-list")
    health_stats = LoadTestStats("GET /health")

    async def timed_request(client, method, url, stats, **kwargs):
        start = time.perf_counter()
        try:
            resp = await client.request(method, url, timeout=15.0, **kwargs)
            elapsed_ms = (time.perf_counter() - start) * 1000
            stats.record(resp.status_code, elapsed_ms)
            return resp
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            stats.record(599, elapsed_ms)
            return None

    async def simulate_checkout(client, stats):
        inventory_id = random.choice(inventory_ids)
        payload = {
            "items": [{"inventory_id": inventory_id, "quantity": 1}],
            "customer_name": f"LoadTest {uuid.uuid4().hex[:6]}",
            "customer_email": f"lt_{uuid.uuid4().hex[:6]}@example.com",
            "customer_phone": "08000000000",
            "payment_method": "paystack",
            "delivery_fee": 0,
            "handling_fee": 0,
        }
        headers = auth_headers.copy()
        headers["X-Load-Test"] = "true"
        await timed_request(client, "POST", f"{base_url}/pos/checkout", stats,
                            headers=headers, json=payload)

    async def simulate_webhook(client, stats):
        reference = str(uuid.uuid4())
        event_body = json.dumps({
            "event": "charge.success",
            "data": {
                "reference": reference,
                "amount": 500000,
                "status": "success",
                "customer": {"email": "loadtest@example.com"},
                "metadata": {"org_id": org_id}
            }
        }).encode()
        signature = sign_paystack_payload(event_body, paystack_secret)
        headers = {"Content-Type": "application/json", "x-paystack-signature": signature}
        await timed_request(client, "POST", f"{base_url}/webhook/paystack", stats,
                            headers=headers, content=event_body)

    async def simulate_read(client, url, stats):
        await timed_request(client, "GET", url, stats)

    async with httpx.AsyncClient() as client:
        stop_time = time.time() + duration_s

        async def checkout_worker():
            while time.time() < stop_time:
                await simulate_checkout(client, checkout_stats)
                await asyncio.sleep(random.uniform(0.2, 1.0))

        async def webhook_worker():
            while time.time() < stop_time:
                await simulate_webhook(client, webhook_stats)
                await asyncio.sleep(random.uniform(0.1, 0.5))

        async def read_worker():
            while time.time() < stop_time:
                await simulate_read(client, f"{base_url}/inventory/public-list", inventory_stats)
                await simulate_read(client, f"{base_url}/health", health_stats)
                await asyncio.sleep(0.5)

        tasks = (
            [asyncio.create_task(checkout_worker()) for _ in range(checkout_users)]
            + [asyncio.create_task(webhook_worker()) for _ in range(webhook_bursts)]
            + [asyncio.create_task(read_worker()) for _ in range(5)]
        )
        await asyncio.gather(*tasks)

    return {
        "checkout": checkout_stats.to_dict(),
        "webhook": webhook_stats.to_dict(),
        "inventory": inventory_stats.to_dict(),
        "health": health_stats.to_dict(),
        "config": {
            "checkout_users": checkout_users,
            "webhook_bursts": webhook_bursts,
            "duration_seconds": duration_s,
            "base_url": base_url,
            "org_id": org_id,
            "inventory_ids": inventory_ids
        }
    }


class ReconcileStockRequest(BaseModel):
    heal: bool = Field(False, description="If true, apply corrections. If false, report only.")
    limit: int = Field(500, ge=1, le=5000, description="Max drifted items per org.")
    stale_org_ids: Optional[List[str]] = Field(None, description="Optional: restrict to specific orgs.")


@app.post("/admin/reconcile-stock")
async def reconcile_stock(
    request: Request,
    req: ReconcileStockRequest,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    """
    Compare inventory.current_qty vs SUM(location_stocks.quantity) per item,
    report drift, and (optionally) heal it.
    """
    if x_admin_key != ADMIN_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    # Admin client: fresh service-role client per call. Every operation
    # here iterates the whole platform — listing orgs, calling drift
    # audits, healing rows — so RLS must not scope any of it to the
    # caller's membership. Under the polluted singleton, this endpoint
    # would only see orgs visible to the last-logged-in user.
    client = get_admin_supabase()

    if req.stale_org_ids:
        org_ids = list(req.stale_org_ids)
    else:
        orgs_resp = await run_sync_db_call(
            client.table("organisations").select("id").execute
        )
        org_ids = [row["id"] for row in (orgs_resp.data or [])]

    summary = {
        "orgs_scanned": 0,
        "items_drifted": 0,
        "units_drifted": 0,
        "items_healed": 0,
        "heal_failures": 0,
    }
    drifts: List[Dict] = []

    for oid in org_ids:
        summary["orgs_scanned"] += 1

        try:
            audit = await run_sync_db_call(
                client.rpc("audit_stock_drift", {"p_org_id": oid}).execute
            )
        except Exception as e:
            logger.error(f"audit_stock_drift({oid}) failed: {e}")
            continue

        rows = audit.data or []
        if not rows:
            continue

        default_location_id = await get_default_location(oid)

        for row in rows[: req.limit]:
            drift = int(row["drift"])
            entry = {
                "org_id":         oid,
                "inventory_id":   row["inventory_id"],
                "item_code":      row.get("item_code"),
                "description":    row.get("description"),
                "current_qty":    int(row["current_qty"]),
                "location_total": int(row["location_total"]),
                "drift":          drift,
                "healed":         False,
            }

            summary["items_drifted"] += 1
            summary["units_drifted"] += abs(drift)

            if req.heal:
                if not default_location_id:
                    entry["heal_error"] = "no default location for org"
                    summary["heal_failures"] += 1
                else:
                    try:
                        heal_resp = await run_sync_db_call(
                            client.rpc("heal_stock_drift", {
                                "p_org_id":              oid,
                                "p_inventory_id":        row["inventory_id"],
                                "p_default_location_id": default_location_id,
                            }).execute
                        )
                        healed = bool((heal_resp.data or {}).get("healed"))
                        entry["healed"] = healed
                        if healed:
                            summary["items_healed"] += 1
                    except Exception as e:
                        entry["heal_error"] = str(e)
                        summary["heal_failures"] += 1
                        logger.error(
                            f"heal_stock_drift(org={oid}, inv={row['inventory_id']}) failed: {e}"
                        )

            drifts.append(entry)

    sample_size = 200
    return {
        "dry_run": not req.heal,
        "summary": summary,
        "sample_drifts": drifts[:sample_size],
        "total_drifts_returned": len(drifts),
    }




@app.get("/admin/load-test")
async def admin_load_test(
    request: Request,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
    checkout_users: int = Query(10, ge=1, le=50),
    webhook_bursts: int = Query(10, ge=1, le=50),
    duration: int = Query(30, ge=5, le=120),
    email: Optional[str] = Query(None),
    password: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
):
    if x_admin_key != ADMIN_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    base_url = PRODUCTION_HOST or f"https://{request.headers.get('host')}"
    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    test_email = email or "demo@kevsdigital.com"
    test_password = password or "KevsDemo2026!"

    inventory_ids = [15377, 15378, 15379, 15380, 15381]

    paystack_secret = PAYSTACK_SECRET_KEY or "sk_test_33322c2ce90f9a69d3e887ee5c96336638952c8a"

    YOUR_ORG_ID = "7204f2d6-4b2b-4efc-a4b4-c77d6dcc5ae2"

    try:
        results = await run_load_test_internal(
            base_url=base_url,
            org_id=YOUR_ORG_ID,
            inventory_ids=inventory_ids,
            paystack_secret=paystack_secret,
            email=test_email,
            password=test_password,
            checkout_users=checkout_users,
            webhook_bursts=webhook_bursts,
            duration_s=duration,
            token=token
        )
        return results
    except Exception as e:
        logger.error(f"Load test failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ===================== TEMP DEBUG =====================
@app.get("/debug/current-db-role")
async def debug_current_db_role(request: Request):
    await rate_limit(get_client_ip(request))
    client = get_supabase()

    # What does Postgres see as the current role?
    try:
        rpc = await run_sync_db_call(
            client.rpc("exec_sql", {
                "query": (
                    "SELECT current_user AS pg_role, "
                    "current_setting('request.jwt.claim.role', true) AS jwt_role, "
                    "session_user AS session_role;"
                )
            }).execute
        )
        whoami = rpc.data
    except Exception as e:
        whoami = f"error: {e}"

    # Is there a stored user session on the cached client?
    session_present = False
    session_user = None
    try:
        s = client.auth.get_session()
        if s is not None:
            session_present = True
            session_user = getattr(s, "user", None)
            session_user = getattr(session_user, "email", None) if session_user else None
    except Exception:
        pass

    return {
        "pg_role": whoami,
        "session_present": session_present,
        "session_user_email": session_user,
    }


# ===================== HR ENDPOINTS =====================
@hr_router.get("/departments")
async def list_departments(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("hr_departments")
        .select("*")
        .eq("org_id", org_id)
        .order("name")
        .execute
    )
    return {"departments": result.data}

@hr_router.post("/departments")
async def create_department(
    request: Request,
    dept: DepartmentCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    data = dept.dict()
    data["org_id"] = org_id
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(client.table("hr_departments").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create department")
    return result.data[0]

@hr_router.put("/departments/{dept_id}")
async def update_department(
    request: Request,
    dept_id: int,
    dept: DepartmentUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    existing = await run_sync_db_call(
        client.table("hr_departments")
        .select("id")
        .eq("id", dept_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Department not found")
    update_data = {k: v for k, v in dept.dict().items() if v is not None}
    result = await run_sync_db_call(
        client.table("hr_departments")
        .update(update_data)
        .eq("id", dept_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update department")
    return result.data[0]

@hr_router.delete("/departments/{dept_id}")
async def delete_department(
    request: Request,
    dept_id: int,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    emp_check = await run_sync_db_call(
        client.table("hr_employees")
        .select("id")
        .eq("department_id", dept_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute
    )
    if emp_check.data:
        raise HTTPException(status_code=400, detail="Cannot delete department with employees assigned")
    result = await run_sync_db_call(
        client.table("hr_departments")
        .delete()
        .eq("id", dept_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Department not found")
    return {"message": "Department deleted"}

@hr_router.get("/employees")
async def list_employees(
    request: Request,
    department_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    query = client.table("hr_employees").select("*").eq("org_id", org_id)
    if department_id:
        query = query.eq("department_id", department_id)
    if status:
        query = query.eq("status", status)
    result = await run_sync_db_call(query.order("last_name").range(offset, offset + limit - 1).execute)
    return {"employees": result.data, "total": len(result.data) if result.data else 0}

@hr_router.post("/employees")
async def create_employee(
    request: Request,
    emp: EmployeeCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    if emp.user_id:
        member_check = await run_sync_db_call(
            client.table("org_members")
            .select("user_id")
            .eq("user_id", emp.user_id)
            .eq("org_id", org_id)
            .maybe_single()
            .execute
        )
        if not member_check.data:
            raise HTTPException(status_code=400, detail="User is not a member of this organisation")
    email_check = await run_sync_db_call(
        client.table("hr_employees")
        .select("id")
        .eq("email", emp.email)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if email_check.data:
        raise HTTPException(status_code=400, detail="Employee with this email already exists")

    data = emp.dict()
    data["org_id"] = org_id
    data["branch_id"] = await resolve_branch_for_write(org_id)
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(client.table("hr_employees").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create employee")
    return result.data[0]

@hr_router.get("/employees/{employee_id}")
async def get_employee(
    request: Request,
    employee_id: int,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "finance", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp or emp["id"] != employee_id:
            raise HTTPException(status_code=403, detail="Not authorised to view this employee")
    result = await run_sync_db_call(
        client.table("hr_employees")
        .select("*")
        .eq("id", employee_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Employee not found")
    return result.data[0]

@hr_router.put("/employees/{employee_id}")
async def update_employee(
    request: Request,
    employee_id: int,
    emp: EmployeeUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    existing = await get_employee_by_id(employee_id, org_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Employee not found")
    update_data = {k: v for k, v in emp.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(
        client.table("hr_employees")
        .update(update_data)
        .eq("id", employee_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update employee")
    return result.data[0]

@hr_router.delete("/employees/{employee_id}")
async def delete_employee(
    request: Request,
    employee_id: int,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    existing = await get_employee_by_id(employee_id, org_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Employee not found")
    result = await run_sync_db_call(
        client.table("hr_employees")
        .delete()
        .eq("id", employee_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to delete employee")
    return {"message": "Employee deleted"}

@hr_router.get("/me")
async def get_my_employee_profile(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["employee"]))
):
    user_id, org_id, _ = user_data
    emp = await get_employee_by_user_id(user_id, org_id)
    if not emp:
        raise HTTPException(status_code=404, detail="No employee profile found for this user")
    return emp

@hr_router.post("/attendance/clock-in")
async def clock_in(
    request: Request,
    clock: AttendanceClockIn,
    user_data: Tuple[str, str, str] = Depends(require_role(["employee"]))
):
    user_id, org_id, _ = user_data
    emp = await get_employee_by_user_id(user_id, org_id)
    if not emp or emp["id"] != clock.employee_id:
        raise HTTPException(status_code=403, detail="Not authorised to clock in for this employee")
    client = get_supabase()
    today = date.today().isoformat()
    existing = await run_sync_db_call(
        client.table("hr_attendance")
        .select("id")
        .eq("employee_id", clock.employee_id)
        .eq("date", today)
        .is_("clock_out", "null")
        .maybe_single()
        .execute
    )
    if existing.data:
        raise HTTPException(status_code=400, detail="Already clocked in today; please clock out first")
    data = {
        "employee_id": clock.employee_id,
        "branch_id": (emp.get("branch_id") if emp else None) or await resolve_branch_for_write(org_id),
        "date": today,
        "clock_in": clock.clock_in.isoformat(),
        "status": "present"
    }
    result = await run_sync_db_call(client.table("hr_attendance").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to clock in")
    return {"message": "Clocked in", "attendance": result.data[0]}

@hr_router.post("/attendance/clock-out")
async def clock_out(
    request: Request,
    clock: AttendanceClockOut,
    user_data: Tuple[str, str, str] = Depends(require_role(["employee"]))
):
    user_id, org_id, _ = user_data
    emp = await get_employee_by_user_id(user_id, org_id)
    if not emp or emp["id"] != clock.employee_id:
        raise HTTPException(status_code=403, detail="Not authorised")
    client = get_supabase()
    today = date.today().isoformat()
    record = await run_sync_db_call(
        client.table("hr_attendance")
        .select("id")
        .eq("employee_id", clock.employee_id)
        .eq("date", today)
        .is_("clock_out", "null")
        .maybe_single()
        .execute
    )
    if not record.data:
        raise HTTPException(status_code=400, detail="No open clock-in found for today")
    update_data = {
        "clock_out": clock.clock_out.isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    result = await run_sync_db_call(
        client.table("hr_attendance")
        .update(update_data)
        .eq("id", record.data["id"])
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to clock out")
    return {"message": "Clocked out", "attendance": result.data[0]}

@hr_router.get("/attendance")
async def get_attendance(
    request: Request,
    employee_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    target_employee_id = employee_id
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp:
            raise HTTPException(status_code=404, detail="No employee profile")
        if employee_id and employee_id != emp["id"]:
            raise HTTPException(status_code=403, detail="Can only view own attendance")
        target_employee_id = emp["id"]
    query = client.table("hr_attendance").select("*").eq("org_id", org_id)
    if target_employee_id:
        query = query.eq("employee_id", target_employee_id)
    if start_date:
        query = query.gte("date", start_date.isoformat())
    if end_date:
        query = query.lte("date", end_date.isoformat())
    result = await run_sync_db_call(query.order("date", desc=True).range(offset, offset + limit - 1).execute)
    return {"attendance": result.data, "total": len(result.data) if result.data else 0}

@hr_router.post("/leave-requests")
async def create_leave_request(
    request: Request,
    leave: LeaveRequestCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["employee"]))
):
    user_id, org_id, _ = user_data
    emp = await get_employee_by_user_id(user_id, org_id)
    if not emp or emp["id"] != leave.employee_id:
        raise HTTPException(status_code=403, detail="Not authorised")
    if leave.start_date > leave.end_date:
        raise HTTPException(status_code=400, detail="Start date must be before end date")
    client = get_supabase()
    data = leave.dict()
    data["org_id"] = org_id
    data["branch_id"] = (emp.get("branch_id") if emp else None) or await resolve_branch_for_write(org_id)
    data["status"] = "pending"
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(client.table("hr_leave_requests").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create leave request")
    return result.data[0]

@hr_router.get("/leave-requests")
async def list_leave_requests(
    request: Request,
    employee_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    target_employee_id = employee_id
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp:
            raise HTTPException(status_code=404, detail="No employee profile")
        if employee_id and employee_id != emp["id"]:
            raise HTTPException(status_code=403, detail="Can only view own leave requests")
        target_employee_id = emp["id"]
    query = client.table("hr_leave_requests").select("*").eq("org_id", org_id)
    if target_employee_id:
        query = query.eq("employee_id", target_employee_id)
    if status:
        query = query.eq("status", status)
    result = await run_sync_db_call(query.order("created_at", desc=True).range(offset, offset + limit - 1).execute)
    return {"requests": result.data, "total": len(result.data) if result.data else 0}

@hr_router.put("/leave-requests/{request_id}")
async def update_leave_request(
    request: Request,
    request_id: int,
    update: LeaveRequestUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    req = await run_sync_db_call(
        client.table("hr_leave_requests")
        .select("*")
        .eq("id", request_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not req.data:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if req.data["status"] != "pending":
        raise HTTPException(status_code=400, detail="Request already processed")
    update_data = {
        "status": update.status,
        "approved_by": update.approved_by,
        "notes": update.notes,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    result = await run_sync_db_call(
        client.table("hr_leave_requests")
        .update(update_data)
        .eq("id", request_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update leave request")
    return result.data[0]

@hr_router.get("/leave-balances")
async def get_leave_balances(
    request: Request,
    employee_id: Optional[int] = None,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    target_employee_id = employee_id
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp:
            raise HTTPException(status_code=404, detail="No employee profile")
        if employee_id and employee_id != emp["id"]:
            raise HTTPException(status_code=403, detail="Can only view own balances")
        target_employee_id = emp["id"]
    query = client.table("hr_leave_balances").select("*").eq("org_id", org_id)
    if target_employee_id:
        query = query.eq("employee_id", target_employee_id)
    result = await run_sync_db_call(query.execute)
    return {"balances": result.data}

@hr_router.post("/payroll/generate")
async def generate_payroll(
    request: Request,
    payload: PayrollGenerate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    employees = await run_sync_db_call(
        client.table("hr_employees")
        .select("id, salary")
        .eq("org_id", org_id)
        .eq("status", "active")
        .execute
    )
    if not employees.data:
        raise HTTPException(status_code=400, detail="No active employees")
    payrolls = []
    month = payload.month
    year = payload.year
    for emp in employees.data:
        existing = await run_sync_db_call(
            client.table("hr_payroll")
            .select("id")
            .eq("employee_id", emp["id"])
            .eq("month", month)
            .eq("year", year)
            .eq("org_id", org_id)
            .maybe_single()
            .execute
        )
        if existing.data:
            continue
        branch_id_for_payroll = await resolve_branch_for_write(org_id)
        payroll_data = {
            "org_id": org_id,
            "branch_id": branch_id_for_payroll,
            "employee_id": emp["id"],
            "month": month,
            "year": year,
            "base_salary": emp["salary"],
            "allowances": 0.0,
            "deductions": 0.0,
            "net_pay": emp["salary"],
            "status": "draft",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        payrolls.append(payroll_data)
    if payrolls:
        result = await run_sync_db_call(client.table("hr_payroll").insert(payrolls).execute)
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to generate payroll")
    return {"message": f"Generated payroll for {len(payrolls)} employees", "payrolls": result.data if payrolls else []}

@hr_router.get("/payroll")
async def list_payroll(
    request: Request,
    employee_id: Optional[int] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "finance", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    target_employee_id = employee_id
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp:
            raise HTTPException(status_code=404, detail="No employee profile")
        if employee_id and employee_id != emp["id"]:
            raise HTTPException(status_code=403, detail="Can only view own payroll")
        target_employee_id = emp["id"]
    query = client.table("hr_payroll").select("*").eq("org_id", org_id)
    if target_employee_id:
        query = query.eq("employee_id", target_employee_id)
    if month:
        query = query.eq("month", month)
    if year:
        query = query.eq("year", year)
    result = await run_sync_db_call(query.order("year", desc=True).order("month", desc=True).range(offset, offset + limit - 1).execute)
    return {"payroll": result.data, "total": len(result.data) if result.data else 0}

# ===================== INCLUDE HR ROUTER =====================
app.include_router(hr_router)


# --- CENTRALIZED LOG SHIPPING (Optional) AXIOM ---
import requests
import json

class AxiomHandler(logging.Handler):
    def __init__(self, dataset: str, token: str):
        super().__init__()
        self.dataset = dataset
        self.token = token
        self.url = f"https://api.axiom.co/v1/datasets/{dataset}/ingest"

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            payload = json.loads(msg)
            requests.post(self.url, json=payload, headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }, timeout=1.0)
        except Exception:
            pass

if os.environ.get("AXIOM_TOKEN"):
    axiom_handler = AxiomHandler(
        dataset=os.environ.get("AXIOM_DATASET", "fastapi-logs"),
        token=os.environ.get("AXIOM_TOKEN")
    )
    axiom_handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(axiom_handler)
    logger.info("axiom_logging_enabled")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
