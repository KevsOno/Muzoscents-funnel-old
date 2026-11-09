# support_tickets.py
#
# Multi-tenant, multi-branch support-ticket module.
#
# Architecture:
#
#   - Recipients live in organisations.escalation_config (JSONB), not in
#     environment variables. Environment variables are platform-wide and
#     would notify every tenant's customers on behalf of every other
#     tenant — a leak, not a feature.
#
#   - Email and WhatsApp delivery go through the existing abstractions
#     already exported from main.py:
#         send_sendgrid_email          (email provider — swap Brevo→SES
#                                        in that one function)
#         send_whatsapp_message_with_retry  (WhatsApp provider)
#     This module never imports a provider SDK, never names a provider,
#     and never needs to change when the provider changes.
#
#   - Access control is role + branch aware:
#         customer         → only their own tickets
#         owner            → all tickets in the org
#         admin / support  → tickets in their assigned branch(es)
#     Branch scoping uses branch_members via get_user_branches(), the
#     same rule /stock-transfers, /grn, and /fulfillment/orders use.
#
#   - Ticket creation supports both legacy and new field names:
#         POST /api/support/ticket   (legacy: `message`)
#         POST /support/tickets      (new:    `description`)
#     Both routes registered, both fields accepted.

from datetime import datetime, timezone
from typing import Tuple, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from main import (
    get_supabase,
    run_sync_db_call,
    rate_limit,
    get_client_ip,
    resolve_request_branch_for_write,
    get_user_branches,
    send_sendgrid_email,
    send_whatsapp_message_with_retry,
    logger,
)
from deps import require_role


router = APIRouter(tags=["Support Tickets"])


# ─────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────

class TicketCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    priority: str = "normal"
    message: Optional[str] = None
    description: Optional[str] = None
    user_id: Optional[str] = None   # honoured for agent callers only

    @property
    def body_text(self) -> str:
        return (self.message or self.description or "").strip()


class TicketMessageReq(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class ResolveReq(BaseModel):
    resolution_notes: str = Field("", max_length=4000)


class EscalateReq(BaseModel):
    department: str = Field(..., min_length=1, max_length=100)
    method: str = Field("email", description="'email' or 'whatsapp'")
    note: str = Field("", max_length=4000)


# ─────────────────────────────────────────────────────────────────────
# Department name ↔ config key normalisation
#
# The frontend dropdown sends human-readable values ("Technical Support").
# The config JSONB uses snake_case keys ("technical_support") because that
# is the conventional shape for keys inside JSONB blobs — no spaces, no
# case sensitivity headaches.
# ─────────────────────────────────────────────────────────────────────

KNOWN_DEPARTMENTS = {
    "Technical Support": "technical_support",
    "Billing":           "billing",
    "Logistics":         "logistics",
    "Sales":             "sales",
    "Management":        "management",
}


def _dept_key(department: str) -> str:
    """Normalise a department label to a config key."""
    if department in KNOWN_DEPARTMENTS:
        return KNOWN_DEPARTMENTS[department]
    return department.strip().lower().replace(" ", "_")


# ─────────────────────────────────────────────────────────────────────
# Access scoping — role + branch aware
# ─────────────────────────────────────────────────────────────────────

async def _scope_for_caller(user_id: str, org_id: str, role: str) -> dict:
    """
    Resolve the filter to apply to any ticket query for this caller.

    Returns:
      {"user_filter": <uuid>|None, "branch_filter": <uuid>|<list>|None}
    """
    if role == "customer":
        return {"user_filter": user_id, "branch_filter": None}

    if role == "owner":
        return {"user_filter": None, "branch_filter": None}

    # admin / support / any other staff role
    branches = await get_user_branches(user_id, org_id)
    if not branches:
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to any branch, so you have no ticket access.",
        )
    if len(branches) == 1:
        return {"user_filter": None, "branch_filter": branches[0]["id"]}
    return {"user_filter": None, "branch_filter": [b["id"] for b in branches]}


