"""saw-codex-api — REST API for managing Codex sessions on SAW."""

import asyncio
import re

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from . import config
from .auth import UserInfo, get_current_user
from .k8s import (
    Session,
    create_session_cr,
    delete_session_cr,
    get_vm_owner,
    list_user_vms,
)

app = FastAPI(title="saw-codex-api", version="0.2.0")

_SAFE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,18}$")


def _validate_name(name: str) -> str:
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Name must be 1-19 lowercase alphanumeric chars or hyphens, "
            "starting with a letter",
        )
    return name


class SessionResponse(BaseModel):
    name: str
    status: str
    created: str
    owner: str
    ws_url: str | None


class CreateRequest(BaseModel):
    name: str


class CreateResponse(BaseModel):
    name: str
    status: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(user: UserInfo = Depends(get_current_user)):
    sessions = await asyncio.to_thread(list_user_vms, user.sub)
    return [
        SessionResponse(
            name=s.name,
            status=s.status,
            created=s.created,
            owner=s.owner,
            ws_url=s.ws_url,
        )
        for s in sessions
    ]


@app.post("/sessions", response_model=CreateResponse, status_code=202)
async def create_session(
    request: Request,
    body: CreateRequest,
    user: UserInfo = Depends(get_current_user),
):
    name = _validate_name(body.name)

    existing = await asyncio.to_thread(list_user_vms, user.sub)
    if len(existing) >= config.MAX_SESSIONS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=f"Session limit reached ({config.MAX_SESSIONS_PER_USER}). "
            "Delete an existing session first.",
        )

    oidc_token = request.headers.get("authorization", "")[7:]
    ok = await asyncio.to_thread(create_session_cr, name, user.sub, oidc_token)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to create session")
    return CreateResponse(name=name, status="creating")


@app.delete("/sessions/{name}", status_code=204)
async def delete_session(name: str, user: UserInfo = Depends(get_current_user)):
    _validate_name(name)
    owner = await asyncio.to_thread(get_vm_owner, name)
    if owner is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if owner != user.sub:
        raise HTTPException(status_code=403, detail="Not your session")

    ok = await asyncio.to_thread(delete_session_cr, name)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete session")
