from fastapi import FastAPI, Header, HTTPException, Request, Response, Depends, File, UploadFile, Query, BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Tuple, Literal
from datetime import datetime, date, timedelta, timezone
from enum import Enum
import csv
import io
import os
import logging
import httpx
import uuid
import time
import traceback
import re
import json
import hashlib
import hmac
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

from sentence_transformers import SentenceTransformer
print("Preloading embedding model...")
SentenceTransformer('all-MiniLM-L6-v2', cache_folder='/root/.cache/huggingface')
print("Preload done.")

try:
    from sentence_transformers import SentenceTransformer, util
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError as e:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    print(f"⚠️ sentence-transformers not available: {e}")

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

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@kevsdigital.com")
LOGISTICS_EMAIL = os.environ.get("LOGISTICS_EMAIL", "")

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
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Supabase rate limiter
# ------------------------------------------------------------------
async def rate_limit(client_id: str, org_id: Optional[str] = None):
    if not RATE_LIMIT_ENABLED:
        return
    supabase = get_supabase()
    now = datetime.utcnow()
    window_start = datetime.utcfromtimestamp(
        (now.timestamp() // RATE_LIMIT_WINDOW) * RATE_LIMIT_WINDOW
    )
    try:
        query = supabase.table("rate_limits").select("request_count").eq("client_id", client_id).eq("window_start", window_start.isoformat())
        if org_id is not None:
            query = query.eq("org_id", org_id)
        existing = query.execute()
        
        if existing.data and len(existing.data) > 0:
            new_count = existing.data[0]["request_count"] + 1
            update_query = supabase.table("rate_limits").update({"request_count": new_count}).eq("client_id", client_id).eq("window_start", window_start.isoformat())
            if org_id is not None:
                update_query = update_query.eq("org_id", org_id)
            update_query.execute()
        else:
            insert_data = {
                "client_id": client_id,
                "window_start": window_start.isoformat(),
                "request_count": 1
            }
            if org_id is not None:
                insert_data["org_id"] = org_id
            supabase.table("rate_limits").insert(insert_data).execute()
            new_count = 1
        
        if new_count > RATE_LIMIT_REQUESTS:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rate limit error: {e}")

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# ------------------------------------------------------------------
# Email helper (SendGrid)
# ------------------------------------------------------------------
async def send_sendgrid_email(to_email: str, subject: str, html_content: str):
    if not SENDGRID_API_KEY or not FROM_EMAIL:
        logger.warning(f"SendGrid not configured. Would send email to {to_email}: {subject}")
        return
    url = "https://api.sendgrid.com/v3/mail/send"
    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": FROM_EMAIL},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_content}]
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=data, headers=headers)
            if resp.status_code >= 400:
                logger.error(f"SendGrid error {resp.status_code}: {resp.text}")
            else:
                logger.info(f"Email sent to {to_email}: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

async def send_status_update_email(sale_id: str, old_status: str, new_status: str, tracking_info: dict = None):
    client = get_supabase()
    sale = client.table("sales").select("*, sale_items(*)").eq("id", sale_id).maybe_single().execute()
    if not sale.data:
        logger.error(f"Sale {sale_id} not found for status email")
        return
    sale_data = sale.data
    org = client.table("organisations").select("org_name, logistics_email").eq("id", sale_data["org_id"]).maybe_single().execute()
    org_name = org.data["org_name"] if org.data else "Our Store"
    logistics_email = org.data.get("logistics_email") if org.data else LOGISTICS_EMAIL
    
    customer_email = sale_data.get("customer_email")
    if not customer_email:
        logger.warning(f"No customer email for order {sale_id}")
        return
    
    tracking_link = f"{PRODUCTION_HOST}/track-order?receipt_number={sale_data['receipt_number']}&email={customer_email}"
    
    if new_status == "shipped":
        subject = f"Your order #{sale_data['receipt_number']} is on the way!"
        customer_html = f"""
        <h2>Order Dispatched</h2>
        <p>Good news! Your order <strong>{sale_data['receipt_number']}</strong> has been shipped.</p>
        <p><strong>Carrier:</strong> {tracking_info.get('carrier', sale_data.get('shipping_carrier', 'Not specified')) if tracking_info else sale_data.get('shipping_carrier', 'Not specified')}</p>
        <p><strong>Tracking number:</strong> {tracking_info.get('tracking_number', sale_data.get('tracking_number', 'N/A')) if tracking_info else sale_data.get('tracking_number', 'N/A')}</p>
        <p><strong>Estimated delivery:</strong> {tracking_info.get('estimated_delivery', sale_data.get('estimated_delivery', '2-5 business days')) if tracking_info else sale_data.get('estimated_delivery', '2-5 business days')}</p>
        <p>Track your order: <a href="{tracking_link}">Click here</a></p>
        """
        internal_html = f"""
        <h2>Order Dispatched – Action Required</h2>
        <p>Order <strong>{sale_data['receipt_number']}</strong> has been marked as shipped.</p>
        <p>Carrier: {tracking_info.get('carrier', sale_data.get('shipping_carrier', 'N/A')) if tracking_info else sale_data.get('shipping_carrier', 'N/A')}</p>
        <p>Tracking: {tracking_info.get('tracking_number', sale_data.get('tracking_number', 'N/A')) if tracking_info else sale_data.get('tracking_number', 'N/A')}</p>
        <p>Ensure delivery confirmation is received.</p>
        """
    elif new_status == "delivered":
        subject = f"Your order #{sale_data['receipt_number']} has been delivered"
        customer_html = f"""
        <h2>Order Delivered</h2>
        <p>Your order <strong>{sale_data['receipt_number']}</strong> has been delivered.</p>
        <p>Thank you for shopping with {org_name}!</p>
        <p>If you have any issues, please contact support.</p>
        """
        internal_html = f"""
        <h2>Order Delivered – Complete</h2>
        <p>Order <strong>{sale_data['receipt_number']}</strong> has been marked as delivered.</p>
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
# Embedder & semantic firewall
# ------------------------------------------------------------------
_embedder = None
_guardrail_embedder = None
_approved_topics = [
    "product availability and inventory",
    "order status and tracking",
    "return and refund policy",
    "store location and business hours",
    "loyalty points and membership",
    "create a support ticket",
    "talk to a human agent"
]
_approved_embeddings = None

async def load_embedders():
    global _embedder, _guardrail_embedder, _approved_embeddings
    if not SENTENCE_TRANSFORMERS_AVAILABLE:
        logger.warning("sentence-transformers not available – embedding features disabled")
        _embedder = False
        _guardrail_embedder = False
        return
    try:
        _embedder = SentenceTransformer('all-MiniLM-L6-v2', cache_folder='/root/.cache/huggingface')
        _guardrail_embedder = _embedder
        _approved_embeddings = _embedder.encode(_approved_topics, convert_to_tensor=True)
        logger.info("Embedders loaded at startup")
    except Exception as e:
        logger.error(f"Failed to load embedder: {e}", exc_info=True)
        _embedder = False
        _guardrail_embedder = False

def get_embedder():
    return _embedder if _embedder is not False else None

def semantic_firewall(user_message: str, threshold: float = 0.65) -> bool:
    if _guardrail_embedder is False or _approved_embeddings is None:
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
# LLM caller (unified)
# ------------------------------------------------------------------
async def call_llm(prompt: str) -> str:
    if GROQ_API_KEY:
        try:
            groq = Groq(api_key=GROQ_API_KEY)
            resp = groq.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
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
# FastAPI app
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

# ------------------------------------------------------------------
# Database migrations (cost_price_naira, delivery_fee, handling_fee, org delivery columns, role column)
# ------------------------------------------------------------------
async def ensure_cost_price_column():
    supabase = get_supabase()
    try:
        test = supabase.table("inventory").select("cost_price_naira").limit(1).execute()
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
                import httpx
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
                    if resp.status_code != 200:
                        logger.error(f"Failed to run migration: {resp.text}")
                    else:
                        logger.info("Successfully added cost_price_naira column and set default values.")
            except Exception as migration_err:
                logger.error(f"Migration error: {migration_err}. Please run SQL manually: {sql}")
        else:
            logger.error(f"Unexpected error checking column: {e}")

async def ensure_delivery_fee_columns():
    """Add delivery_fee and handling_fee columns to sales table if missing."""
    supabase = get_supabase()
    try:
        test = supabase.table("sales").select("delivery_fee").limit(1).execute()
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
                import httpx
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
                    if resp.status_code != 200:
                        logger.error(f"Failed to add delivery_fee columns: {resp.text}")
                    else:
                        logger.info("Successfully added delivery_fee and handling_fee columns.")
            except Exception as migration_err:
                logger.error(f"Delivery fee column migration error: {migration_err}. Please run SQL manually: {sql}")
        else:
            logger.error(f"Unexpected error checking delivery_fee column: {e}")

async def ensure_org_delivery_columns():
    """Add delivery configuration columns to organisations table if missing."""
    supabase = get_supabase()
    try:
        test = supabase.table("organisations").select("delivery_base_fee").limit(1).execute()
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
                import httpx
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
                    if resp.status_code != 200:
                        logger.error(f"Failed to add organisation delivery columns: {resp.text}")
                    else:
                        logger.info("Successfully added delivery columns to organisations table.")
            except Exception as migration_err:
                logger.error(f"Organisation delivery columns migration error: {migration_err}. Please run SQL manually: {sql}")
        else:
            logger.error(f"Unexpected error checking organisation columns: {e}")

async def ensure_role_column():
    """Add role column to org_members if missing."""
    supabase = get_supabase()
    try:
        test = supabase.table("org_members").select("role").limit(1).execute()
        logger.info("role column already exists in org_members.")
    except Exception as e:
        if 'column "role" does not exist' in str(e):
            logger.warning("role column missing in org_members. Adding it now...")
            try:
                sql = """
                ALTER TABLE public.org_members 
                ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'customer';
                """
                import httpx
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
                    if resp.status_code != 200:
                        logger.error(f"Failed to add role column: {resp.text}")
                    else:
                        logger.info("Successfully added role column to org_members.")
                        # Optionally set existing owner role for the first member of each org
                        # This is a one-time fix (can be done manually if needed)
            except Exception as migration_err:
                logger.error(f"Role column migration error: {migration_err}. Please run SQL manually: {sql}")
        else:
            logger.error(f"Unexpected error checking role column: {e}")

@app.on_event("startup")
async def startup_event():
    await load_embedders()
    await ensure_cost_price_column()
    await ensure_delivery_fee_columns()
    await ensure_org_delivery_columns()
    await ensure_role_column()
    logger.info("Startup complete")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_detail = traceback.format_exc()
    logger.error(f"Unhandled exception: {error_detail}")
    return JSONResponse(status_code=500, content={"detail": str(exc), "traceback": error_detail})

@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    start_time = time.time()
    logger.info(f"🔵 REQ {request_id} | {request.method} {request.url.path}")
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.info(f"🟢 RESP {request_id} | {response.status_code} | {process_time:.3f}s")
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as e:
        logger.error(f"🔴 REQ {request_id} | {type(e).__name__}: {str(e)}", exc_info=True)
        raise

# ------------------------------------------------------------------
# Supabase client (service role)
# ------------------------------------------------------------------
supabase_client: Optional[Client] = None
last_client_check = None

def get_supabase():
    global supabase_client, last_client_check
    now = datetime.now()
    if supabase_client is None or (last_client_check and (now - last_client_check).seconds > 3600):
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            if SUPABASE_ANON_KEY:
                logger.warning("SUPABASE_SERVICE_ROLE_KEY missing – falling back to anon key (RLS may block access)")
                supabase_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
            else:
                raise RuntimeError("No Supabase credentials (neither service role nor anon key)")
        else:
            supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
            logger.info("Supabase client created with SERVICE ROLE KEY (RLS bypassed)")
        last_client_check = now
    return supabase_client

# ------------------------------------------------------------------
# Helper functions (invite code, auth, conversation, RAG, loyalty, tickets, roles)
# ------------------------------------------------------------------
async def generate_invite_code() -> str:
    client = get_supabase()
    result = client.table("organisations").select("invite_code").execute()
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

async def get_current_user(authorization: str = Header(None)) -> Optional[Tuple[str, str]]:
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("get_current_user: No Bearer token")
        return None
    token = authorization.split(" ")[1]
    try:
        client = get_supabase()
        user = client.auth.get_user(token)
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

async def get_current_org(authorization: str = Header(None)) -> Tuple[str, str]:
    user_info = await get_current_user(authorization)
    if not user_info:
        logger.error("get_current_org: No user info")
        raise HTTPException(status_code=401, detail="Not authenticated")
    token_user_id, email = user_info

    client = get_supabase()
    resolved_user_id = token_user_id
    org_id = None

    try:
        logger.info(f"🔍 Query org_members with user_id={token_user_id}")
        res = client.table("org_members").select("org_id").eq("user_id", token_user_id).execute()
        logger.info(f"🔍 org_members response (direct): {res.data}")
        org_rows = getattr(res, "data", []) or []
        if org_rows:
            org_id = org_rows[0]["org_id"]
            logger.info(f"✅ Org found via token user_id: {token_user_id}, org_id={org_id}")
            return token_user_id, org_id
        else:
            logger.warning(f"Direct lookup returned no rows for user_id={token_user_id}")
    except Exception as e:
        logger.warning(f"Direct lookup failed: {e}", exc_info=True)

    if email:
        try:
            logger.info(f"🔍 Looking up profile by email={email}")
            profile_res = client.table("profiles").select("id").eq("email", email).maybe_single().execute()
            logger.info(f"Profile lookup response: {profile_res.data}")
            if profile_res and profile_res.data:
                resolved_user_id = profile_res.data["id"]
                logger.info(f"📧 Resolved user_id {resolved_user_id} from email {email}")
                res2 = client.table("org_members").select("org_id").eq("user_id", resolved_user_id).execute()
                logger.info(f"🔍 org_members response (email fallback): {res2.data}")
                org_rows2 = getattr(res2, "data", []) or []
                if org_rows2:
                    org_id = org_rows2[0]["org_id"]
                    logger.info(f"✅ Org found via email-resolved user_id: {resolved_user_id}, org_id={org_id}")
                    return resolved_user_id, org_id
                else:
                    logger.warning(f"Email fallback: no org_members row for resolved_user_id={resolved_user_id}")
            else:
                logger.warning(f"Email fallback: no profile found for email={email}")
        except Exception as e:
            logger.warning(f"Email fallback lookup failed: {e}", exc_info=True)
    else:
        logger.warning("No email available from token")

    logger.error(f"❌ No org for token_user_id={token_user_id}, email={email}, resolved_id={resolved_user_id}")
    raise HTTPException(
        status_code=403,
        detail="Workspace Access Denied. Your credentials match, but you have not been assigned to an organization profile yet."
    )

async def get_current_user_with_role(authorization: str = Header(None)) -> Tuple[str, str, str]:
    """Returns (user_id, org_id, role). Raises 401/403 if not authenticated or no org."""
    user_id, org_id = await get_current_org(authorization)
    client = get_supabase()
    member = client.table("org_members").select("role").eq("user_id", user_id).eq("org_id", org_id).maybe_single().execute()
    role = member.data["role"] if member and member.data else "customer"
    return user_id, org_id, role

def require_role(allowed_roles: List[str]):
    """Dependency factory for role-based access control."""
    async def role_checker(user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
        _, _, role = user_data
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Access denied. Required role: {allowed_roles}")
        return user_data
    return role_checker

async def get_user_and_org_names(user_id: str, org_id: str) -> Tuple[str, str]:
    client = get_supabase()
    profile_res = client.table("profiles").select("first_name").eq("id", user_id).maybe_single().execute()
    first_name = profile_res.data["first_name"] if profile_res and profile_res.data else "there"
    org_res = client.table("organisations").select("org_name").eq("id", org_id).maybe_single().execute()
    org_name = org_res.data["org_name"] if org_res and org_res.data else "our organization"
    return first_name, org_name

async def get_full_conversation_history(user_id: str, session_id: str, limit: int = 20) -> List[Dict]:
    client = get_supabase()
    if not client:
        return []
    try:
        result = client.table("chat_messages").select("message, response, created_at") \
            .eq("user_id", user_id) \
            .eq("session_id", session_id) \
            .order("created_at", desc=False).limit(limit).execute()
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
            result = client.rpc(
                'match_knowledge_documents',
                {
                    'query_embedding': query_embedding,
                    'match_threshold': threshold,
                    'match_count': top_k * 2
                }
            ).execute()
            if result.data:
                filtered = [row for row in result.data if row.get('org_id') == org_id]
                return filtered[:top_k]
        except Exception as e:
            logger.warning(f"Vector search error: {e}, fallback to keyword")
    try:
        all_rows = client.table("general_knowledge") \
            .select("category, title, content, keywords") \
            .eq("org_id", org_id) \
            .execute()
        if not all_rows.data:
            return []
        q_lower = query.lower()
        scored = []
        for row in all_rows.data:
            content = row.get('content', '')
            keywords = row.get('keywords', []) or []
            score = 0
            for kw in keywords:
                if kw and kw.lower() in q_lower:
                    score += 30
            for word in q_lower.split():
                if len(word) > 3 and word in content.lower():
                    score += 5
            if score > 0:
                scored.append({"content": content, "title": row.get('title', ''), "score": score})
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

async def get_loyalty_info_by_user_id(user_id: str) -> Optional[Dict]:
    client = get_supabase()
    if not client:
        return None
    try:
        result = client.table("profiles") \
            .select("first_name, current_points, tier, membership_id, phone") \
            .eq("id", user_id) \
            .maybe_single() \
            .execute()
        if result and result.data:
            return result.data
    except Exception as e:
        logger.error(f"Loyalty fetch error: {e}", exc_info=True)
    return None

async def create_support_ticket(user_id: str, org_id: str, subject: str, message: str, priority: str = "normal") -> Optional[str]:
    client = get_supabase()
    ticket = client.table("support_tickets").insert({
        "user_id": user_id,
        "org_id": org_id,
        "subject": subject,
        "priority": priority,
        "status": "open",
        "created_at": datetime.now().isoformat()
    }).execute()
    if not ticket.data:
        return None
    ticket_id = ticket.data[0]["id"]
    client.table("ticket_messages").insert({
        "ticket_id": ticket_id,
        "sender_type": "user",
        "sender_id": user_id,
        "message": message,
        "created_at": datetime.now().isoformat()
    }).execute()
    return str(ticket_id)

async def save_conversation(user_id: str, org_id: str, session_id: str, message: str, response: str, channel: str = "website"):
    client = get_supabase()
    if not client:
        return
    try:
        sess = client.table("chat_sessions").select("id").eq("id", session_id).maybe_single().execute()
        if not sess or not sess.data:
            new_sess = client.table("chat_sessions").insert({
                "id": session_id,
                "user_id": user_id,
                "org_id": org_id,
                "channel": channel,
                "started_at": datetime.now().isoformat()
            }).execute()
            if not new_sess.data:
                logger.error("Failed to create chat session")
                return
        
        client.table("chat_messages").insert({
            "session_id": session_id,
            "user_id": user_id,
            "org_id": org_id,
            "message": message,
            "response": None,
            "created_at": datetime.now().isoformat()
        }).execute()
        client.table("chat_messages").insert({
            "session_id": session_id,
            "user_id": user_id,
            "org_id": org_id,
            "message": None,
            "response": response,
            "created_at": datetime.now().isoformat()
        }).execute()
    except Exception as e:
        logger.error(f"Save conversation error: {e}", exc_info=True)

async def get_strategic_reply(
    user_message: str,
    user_id: str,
    org_id: str,
    session_id: str,
    channel: str = "website"
) -> Tuple[str, Optional[str]]:
    if not semantic_firewall(user_message):
        logger.info(f"Off-topic message blocked: {user_message[:50]}")
        return fallback_response(), None

    first_name, org_name = await get_user_and_org_names(user_id, org_id)
    loyalty_data = await get_loyalty_info_by_user_id(user_id)
    loyalty_text = f"Customer {first_name} has {loyalty_data.get('current_points',0)} points, tier {loyalty_data.get('tier','Standard')}" if loyalty_data else ""
    history = await get_full_conversation_history(user_id, session_id, limit=20)
    context = await get_relevant_context(org_id, user_message)

    history_text = ""
    if history:
        recent = history[-10:]
        history_text = "\n".join([f"{h['role']}: {h['content']}" for h in recent])

    system_prompt = f"""You are {org_name}'s AI assistant, Kevs Assistant.
You are speaking with {first_name}, a registered customer.
{loyalty_text}
Business knowledge (use if relevant):
{context if context else "(none)"}
Conversation history:
{history_text if history_text else "(start of conversation)"}
You MUST respond with a valid JSON object only, no extra text. The JSON must follow this schema:
{{
    "message": "Your friendly, helpful response to the user",
    "confidence": 0.95,
    "action": "reply" or "create_ticket" or "escalate",
    "metadata": {{ "ticket_subject": "only if action is create_ticket" }}
}}
Rules:
- If you are unsure or the question is outside your knowledge, set confidence < 0.6 and action = "escalate".
- If the user explicitly asks to create a ticket or talk to a human, set action = "create_ticket".
- Keep message under 800 characters.
- Do NOT hallucinate order numbers, phone numbers, or personal data.
- Be warm, concise, and helpful.
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
        ticket_id = await create_support_ticket(user_id, org_id, "LLM validation failure", f"User: {user_message}\nError: {e}")
        return escalation_response(), ticket_id

    if safe.action == "create_ticket":
        ticket_subject = safe.metadata.get("ticket_subject", f"Support request from {first_name}")
        ticket_id = await create_support_ticket(user_id, org_id, ticket_subject, f"User message: {user_message}\nAI context: {context}")
        return f"✅ I've created a support ticket (ID: {ticket_id[:8]}). Our team will reach out within 24 hours.", ticket_id
    elif safe.action == "escalate" or safe.confidence < 0.6:
        ticket_id = await create_support_ticket(user_id, org_id, "Low confidence query", f"User: {user_message}\nConfidence: {safe.confidence}")
        return escalation_response(), ticket_id
    else:
        final_message = safe.message.strip()
        if any(phrase in final_message.lower() for phrase in ["fake", "scam", "steal"]):
            final_message = "I cannot answer that. Please contact support for help."
        if len(final_message) > 800:
            final_message = final_message[:797] + "..."
        return final_message, None

# ------------------------------------------------------------------
# Auth endpoints (updated registration with role assignment)
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
    # Delivery & store location for new organisation
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
    
    org_id = None
    role = "customer"  # default role for invite code users
    
    if auth.invite_code and auth.invite_code.strip():
        org_result = client.table("organisations").select("id").eq("invite_code", auth.invite_code).maybe_single().execute()
        if not org_result or not org_result.data:
            raise HTTPException(status_code=400, detail="Invalid invite code")
        org_id = org_result.data["id"]
        # For invite code, role remains 'customer' (can be promoted later by owner)
    elif auth.org_name and auth.location and auth.niche:
        existing = client.table("organisations").select("id").eq("org_name", auth.org_name).maybe_single().execute()
        if existing and existing.data:
            raise HTTPException(status_code=400, detail="Organisation name already exists. Please use an invite code or different name.")
        
        # Geocode store address if provided (or manual lat/lng)
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
        new_org = client.table("organisations").insert({
            "org_name": auth.org_name,
            "location": auth.location,
            "niche": auth.niche,
            "budget": auth.budget or 0,
            "invite_code": invite_code,
            "created_at": datetime.now().isoformat(),
            "payment_gateway_config": {"provider": "paystack", "credentials": {}},
            "latitude": store_lat,
            "longitude": store_lng,
            "delivery_base_fee": auth.delivery_base_fee or 300,
            "delivery_per_km_rate": auth.delivery_per_km_rate or 80,
            "delivery_per_kg_rate": auth.delivery_per_kg_rate or 50,
            "handling_surcharge_fragile": 200,
            "handling_surcharge_bulky": 500,
            "handling_surcharge_hazardous": 1000
        }).execute()
        if not new_org.data:
            raise HTTPException(status_code=500, detail="Failed to create organisation")
        org_id = new_org.data[0]["id"]
        role = "owner"  # first user of a new organisation becomes owner
    else:
        raise HTTPException(
            status_code=400,
            detail="Either provide an invite_code OR provide org_name, location, niche, and store_address to create a new organisation."
        )
    
    try:
        resp = client.auth.sign_up({"email": auth.email, "password": auth.password})
        if not resp.user:
            raise HTTPException(status_code=400, detail="Registration failed")
        user_id = resp.user.id
        
        client.table("profiles").insert({
            "id": user_id,
            "email": auth.email,
            "first_name": auth.first_name,
            "last_name": auth.last_name,
            "phone": auth.phone,
            "membership_id": f"MEM-{user_id[:8]}",
            "status": "Active"
        }).execute()
        
        # Insert org_members with the determined role
        client.table("org_members").insert({
            "user_id": user_id,
            "org_id": org_id,
            "role": role,
            "joined_at": datetime.now().isoformat()
        }).execute()
        
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
        resp = get_supabase().auth.sign_in_with_password({"email": auth.email, "password": auth.password})
        if resp.session:
            return {
                "user_id": resp.user.id,
                "access_token": resp.session.access_token,
                "refresh_token": resp.session.refresh_token
            }
        raise HTTPException(status_code=401, detail="Invalid credentials")
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@app.post("/auth/refresh")
async def refresh_token(request: Request, req: RefreshRequest):
    await rate_limit(get_client_ip(request))
    try:
        resp = get_supabase().auth.refresh_session(req.refresh_token)
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
        raise HTTPException(status_code=401, detail="Invalid token format")
    token = authorization.split(" ")[1]
    try:
        get_supabase().auth.sign_out(token)
        return {"message": "Logged out"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/auth/me")
async def me(request: Request, authorization: str = Header(None)):
    await rate_limit(get_client_ip(request))
    user_data = await get_current_user_with_role(authorization)
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id, org_id, role = user_data
    return {"user_id": user_id, "org_id": org_id, "role": role}

# ------------------------------------------------------------------
# TEAM MANAGEMENT (ONBOARDING) – requires owner/admin role
# ------------------------------------------------------------------
class CreateStaffRequest(BaseModel):
    email: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    role: str = "customer"   # owner, admin, inventory_manager, sales_rep, finance, logistics, support, customer
    send_invite_email: bool = True

@app.get("/organisations/me/users")
async def list_org_members(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    
    result = client.table("org_members") \
        .select("user_id, role, joined_at, profiles(first_name, last_name, email, phone, status)") \
        .eq("org_id", org_id) \
        .execute()
    
    members = []
    for row in result.data:
        profile = row.get("profiles", {})
        members.append({
            "id": row["user_id"],
            "first_name": profile.get("first_name"),
            "last_name": profile.get("last_name"),
            "email": profile.get("email"),
            "phone": profile.get("phone"),
            "role": row["role"],
            "status": profile.get("status"),
            "joined_at": row["joined_at"]
        })
    return {"users": members}

@app.post("/organisations/me/users")
async def create_staff_member(
    request: Request,
    staff: CreateStaffRequest,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    
    # 1. Check if email already exists in profiles
    existing = client.table("profiles").select("id").eq("email", staff.email).maybe_single().execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # 2. Generate a random temporary password (12 chars)
    import secrets, string
    temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    
    # 3. Create Supabase auth user
    try:
        auth_resp = client.auth.admin.create_user({
            "email": staff.email,
            "password": temp_password,
            "email_confirm": True,
            "user_metadata": {
                "first_name": staff.first_name,
                "last_name": staff.last_name,
                "phone": staff.phone or ""
            }
        })
        user_id = auth_resp.user.id
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Auth user creation failed: {str(e)}")
    
    # 4. Insert into profiles
    profile_data = {
        "id": user_id,
        "email": staff.email,
        "first_name": staff.first_name,
        "last_name": staff.last_name,
        "phone": staff.phone,
        "membership_id": f"MEM-{user_id[:8]}",
        "status": "active",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    client.table("profiles").insert(profile_data).execute()
    
    # 5. Insert into org_members
    client.table("org_members").insert({
        "user_id": user_id,
        "org_id": org_id,
        "role": staff.role,
        "joined_at": datetime.now().isoformat()
    }).execute()
    
    # 6. Send invite email with temporary password
    if staff.send_invite_email:
        login_link = f"{PRODUCTION_HOST}/kdsiginin"
        html = f"""
        <h2>Welcome to {org_id}</h2>
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
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1])
    current_user_id, org_id, current_role = user_data
    
    if target_user_id == current_user_id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself")
    
    client = get_supabase()
    # Check that target user belongs to this organisation
    membership = client.table("org_members").select("role").eq("user_id", target_user_id).eq("org_id", org_id).maybe_single().execute()
    if not membership.data:
        raise HTTPException(status_code=404, detail="User not found in this organisation")
    
    # Prevent removing the only owner
    if membership.data["role"] == "owner" and current_role != "owner":
        raise HTTPException(status_code=403, detail="Only another owner can remove an owner")
    
    # Delete from org_members (profile remains but loses org access)
    client.table("org_members").delete().eq("user_id", target_user_id).eq("org_id", org_id).execute()
    
    # Optionally deactivate profile
    client.table("profiles").update({"status": "inactive"}).eq("id", target_user_id).execute()
    
    return {"message": "Staff member removed"}

@app.post("/auth/admin-reset-password")
async def admin_reset_password(
    request: Request,
    email: str,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin"]))
):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    
    client = get_supabase()
    # Verify that email belongs to a user in this organisation
    profile = client.table("profiles").select("id").eq("email", email).maybe_single().execute()
    if not profile.data:
        raise HTTPException(status_code=404, detail="Email not found")
    membership = client.table("org_members").select("role").eq("user_id", profile.data["id"]).eq("org_id", org_id).maybe_single().execute()
    if not membership.data:
        raise HTTPException(status_code=403, detail="User not in your organisation")
    
    # Generate reset link via Supabase
    try:
        # This sends a password reset email using Supabase's built‑in endpoint
        client.auth.reset_password_for_email(email)
        return {"message": f"Password reset email sent to {email}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/reset-password")
async def reset_password(request: Request, req: ResetPasswordRequest):
    await rate_limit(get_client_ip(request))
    try:
        get_supabase().auth.reset_password_for_email(req.email)
        return {"message": "Password reset email sent"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ------------------------------------------------------------------
# Admin: create organisation
# ------------------------------------------------------------------
class CreateOrgRequest(BaseModel):
    org_name: str
    location: str
    niche: str
    budget: int

@app.post("/admin/create-org")
async def create_organisation(request: Request, req: CreateOrgRequest, x_admin_key: str = Header(..., alias="X-Admin-Key")):
    await rate_limit(get_client_ip(request))
    if x_admin_key != ADMIN_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    client = get_supabase()
    invite_code = await generate_invite_code()
    result = client.table("organisations").insert({
        "org_name": req.org_name,
        "location": req.location,
        "niche": req.niche,
        "budget": req.budget,
        "invite_code": invite_code,
        "created_at": datetime.now().isoformat(),
        "payment_gateway_config": {"provider": "paystack", "credentials": {}}
    }).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed")
    return {"org_id": result.data[0]["id"], "invite_code": invite_code, "message": "Organisation created"}

@app.get("/public/org-info")
async def org_info(request: Request, invite_code: str):
    await rate_limit(get_client_ip(request))
    client = get_supabase()
    result = client.table("organisations").select("org_name").eq("invite_code", invite_code).maybe_single().execute()
    if not result or not result.data:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return {"org_name": result.data["org_name"]}

# ------------------------------------------------------------------
# DEBUG ENDPOINTS
# ------------------------------------------------------------------
@app.get("/debug/check-org-members")
async def debug_org_members(request: Request, user_id: str, x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    await rate_limit(get_client_ip(request))
    client = get_supabase()
    try:
        result = client.table("org_members").select("*").eq("user_id", user_id).execute()
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
async def debug_key_info(request: Request):
    await rate_limit(get_client_ip(request))
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
    result = client.table("organisations").select("org_name").eq("id", org_id).maybe_single().execute()
    return {"org_name": result.data["org_name"] if result and result.data else "Unknown Org"}

# ------------------------------------------------------------------
# INVENTORY MANAGEMENT (role-protected)
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

@app.get("/inventory")
async def get_inventory(request: Request, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "sales_rep", "finance"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    result = client.table("inventory").select("*").eq("org_id", org_id).order("id").execute()
    return result.data

@app.post("/inventory")
async def create_inventory_item(request: Request, item: InventoryItem, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    data = item.dict()
    data["org_id"] = org_id
    result = client.table("inventory").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create inventory item")
    return result.data[0]

@app.put("/inventory/{item_id}")
async def update_inventory(request: Request, item_id: int, item: InventoryItem, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    data = {k: v for k, v in item.dict().items() if v is not None}
    data["updated_at"] = datetime.now().isoformat()
    result = client.table("inventory").update(data).eq("id", item_id).eq("org_id", org_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return result.data[0]

@app.delete("/inventory/{item_id}")
async def delete_inventory(request: Request, item_id: int, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    result = client.table("inventory").delete().eq("id", item_id).eq("org_id", org_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return {"message": "Deleted successfully"}

@app.get("/inventory/public-list")
async def public_inventory(request: Request, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    items = client.table("inventory").select("id, description, price_naira, current_qty, image_url").eq("org_id", org_id).gt("current_qty", 0).execute()
    return items.data

# ------------------------------------------------------------------
# BULK INVENTORY UPLOAD (CSV) - role-protected
# ------------------------------------------------------------------
@app.post("/inventory/bulk-upload")
async def bulk_upload_inventory(
    request: Request,
    file: UploadFile = File(...),
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "inventory_manager"]))
):
    await rate_limit(get_client_ip(request), user_data[1])
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

        existing_items = client.table("inventory") \
            .select("id, item_code, current_qty, cost_price_naira") \
            .eq("org_id", org_id) \
            .execute()
        existing_map = {}
        for item in existing_items.data:
            if item.get("item_code"):
                existing_map[item["item_code"]] = item

        new_items = []
        updates = []
        errors = []

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
                    "updated_at": datetime.now().isoformat()
                }

                if update_data["cost_price_naira"] != existing.get("cost_price_naira", 0):
                    try:
                        client.table("inventory_cost_history").insert({
                            "item_code": item_code,
                            "org_id": org_id,
                            "old_cost": existing.get("cost_price_naira", 0),
                            "new_cost": update_data["cost_price_naira"],
                            "changed_at": datetime.now().isoformat()
                        }).execute()
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
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
                new_items.append(new_item)

        if errors:
            raise HTTPException(status_code=400, detail="; ".join(errors[:10]))

        updated_count = 0
        for item_code, update_data in updates:
            result = client.table("inventory") \
                .update(update_data) \
                .eq("org_id", org_id) \
                .eq("item_code", item_code) \
                .execute()
            if result.data:
                updated_count += 1

        inserted_count = 0
        if new_items:
            result = client.table("inventory").insert(new_items).execute()
            inserted_count = len(result.data) if result.data else 0

        return {
            "message": f"Upload complete. Inserted: {inserted_count}, Updated: {updated_count}",
            "inserted": inserted_count,
            "updated": updated_count
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"CSV processing failed: {str(e)}")
        
# ------------------------------------------------------------------
# SALES SUMMARY & TREND (role-protected)
# ------------------------------------------------------------------
@app.get("/sales/product-stats")
async def product_stats(request: Request, start_date: str, end_date: str, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()

    sales = client.table("sales").select("id") \
        .eq("org_id", org_id) \
        .gte("created_at", start_date) \
        .lte("created_at", end_date) \
        .execute()
    sales_data = sales.data if hasattr(sales, 'data') else []
    if not sales_data:
        return {"product_stats": []}

    sale_ids = [s["id"] for s in sales_data]

    items = client.table("sale_items").select("product_name, quantity, subtotal, inventory_id") \
        .in_("sale_id", sale_ids) \
        .execute()
    items_data = items.data if hasattr(items, 'data') else []
    if not items_data:
        return {"product_stats": []}

    inventory_ids = list(set([it["inventory_id"] for it in items_data if it.get("inventory_id")]))
    inv_query = client.table("inventory").select("id, cost_price_naira").in_("id", inventory_ids).execute()
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
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()

    sales = client.table("sales").select("id, total_amount") \
        .eq("org_id", org_id) \
        .gte("created_at", start_date) \
        .lte("created_at", end_date) \
        .execute()
    sales_data = sales.data if hasattr(sales, 'data') else []
    if not sales_data:
        return {"total_revenue": 0, "total_cogs": 0, "total_profit": 0, "count": 0}

    sale_ids = [s["id"] for s in sales_data]
    items = client.table("sale_items").select("sale_id, quantity, subtotal, inventory_id") \
        .in_("sale_id", sale_ids) \
        .execute()
    items_data = items.data if hasattr(items, 'data') else []

    inv_ids = list(set([it["inventory_id"] for it in items_data if it.get("inventory_id")]))
    inv_res = client.table("inventory").select("id, cost_price_naira").in_("id", inv_ids).execute()
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
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    start_date = (datetime.now() - timedelta(days=days)).isoformat()
    result = client.table("sales").select("total_amount, created_at") \
        .eq("org_id", org_id) \
        .gte("created_at", start_date) \
        .order("created_at", desc=False) \
        .execute()
    daily = {}
    for s in result.data:
        date_str = s["created_at"][:10]
        daily[date_str] = daily.get(date_str, 0) + s["total_amount"]
    trend = [{"date": d, "revenue": daily[d]} for d in sorted(daily.keys())]
    return trend

# ------------------------------------------------------------------
# LEADS (full CRUD) – role-protected
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
    await rate_limit(get_client_ip(request), user_data[1])
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
        result = get_supabase().table("org_leads").insert(leads_to_insert).execute()
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
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    query = client.table("org_leads").select("*").eq("org_id", org_id)
    if status:
        query = query.eq("status", status)
    if source:
        query = query.eq("source", source)
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"leads": result.data}

@app.post("/leads")
async def create_lead(request: Request, lead: LeadCreate, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    data = lead.dict()
    data["org_id"] = org_id
    if not data.get("acquired_date"):
        data["acquired_date"] = datetime.now().date().isoformat()
    result = client.table("org_leads").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create lead")
    return result.data[0]

@app.patch("/leads/{lead_id}")
async def update_lead(request: Request, lead_id: str, lead: LeadUpdate, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    data = {k: v for k, v in lead.dict().items() if v is not None}
    data["updated_at"] = datetime.now().isoformat()
    result = client.table("org_leads").update(data).eq("id", lead_id).eq("org_id", org_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    return result.data[0]

@app.delete("/leads/{lead_id}")
async def delete_lead(request: Request, lead_id: str, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    result = client.table("org_leads").delete().eq("id", lead_id).eq("org_id", org_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"message": "Lead deleted"}

@app.get("/leads/metrics")
async def get_lead_metrics(request: Request, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep", "finance"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    leads = client.table("org_leads").select("*").eq("org_id", org_id).execute()
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
# FORECAST & CAC TARGET – role-protected
# ------------------------------------------------------------------
class ForecastRequest(BaseModel):
    months: int = 6
    target_growth_rate: Optional[float] = None
    additional_ad_spend: Optional[float] = None

@app.post("/analytics/forecast")
async def forecast(request: Request, req: ForecastRequest, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    sales = client.table("sales").select("total_amount, sale_date").eq("org_id", org_id).eq("status", "completed").order("sale_date", desc=True).limit(10).execute()
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
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    sales_data = client.table("sales").select("total_amount").eq("org_id", org_id).eq("status", "completed").execute()
    if sales_data.data and len(sales_data.data) > 0:
        total_historical_revenue = sum(s["total_amount"] for s in sales_data.data)
        average_order_value = total_historical_revenue / len(sales_data.data)
    else:
        average_order_value = 5000.0
    leads = client.table("org_leads").select("*").eq("org_id", org_id).execute()
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
# SUPPORT TICKETS – role-protected
# ------------------------------------------------------------------
class TicketCreate(BaseModel):
    subject: str
    priority: str = "normal"
    message: str

@app.post("/api/support/ticket")
async def create_ticket(request: Request, ticket: TicketCreate, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support", "customer"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    user_id, org_id, _ = user_data
    client = get_supabase()
    ticket_data = {
        "user_id": user_id,
        "org_id": org_id,
        "subject": ticket.subject,
        "priority": ticket.priority,
        "status": "open",
        "created_at": datetime.now().isoformat()
    }
    res = client.table("support_tickets").insert(ticket_data).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create ticket")
    ticket_id = res.data[0]["id"]
    client.table("ticket_messages").insert({
        "ticket_id": ticket_id,
        "sender_type": "user",
        "sender_id": user_id,
        "message": ticket.message,
        "created_at": datetime.now().isoformat()
    }).execute()
    return {"ticket_id": ticket_id, "confirmation": f"Ticket #{ticket_id[:8]} created"}

@app.get("/support/tickets")
async def get_tickets(request: Request, status: Optional[str] = None, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support", "customer"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    user_id, org_id, _ = user_data
    client = get_supabase()
    query = client.table("support_tickets").select("*").eq("org_id", org_id).eq("user_id", user_id)
    if status:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).execute()
    return {"tickets": result.data}

@app.get("/support/tickets/{ticket_id}")
async def get_ticket_detail(request: Request, ticket_id: str, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support", "customer"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    user_id, org_id, _ = user_data
    client = get_supabase()
    ticket = client.table("support_tickets").select("*").eq("id", ticket_id).eq("org_id", org_id).eq("user_id", user_id).maybe_single().execute()
    if not ticket or not ticket.data:
        raise HTTPException(status_code=404, detail="Ticket not found")
    messages = client.table("ticket_messages").select("*").eq("ticket_id", ticket_id).order("created_at", desc=False).execute()
    return {"ticket": ticket.data, "messages": messages.data}

class TicketMessageReq(BaseModel):
    message: str

@app.post("/support/tickets/{ticket_id}/message")
async def add_ticket_message(request: Request, ticket_id: str, msg: TicketMessageReq, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support", "customer"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    user_id, org_id, _ = user_data
    client = get_supabase()
    ticket = client.table("support_tickets").select("id").eq("id", ticket_id).eq("org_id", org_id).eq("user_id", user_id).maybe_single().execute()
    if not ticket or not ticket.data:
        raise HTTPException(status_code=404, detail="Ticket not found")
    client.table("ticket_messages").insert({
        "ticket_id": ticket_id,
        "sender_type": "agent",
        "sender_id": user_id,
        "message": msg.message,
        "created_at": datetime.now().isoformat()
    }).execute()
    messages = client.table("ticket_messages").select("*").eq("ticket_id", ticket_id).order("created_at", desc=False).execute()
    return {"messages": messages.data}

class ResolveReq(BaseModel):
    resolution_notes: str

@app.post("/support/tickets/{ticket_id}/resolve")
async def resolve_ticket(request: Request, ticket_id: str, req: ResolveReq, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    user_id, org_id, _ = user_data
    client = get_supabase()
    client.table("support_tickets").update({
        "status": "resolved",
        "resolution_notes": req.resolution_notes,
        "resolved_at": datetime.now().isoformat()
    }).eq("id", ticket_id).eq("org_id", org_id).eq("user_id", user_id).execute()
    return {"message": "Ticket resolved"}

# ===================== CUSTOMER CONTEXT =====================
@app.get("/support/customer-context")
async def customer_context(request: Request, target_user_id: Optional[str] = None, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "support"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    current_user_id, org_id, _ = user_data
    user_id = target_user_id if target_user_id else current_user_id
    client = get_supabase()
    try:
        if user_id == current_user_id:
            profile = client.table("profiles").select("*").eq("id", user_id).maybe_single().execute()
            loyalty = None
            if profile and profile.data and profile.data.get("membership_id"):
                try:
                    loyalty = client.table("customer_points_summary").select("*").eq("membership_id", profile.data["membership_id"]).maybe_single().execute()
                except Exception as e:
                    logger.warning(f"Loyalty table may not exist: {e}")
            return {"profile": profile.data if profile else None, "loyalty": loyalty.data if loyalty else None}
        membership = client.table("org_members").select("org_id").eq("user_id", user_id).maybe_single().execute()
        if not membership or not membership.data or membership.data["org_id"] != org_id:
            raise HTTPException(status_code=403, detail="Not authorised to access this user's data")
        profile = client.table("profiles").select("*").eq("id", user_id).maybe_single().execute()
        loyalty = None
        if profile and profile.data and profile.data.get("membership_id"):
            try:
                loyalty = client.table("customer_points_summary").select("*").eq("membership_id", profile.data["membership_id"]).maybe_single().execute()
            except Exception as e:
                logger.warning(f"Loyalty table may not exist: {e}")
        return {"profile": profile.data if profile else None, "loyalty": loyalty.data if loyalty else None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Customer context error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch customer context")

# ------------------------------------------------------------------
# MULTI‑GATEWAY PAYMENT SYSTEM (Adapter Pattern) – role-protected POS endpoints
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

class POSCheckoutRequest(BaseModel):
    items: List[CartItem]
    payment_method: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    shipping_address: Optional[str] = None
    delivery_fee: float = 0.0
    handling_fee: float = 0.0

# ------------------------------------------------------------------
# OPTIMIZED /pos/checkout WITH BATCHING + delivery fees (role-protected)
# ------------------------------------------------------------------
@app.post("/pos/checkout")
async def checkout(request: Request, req: CheckoutRequest, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    user_id, org_id, _ = user_data
    client = get_supabase()

    org = client.table("organisations").select("payment_gateway_config, subaccount_code, org_name").eq("id", org_id).maybe_single().execute()
    if not org or not org.data:
        raise HTTPException(status_code=400, detail="Organisation not found")
    gateway_config = org.data.get("payment_gateway_config", {"provider": "paystack", "credentials": {}})
    subaccount_code = org.data.get("subaccount_code")

    product_ids = [item.inventory_id for item in req.items]
    inventory_response = client.table("inventory").select("*").eq("org_id", org_id).in_("id", product_ids).execute()
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

    receipt_num = f"RCP-{org_id[:4]}-{int(datetime.now().timestamp())}"
    payment_ref = str(uuid.uuid4())
    sale_data = {
        "org_id": org_id,
        "user_id": user_id,
        "total_amount": total,
        "payment_method": req.payment_method,
        "payment_reference": payment_ref,
        "status": "pending",
        "customer_name": req.customer_name,
        "customer_phone": req.customer_phone,
        "customer_email": req.customer_email,
        "receipt_number": receipt_num,
        "shipping_address": req.shipping_address,
        "delivery_fee": req.delivery_fee,
        "handling_fee": req.handling_fee,
        "created_at": datetime.now().isoformat()
    }
    sale_res = client.table("sales").insert(sale_data).execute()
    if not sale_res.data:
        raise HTTPException(status_code=500, detail="Failed to create sale")
    sale_id = sale_res.data[0]["id"]

    if sale_items_batch:
        for item in sale_items_batch:
            item["sale_id"] = sale_id
        client.table("sale_items").insert(sale_items_batch).execute()

    gateway = get_payment_gateway_from_config(gateway_config)
    customer_email = req.customer_email or f"guest_{payment_ref}@example.com"

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
# POS TERMINAL CHECKOUT (role-protected)
# ------------------------------------------------------------------
@app.post("/pos/terminal/checkout")
async def pos_terminal_checkout(request: Request, req: POSCheckoutRequest, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "sales_rep"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    user_id, org_id, _ = user_data

    items_payload = [{"inventory_id": item.inventory_id, "quantity": item.quantity} for item in req.items]
    receipt_num = f"POS-{org_id[:4]}-{int(datetime.now().timestamp())}"

    try:
        rpc_response = get_supabase().rpc(
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
            }
        ).execute()

        result = rpc_response.data
        if not result or not result.get("success"):
            error_msg = result.get("error", "Unknown error") if result else "No response"
            logger.error(f"Batch checkout failed: {error_msg}")
            raise HTTPException(status_code=400, detail=f"Checkout failed: {error_msg}")

        return {
            "sale_id": result["sale_id"],
            "receipt_number": receipt_num,
            "total": result["total_amount"],
            "payment_reference": result["payment_reference"],
            "execution_ms": result["execution_ms"],
            "updated_stock": result.get("updated_stock", []),
            "message": "Sale completed (cash)"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch checkout exception: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# ------------------------------------------------------------------
# WEBHOOKS (unchanged - no auth)
# ------------------------------------------------------------------
@app.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature")
    try:
        payload = json.loads(raw_body)
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    event = payload.get("event")
    if event != "charge.success":
        return {"status": "ignored"}
    data = payload["data"]
    reference = data.get("reference")
    metadata = data.get("metadata", {})
    org_id = metadata.get("org_id")
    if not org_id:
        logger.error("Webhook missing org_id")
        return {"status": "ignored"}

    client = get_supabase()
    org = client.table("organisations").select("payment_gateway_config").eq("id", org_id).maybe_single().execute()
    if not org or not org.data:
        logger.error(f"Org {org_id} not found")
        return {"status": "ignored"}

    gateway = get_payment_gateway_from_config(org.data.get("payment_gateway_config", {}))
    if not gateway.verify_webhook_signature(raw_body, signature):
        logger.error("Invalid Paystack signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    sale = client.table("sales").select("*").eq("payment_reference", reference).maybe_single().execute()
    if sale and sale.data and sale.data["status"] == "pending":
        client.table("sales").update({
            "status": "completed",
            "shipping_status": "processing"
        }).eq("id", sale.data["id"]).execute()
        items = client.table("sale_items").select("*").eq("sale_id", sale.data["id"]).execute()
        for item in items.data:
            current_stock = client.table("inventory").select("current_qty").eq("id", item["inventory_id"]).execute().data[0]["current_qty"]
            client.table("inventory").update({"current_qty": current_stock - item["quantity"]}).eq("id", item["inventory_id"]).execute()
        logger.info(f"Paystack webhook completed for {reference} – shipping_status set to processing")
    else:
        logger.info(f"Paystack webhook received for {reference} – already processed")
    return {"status": "ok"}


@app.post("/webhook/flutterwave")
async def flutterwave_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-verif-hash")
    try:
        payload = json.loads(raw_body)
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    event = payload.get("event")
    if event != "charge.completed":
        return {"status": "ignored"}
    data = payload["data"]
    reference = data.get("tx_ref")
    meta = data.get("meta", {})
    org_id = meta.get("org_id")
    if not org_id:
        logger.error("Flutterwave webhook missing org_id")
        return {"status": "ignored"}

    client = get_supabase()
    org = client.table("organisations").select("payment_gateway_config").eq("id", org_id).maybe_single().execute()
    if not org or not org.data:
        logger.error(f"Org {org_id} not found")
        return {"status": "ignored"}

    gateway = get_payment_gateway_from_config(org.data.get("payment_gateway_config", {}))
    if not gateway.verify_webhook_signature(raw_body, signature):
        logger.error("Invalid Flutterwave signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    sale = client.table("sales").select("*").eq("payment_reference", reference).maybe_single().execute()
    if sale and sale.data and sale.data["status"] == "pending":
        client.table("sales").update({
            "status": "completed",
            "shipping_status": "processing"
        }).eq("id", sale.data["id"]).execute()
        items = client.table("sale_items").select("*").eq("sale_id", sale.data["id"]).execute()
        for item in items.data:
            current_stock = client.table("inventory").select("current_qty").eq("id", item["inventory_id"]).execute().data[0]["current_qty"]
            client.table("inventory").update({"current_qty": current_stock - item["quantity"]}).eq("id", item["inventory_id"]).execute()
        logger.info(f"Flutterwave webhook completed for {reference} – shipping_status set to processing")
    else:
        logger.info(f"Flutterwave webhook received for {reference} – already processed")
    return {"status": "ok"}

# ------------------------------------------------------------------
# CHAT STREAM (role-aware – customers and support can use)
# ------------------------------------------------------------------
class ChatStreamReq(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=2000)

@app.post("/support/chat-stream")
async def chat_stream(request: Request, req: ChatStreamReq, user_data: Tuple[str, str, str] = Depends(get_current_user_with_role)):
    await rate_limit(get_client_ip(request), user_data[1])
    if not re.match(r'^[a-zA-Z0-9_-]+$', req.session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")
    user_id, org_id, _ = user_data
    reply, ticket_id = await get_strategic_reply(req.message, user_id, org_id, req.session_id, "web_widget")
    await save_conversation(user_id, org_id, req.session_id, req.message, reply, "web_widget")
    response = {"response": reply}
    if ticket_id:
        response["ticket_id"] = ticket_id
    return response

# ------------------------------------------------------------------
# WHATSAPP WEBHOOK (no auth, but rate limited)
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
            profile = client.table("profiles").select("id").eq("phone", from_phone).maybe_single().execute()
            if profile and profile.data:
                membership = client.table("org_members").select("org_id").eq("user_id", profile.data["id"]).maybe_single().execute()
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
    result = client.table("sales").select("receipt_number, total_amount, shipping_status, tracking_number, shipping_carrier, estimated_delivery, created_at")\
        .eq("receipt_number", receipt_number).eq("customer_email", email).maybe_single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Order not found")
    return result.data

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
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    sale = client.table("sales").select("*").eq("id", sale_id).eq("org_id", org_id).maybe_single().execute()
    if not sale.data:
        raise HTTPException(status_code=404, detail="Sale not found")
    data = {k: v for k, v in update.dict().items() if v is not None}
    data["updated_at"] = datetime.now().isoformat()
    client.table("sales").update(data).eq("id", sale_id).execute()
    return {"message": "Shipping updated"}

# ------------------------------------------------------------------
# DELIVERY ESTIMATION (organisation-specific rates) – any authenticated user
# ------------------------------------------------------------------
class DeliveryEstimateRequest(BaseModel):
    address: str
    items: List[Dict]   # each item has inventory_id, quantity

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
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data

    # Default store coordinates from env
    store_lat = float(os.environ.get("STORE_LAT", "6.5244"))
    store_lng = float(os.environ.get("STORE_LNG", "3.3792"))
    client = get_supabase()

    # Fetch organisation details (including delivery rates and store location)
    org_result = client.table("organisations").select(
        "latitude, longitude, delivery_base_fee, delivery_per_km_rate, delivery_per_kg_rate, "
        "handling_surcharge_fragile, handling_surcharge_bulky, handling_surcharge_hazardous"
    ).eq("id", org_id).maybe_single().execute()
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
        # fallback to env or defaults
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

    # Geocode customer address
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

    # Fetch product details for weight and handling
    if not req.items:
        raise HTTPException(status_code=400, detail="No items provided")
    inventory_ids = [item["inventory_id"] for item in req.items]
    inventory_items = client.table("inventory").select("id, weight_kg, handling_category").in_("id", inventory_ids).execute()
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
    delivery_fee = round(delivery_fee / 50) * 50   # round to nearest 50 Naira
    handling_fee = 200   # fixed packaging fee (could also be per‑org)

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
# FULFILLMENT DASHBOARD ENDPOINTS (role-protected for logistics)
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
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    query = client.table("sales").select("*, sale_items(id, product_name, quantity, unit_price)") \
        .eq("org_id", org_id)
    if not include_pending:
        query = query.neq("status", "pending")
    if status:
        query = query.eq("shipping_status", status)
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"orders": result.data}

@app.get("/fulfillment/order/{order_id}")
async def get_fulfillment_order(request: Request, order_id: str, user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "logistics"]))):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    order = client.table("sales").select("*, sale_items(*)").eq("id", order_id).eq("org_id", org_id).maybe_single().execute()
    if not order.data:
        raise HTTPException(status_code=404, detail="Order not found")
    return order.data

@app.put("/fulfillment/order/{order_id}/status")
async def update_fulfillment_status(
    request: Request,
    order_id: str,
    update: FulfillmentUpdate,
    background_tasks: BackgroundTasks,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "logistics"]))
):
    await rate_limit(get_client_ip(request), user_data[1])
    _, org_id, _ = user_data
    client = get_supabase()
    
    order = client.table("sales").select("shipping_status, customer_email, status").eq("id", order_id).eq("org_id", org_id).maybe_single().execute()
    if not order.data:
        raise HTTPException(status_code=404, detail="Order not found")
    old_status = order.data.get("shipping_status") or "pending"
    new_status = update.shipping_status
    
    data = {
        "shipping_status": new_status,
        "updated_at": datetime.now().isoformat()
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
    
    result = client.table("sales").update(data).eq("id", order_id).eq("org_id", org_id).execute()
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
# DIAGNOSTIC & ROOT (no auth, but rate limited)
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
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

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
        function addMsg(txt, role){{
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
# NEW INTELLIGENCE MODULE (unchanged)
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
        result = client.table("intelligence_history") \
            .select("query, response") \
            .eq("org_id", org_id) \
            .order("created_at", desc=True) \
            .limit(3) \
            .execute()
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
        org = client.table("organisations").select("plan").eq("id", org_id).maybe_single().execute()
        plan = org.data.get("plan", "free") if org and org.data else "free"
        is_premium = plan in ["pro", "enterprise"]
        if is_premium:
            return {"remaining": -1, "is_premium": True, "plan": plan, "request_count": 0}
        now = datetime.now(timezone.utc)
        month_year = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        usage = client.table("intelligence_usage").select("request_count").eq("org_id", org_id).eq("month_year", month_year).maybe_single().execute()
        count = usage.data["request_count"] if usage and usage.data else 0
        remaining = max(0, 50 - count)
        return {"remaining": remaining, "is_premium": False, "plan": plan, "request_count": count}

    @staticmethod
    async def increment_usage(org_id: str):
        client = get_supabase()
        now = datetime.now(timezone.utc)
        month_year = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        existing = client.table("intelligence_usage").select("request_count").eq("org_id", org_id).eq("month_year", month_year).maybe_single().execute()
        if existing and existing.data:
            new_count = existing.data["request_count"] + 1
            client.table("intelligence_usage").update({"request_count": new_count, "updated_at": now.isoformat()}).eq("org_id", org_id).eq("month_year", month_year).execute()
        else:
            client.table("intelligence_usage").insert({
                "org_id": org_id,
                "month_year": month_year,
                "request_count": 1,
                "updated_at": now.isoformat()
            }).execute()

class AIOrchestrator:
    @staticmethod
    async def generate(system_prompt: str, user_prompt: str) -> Tuple[str, str, float]:
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        start = time.time()
        model = "groq/llama3" if GROQ_API_KEY else "gemini"
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
# Intelligence Endpoints (role-protected)
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
    client.table("intelligence_history").insert({
        "org_id": org_id,
        "user_id": user_id,
        "query": req.message[:500],
        "response": answer[:2000],
        "pillar": pillar_info["pillar"],
        "model": model_used,
        "created_at": datetime.now(timezone.utc).isoformat()
    }).execute()
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
    result = client.table("intelligence_history") \
        .select("id, query, response, created_at, pillar, model") \
        .eq("org_id", org_id) \
        .order("created_at", desc=True) \
        .range(offset, offset + limit - 1) \
        .execute()
    return {"history": result.data or []}

@app.get("/intelligence/history/{conv_id}")
async def get_intelligence_conversation(conv_id: str, ctx: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "finance", "sales_rep"]))):
    _, org_id, _ = ctx
    client = get_supabase()
    result = client.table("intelligence_history") \
        .select("*") \
        .eq("id", conv_id) \
        .eq("org_id", org_id) \
        .maybe_single() \
        .execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation": result.data}

# ------------------------------------------------------------------
# Serve HTML pages (no auth, but you can add role-based redirects if needed)
# ------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root_html():
    with open("kdconc.html", "r") as f:
        return f.read()

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)