def _apply_scope(query, scope: dict):
    if scope.get("user_filter"):
        query = query.eq("user_id", scope["user_filter"])
    bf = scope.get("branch_filter")
    if isinstance(bf, list):
        query = query.in_("branch_id", bf)
    elif bf:
        query = query.eq("branch_id", bf)
    return query


async def _fetch_accessible_ticket(
    ticket_id: str, org_id: str, user_id: str, role: str
) -> dict:
    """
    Fetch a ticket and confirm the caller can access it.
    Raises 404 (never 403) so a caller cannot distinguish "does not
    exist" from "belongs to another branch".
    """
    scope = await _scope_for_caller(user_id, org_id, role)
    client = get_supabase()

    query = (
        client.table("support_tickets")
        .select("*")
        .eq("id", ticket_id)
        .eq("org_id", org_id)
    )
    query = _apply_scope(query, scope)

    res = await run_sync_db_call(query.maybe_single().execute)
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return res.data


# ─────────────────────────────────────────────────────────────────────
# Escalation-config resolution
#
# Config lives on organisations.escalation_config. The lookup order at
# escalate time is:
#
#   1. ticket.branch_id → config.branches[ticket.branch_id].departments[dept][method]
#   2. config.departments[dept][method]
#   3. HTTPException 422 with a message that points at the config endpoint
#
# There is no env-var fallback. That is deliberate.
# ─────────────────────────────────────────────────────────────────────

async def _read_escalation_config(org_id: str) -> dict:
    client = get_supabase()
    res = await run_sync_db_call(
        client.table("organisations")
        .select("escalation_config")
        .eq("id", org_id)
        .maybe_single()
        .execute
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return res.data.get("escalation_config") or {}


def _resolve_escalation_target(
    config: dict,
    department: str,
    method: str,
    branch_id: Optional[str],
) -> Optional[str]:
    """
    Walk the resolution order and return the target, or None.

    `config` is the raw escalation_config JSONB from the org.
    """
    dept_key = _dept_key(department)
    if method not in ("email", "whatsapp"):
        return None

    # 1. branch-specific
    if branch_id:
        branch_cfg = (config.get("branches") or {}).get(str(branch_id)) or {}
        dept_cfg = (branch_cfg.get("departments") or {}).get(dept_key) or {}
        target = (dept_cfg.get(method) or "").strip()
        if target:
            return target

    # 2. org-level
    dept_cfg = (config.get("departments") or {}).get(dept_key) or {}
    target = (dept_cfg.get(method) or "").strip()
    if target:
        return target

    return None


# ─────────────────────────────────────────────────────────────────────
# Config management endpoints
# ─────────────────────────────────────────────────────────────────────

@router.get("/support/escalation-config")
async def get_escalation_config(
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "support"])
    ),
):
    _, org_id, _ = user_data
    return {
        "config": await _read_escalation_config(org_id),
        "known_departments": KNOWN_DEPARTMENTS,
    }


class EscalationConfigUpdate(BaseModel):
    config: dict


