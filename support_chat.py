from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Tuple, Optional
from datetime import datetime, timezone
from uuid import UUID, uuid4
from main import get_supabase, run_sync_db_call, rate_limit, get_client_ip
from deps import require_role

router = APIRouter(prefix="/chat", tags=["Live Chat"])

class ChatMessageCreate(BaseModel):
    message: str = Field(..., max_length=2000)

@router.post("/session")
async def start_chat_session(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["customer", "owner", "admin"]))
):
    """Start or resume an open live chat session for a customer."""
    user_id, org_id, _ = user_data
    client = get_supabase()
    
    # 1. Check for an existing open session
    existing = await run_sync_db_call(
        client.table("chat_sessions")
        .select("id")
        .eq("user_id", user_id)
        .eq("org_id", org_id)
        .eq("status", "open")
        .eq("channel", "live_chat")
        .order("started_at", desc=True)
        .limit(1)
        .execute
    )

    if existing.data:
        return {"session_id": existing.data[0]["id"], "status": "open"}

    # 2. Create a new session if none exists
    session_id = str(uuid4())
    await run_sync_db_call(
        client.table("chat_sessions").insert({
            "id": session_id,
            "user_id": user_id,
            "org_id": org_id,
            "channel": "live_chat",
            "status": "open",
            "started_at": datetime.now(timezone.utc).isoformat()
        }).execute
    )
    return {"session_id": session_id, "status": "open"}

@router.post("/session/{session_id}/message")
async def send_chat_message(
    request: Request,
    session_id: str,
    payload: ChatMessageCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["customer", "owner", "admin", "support"]))
):
    """Send a message in a live chat."""
    user_id, org_id, role = user_data
    client = get_supabase()
    
    session = await run_sync_db_call(
        client.table("chat_sessions")
        .select("id")
        .eq("id", session_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute
    )
    if not session or not session.data:
        raise HTTPException(status_code=404, detail="Session not found")

    sender_type = "agent" if role in ["owner", "admin", "support"] else "customer"
    
    await run_sync_db_call(
        client.table("chat_messages").insert({
            "session_id": session_id,
            "user_id": user_id,
            "org_id": org_id,
            "sender_type": sender_type,
            "message": payload.message,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute
    )
    return {"status": "sent"}

@router.get("/session/{session_id}/messages")
async def get_chat_messages(
    request: Request,
    session_id: str,
    user_data: Tuple[str, str, str] = Depends(require_role(["customer", "owner", "admin", "support"]))
):
    """Fetch all messages in a live chat session."""
    _, org_id, _ = user_data
    client = get_supabase()
    
    res = await run_sync_db_call(
        client.table("chat_messages")
        .select("id, sender_type, message, created_at")
        .eq("session_id", session_id)
        .eq("org_id", org_id)
        .order("created_at", desc=False)
        .execute
    )
    return {"messages": res.data or []}