@router.put("/support/escalation-config")
async def put_escalation_config(
    payload: EscalationConfigUpdate,
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin"])
    ),
):
    """
    Replace the org's entire escalation_config.

    PUT, not PATCH. Config is a small complete document; "here is the
    full new config" is simpler to validate and safer than a partial
    merge that could leave stale targets behind.

    Shape validation is intentionally loose at the top level (JSONB is
    flexible) but strict about the fields that matter:

      - config.departments must be a dict of dicts
      - config.branches must be a dict of dicts
      - email values must contain '@'
      - whatsapp values must start with '+'

    Bad values are rejected with a 400 so the caller knows immediately
    rather than discovering it during a live escalation.
    """
    _, org_id, _ = user_data
    cfg = payload.config

    if not isinstance(cfg, dict):
        raise HTTPException(status_code=400, detail="config must be an object")

    def _validate_contacts(block: dict, path: str) -> None:
        if not isinstance(block, dict):
            raise HTTPException(status_code=400, detail=f"{path} must be an object")
        for dept, contacts in block.items():
            if not isinstance(contacts, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"{path}.{dept} must be an object",
                )
            email = contacts.get("email")
            if email is not None:
                if not isinstance(email, str) or "@" not in email:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{path}.{dept}.email must be a valid email",
                    )
            whatsapp = contacts.get("whatsapp")
            if whatsapp is not None:
                if not isinstance(whatsapp, str) or not whatsapp.startswith("+"):
                    raise HTTPException(
                        status_code=400,
                        detail=f"{path}.{dept}.whatsapp must start with '+'",
                    )

    if "departments" in cfg:
        _validate_contacts(cfg["departments"], "departments")

    if "branches" in cfg:
        branches = cfg["branches"]
        if not isinstance(branches, dict):
            raise HTTPException(status_code=400, detail="branches must be an object")
        for branch_id, branch_cfg in branches.items():
            if not isinstance(branch_cfg, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"branches.{branch_id} must be an object",
                )
            if "departments" in branch_cfg:
                _validate_contacts(
                    branch_cfg["departments"],
                    f"branches.{branch_id}.departments",
                )

    client = get_supabase()
    res = await run_sync_db_call(
        client.table("organisations")
        .update({
            "escalation_config": cfg,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", org_id)
        .execute
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to save config")

    return {"config": cfg}


# ─────────────────────────────────────────────────────────────────────
# Create ticket
# ─────────────────────────────────────────────────────────────────────

@router.post("/support/tickets")
@router.post("/api/support/ticket")
async def create_ticket_endpoint(
    request: Request,
    ticket: TicketCreate,
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "support", "customer"])
    ),
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    caller_id, org_id, role = user_data
    client = get_supabase()

    body = ticket.body_text
    if not body:
        raise HTTPException(
            status_code=400,
            detail="Either 'message' or 'description' must be provided",
        )

    # Attribution. A customer can only file on their own behalf even if
    # they send a user_id — no impersonation. An agent can file on behalf
    # of a customer, provided that customer belongs to this org.
    ticket_owner = caller_id
    if ticket.user_id and ticket.user_id != caller_id:
        if role not in ("owner", "admin", "support"):
            raise HTTPException(
                status_code=403,
                detail="Only agents can create tickets on behalf of another user",
            )
        m = await run_sync_db_call(
            client.table("org_members")
            .select("user_id")
            .eq("user_id", ticket.user_id)
            .eq("org_id", org_id)
            .maybe_single()
            .execute
        )
        l = await run_sync_db_call(
            client.table("org_leads")
            .select("profile_id")
            .eq("profile_id", ticket.user_id)
            .eq("org_id", org_id)
            .maybe_single()
            .execute
        )
        if not (m and m.data) and not (l and l.data):
            raise HTTPException(
                status_code=400,
                detail="Target customer is not part of this organisation",
            )
        ticket_owner = ticket.user_id

    branch_id = await resolve_request_branch_for_write(
        request, caller_id, org_id, role
    )
    now = datetime.now(timezone.utc).isoformat()

    ins = await run_sync_db_call(
        client.table("support_tickets").insert({
            "user_id":    ticket_owner,
            "org_id":     org_id,
            "branch_id":  branch_id,
            "subject":    ticket.subject,
            "priority":   ticket.priority or "normal",
            "status":     "open",
            "created_at": now,
        }).execute
    )
    if not ins.data:
        raise HTTPException(status_code=500, detail="Failed to create ticket")
    ticket_id = ins.data[0]["id"]

    await run_sync_db_call(
        client.table("ticket_messages").insert({
            "ticket_id":   ticket_id,
            "sender_type": "user" if ticket_owner == caller_id else "agent",
            "sender_id":   caller_id,
            "message":     body,
            "created_at":  now,
        }).execute
    )

    return {
        "ticket_id":    ticket_id,
        "confirmation": f"Ticket #{ticket_id[:8]} created",
    }


# ─────────────────────────────────────────────────────────────────────
# List / get / message / resolve
# ─────────────────────────────────────────────────────────────────────

@router.get("/support/tickets")
async def list_tickets_endpoint(
    request: Request,
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "support", "customer"])
    ),
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    caller_id, org_id, role = user_data
    client = get_supabase()

    scope = await _scope_for_caller(caller_id, org_id, role)

    query = client.table("support_tickets").select("*").eq("org_id", org_id)
    query = _apply_scope(query, scope)

    if status:
        query = query.eq("status", status)
    if from_date:
        query = query.gte("created_at", f"{from_date}T00:00:00Z")
    if to_date:
        query = query.lte("created_at", f"{to_date}T23:59:59.999999Z")

    result = await run_sync_db_call(
        query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute
    )
    return {"tickets": result.data or []}


@router.get("/support/tickets/{ticket_id}")
async def get_ticket_endpoint(
    request: Request,
    ticket_id: str,
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "support", "customer"])
    ),
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    caller_id, org_id, role = user_data
    client = get_supabase()

    ticket = await _fetch_accessible_ticket(ticket_id, org_id, caller_id, role)

    messages = await run_sync_db_call(
        client.table("ticket_messages")
        .select("*")
        .eq("ticket_id", ticket_id)
        .order("created_at", desc=False)
        .execute
    )
    return {"ticket": ticket, "messages": messages.data or []}


@router.post("/support/tickets/{ticket_id}/message")
async def add_ticket_message_endpoint(
    request: Request,
    ticket_id: str,
    msg: TicketMessageReq,
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "support", "customer"])
    ),
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    caller_id, org_id, role = user_data
    client = get_supabase()

    await _fetch_accessible_ticket(ticket_id, org_id, caller_id, role)

    sender_type = "agent" if role in ("owner", "admin", "support") else "customer"

    await run_sync_db_call(
        client.table("ticket_messages").insert({
            "ticket_id":   ticket_id,
            "sender_type": sender_type,
            "sender_id":   caller_id,
            "message":     msg.message,
            "created_at":  datetime.now(timezone.utc).isoformat(),
        }).execute
    )

    messages = await run_sync_db_call(
        client.table("ticket_messages")
        .select("*")
        .eq("ticket_id", ticket_id)
        .order("created_at", desc=False)
        .execute
    )
    return {"messages": messages.data or []}


@router.post("/support/tickets/{ticket_id}/resolve")
async def resolve_ticket_endpoint(
    request: Request,
    ticket_id: str,
    req: ResolveReq,
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "support"])
    ),
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    caller_id, org_id, role = user_data
    client = get_supabase()

    await _fetch_accessible_ticket(ticket_id, org_id, caller_id, role)

    upd = await run_sync_db_call(
        client.table("support_tickets").update({
            "status":           "resolved",
            "resolution_notes": req.resolution_notes,
            "resolved_at":      datetime.now(timezone.utc).isoformat(),
        }).eq("id", ticket_id).eq("org_id", org_id).execute
    )

    return {
        "message": "Ticket resolved",
        "ticket":  upd.data[0] if upd.data else None,
    }


# ─────────────────────────────────────────────────────────────────────
# Escalate
# ─────────────────────────────────────────────────────────────────────

@router.post("/support/tickets/{ticket_id}/escalate")
async def escalate_ticket_endpoint(
    request: Request,
    ticket_id: str,
    req: EscalateReq,
    user_data: Tuple[str, str, str] = Depends(
        require_role(["owner", "admin", "support"])
    ),
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    caller_id, org_id, role = user_data

    ticket = await _fetch_accessible_ticket(ticket_id, org_id, caller_id, role)

    method = (req.method or "email").lower()
    if method not in ("email", "whatsapp"):
        raise HTTPException(
            status_code=400,
            detail="method must be 'email' or 'whatsapp'",
        )

    # Look up the recipient from the org's own config. Branch-specific
    # entries win over org-level entries, which is what makes this
    # multi-branch: a ticket raised at Branch A notifies Branch A's
    # Billing contact if one is configured, otherwise falls back to
    # Org-wide Billing. No environment variables involved.
    config = await _read_escalation_config(org_id)
    target = _resolve_escalation_target(
        config, req.department, method, ticket.get("branch_id")
    )
    if not target:
        dept_key = _dept_key(req.department)
        raise HTTPException(
            status_code=422,
            detail=(
                f"No {method} escalation target is configured for "
                f"'{req.department}'"
                + (f" at this branch" if ticket.get("branch_id") else "")
                + f". Configure it via PUT /support/escalation-config "
                f"under departments.{dept_key}.{method}."
            ),
        )

    short_id = str(ticket.get("id", ticket_id))[:8]
    subject_line = f"[ESCALATION] Ticket #{short_id} – {ticket.get('subject', '')}"

    plain_body = (
        f"Ticket #{short_id} has been escalated.\n\n"
        f"Department: {req.department}\n"
        f"Priority:   {ticket.get('priority', 'normal')}\n"
        f"Status:     {ticket.get('status', 'open')}\n"
        f"Subject:    {ticket.get('subject', '')}\n\n"
        f"Agent note:\n{req.note or '(no note provided)'}\n\n"
        f"— Kevs bOS Support"
    )

    html_body = (
        f"<h2>Ticket #{short_id} — Escalated</h2>"
        f"<table cellpadding='4'>"
        f"<tr><td><strong>Department</strong></td><td>{req.department}</td></tr>"
        f"<tr><td><strong>Priority</strong></td><td>{ticket.get('priority', 'normal')}</td></tr>"
        f"<tr><td><strong>Status</strong></td><td>{ticket.get('status', 'open')}</td></tr>"
        f"<tr><td><strong>Subject</strong></td><td>{ticket.get('subject', '')}</td></tr>"
        f"</table>"
        f"<hr>"
        f"<p><strong>Agent note</strong></p>"
        f"<pre>{req.note or '(no note provided)'}</pre>"
    )

    # Deliver. Both senders are provider-agnostic thin wrappers already
    # defined in main.py. If the org migrates Brevo → SES tomorrow, only
    # send_sendgrid_email's body changes. This module stays untouched.
    delivery_error: Optional[str] = None
    try:
        if method == "email":
            ok = await send_sendgrid_email(target, subject_line, html_body)
            if not ok:
                delivery_error = "email provider reported a failure"
        else:
            await send_whatsapp_message_with_retry(target, plain_body)
    except Exception as e:
        delivery_error = str(e)

    # Log on the ticket regardless of delivery outcome, so the ticket
    # history always reflects that an escalation was attempted.
    log_line = (
        f"Escalated to {req.department} via {method} ({target})"
        + (f" — delivery FAILED: {delivery_error}" if delivery_error else " — delivered.")
        + (f" Note: {req.note}" if req.note else "")
    )
    client = get_supabase()
    await run_sync_db_call(
        client.table("ticket_messages").insert({
            "ticket_id":   ticket_id,
            "sender_type": "system",
            "sender_id":   caller_id,
            "message":     log_line,
            "created_at":  datetime.now(timezone.utc).isoformat(),
        }).execute
    )

    # Move to the Escalated queue even on delivery failure — the ticket
    # state changed (an agent tried to escalate it), and hiding that
    # would leave the ticket looking untouched.
    await run_sync_db_call(
        client.table("support_tickets")
        .update({"status": "pending"})
        .eq("id", ticket_id)
        .eq("org_id", org_id)
        .execute
    )

    if delivery_error:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Escalation recorded on the ticket but delivery via "
                f"{method} failed: {delivery_error}. The ticket has been "
                f"moved to the Escalated queue."
            ),
        )

    return {
        "message":   f"Ticket escalated to {req.department} via {method}",
        "ticket_id": ticket_id,
        "target":    target,
    }
