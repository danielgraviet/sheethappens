"""Google OAuth + Canvas setup endpoints for multi-tenant onboarding."""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

from app import crypto, user_repo
from app.config import settings
from app.sheets_client import UserSheetsClient, create_user_spreadsheet

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Session helpers ───────────────────────────────────────────────────────────

def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret_key)


def create_session_token(user_id: str) -> str:
    return _signer().dumps({"uid": user_id}, salt="session-v1")


def decode_session_token(token: str) -> str | None:
    try:
        data = _signer().loads(token, salt="session-v1", max_age=86400 * 30)
        return data["uid"]
    except (BadSignature, SignatureExpired, KeyError):
        return None


def generate_oauth_state() -> str:
    return _signer().dumps("oauth", salt="google-state")


def verify_oauth_state(state: str) -> bool:
    try:
        _signer().loads(state, salt="google-state", max_age=600)
        return True
    except (BadSignature, SignatureExpired):
        return False


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _generate_code_verifier() -> str:
    return secrets.token_urlsafe(96)


def _compute_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _sign_pkce(verifier: str) -> str:
    return _signer().dumps(verifier, salt="pkce-v1")


def _unsign_pkce(signed: str) -> str | None:
    try:
        return _signer().loads(signed, salt="pkce-v1", max_age=600)
    except (BadSignature, SignatureExpired):
        return None


# ── Dependency: current user ──────────────────────────────────────────────────

async def require_user(ohsheet_session: Annotated[str | None, Cookie()] = None) -> dict:
    if not ohsheet_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = decode_session_token(ohsheet_session)
    if not user_id:
        raise HTTPException(status_code=401, detail="Session expired")
    user = await user_repo.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _oauth_flow(state: str | None = None) -> Flow:
    client_config = {
        "web": {
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "redirect_uris": [settings.google_oauth_redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    from app.sheets_client import OAUTH_SCOPES
    flow = Flow.from_client_config(
        client_config,
        scopes=OAUTH_SCOPES,
        redirect_uri=settings.google_oauth_redirect_uri,
        state=state,
    )
    return flow


# ── Google OAuth ──────────────────────────────────────────────────────────────

@router.get("/auth/google/start")
async def google_start() -> RedirectResponse:
    state = generate_oauth_state()
    code_verifier = _generate_code_verifier()
    flow = _oauth_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
        include_granted_scopes="true",
        code_challenge=_compute_code_challenge(code_verifier),
        code_challenge_method="S256",
    )
    response = RedirectResponse(auth_url)
    response.set_cookie(
        "ohsheet_pkce",
        _sign_pkce(code_verifier),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600,
    )
    return response


@router.get("/auth/google/callback")
async def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    ohsheet_pkce: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    setup_url = f"{settings.app_base_url.rstrip('/')}/setup"

    if error or not code or not state:
        logger.warning("Google OAuth error: %s", error)
        return RedirectResponse(f"{setup_url}?error=oauth_denied")

    if not verify_oauth_state(state):
        logger.warning("Invalid OAuth state parameter")
        return RedirectResponse(f"{setup_url}?error=invalid_state")

    code_verifier = _unsign_pkce(ohsheet_pkce) if ohsheet_pkce else None
    try:
        flow = _oauth_flow(state=state)
        flow.fetch_token(code=code, code_verifier=code_verifier)
        creds = flow.credentials
    except Exception as exc:
        logger.error("Token exchange failed: %s", exc)
        return RedirectResponse(f"{setup_url}?error=token_exchange")

    # Fetch user info
    try:
        resp = httpx.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=10,
        )
        resp.raise_for_status()
        info = resp.json()
    except Exception as exc:
        logger.error("Userinfo fetch failed: %s", exc)
        return RedirectResponse(f"{setup_url}?error=userinfo")

    email = info.get("email", "")
    name = info.get("name", "") or info.get("given_name", "") or email
    google_sub = info.get("sub", "")

    # Upsert user
    user = await user_repo.upsert_user(email, name)
    user_id = str(user["id"])

    # Encrypt tokens
    access_enc = crypto.encrypt(creds.token)
    refresh_enc = crypto.encrypt(creds.refresh_token) if creds.refresh_token else ""
    expiry = creds.expiry  # datetime or None

    # Check if they already have a spreadsheet
    existing_ga = await user_repo.get_google_account(user_id)
    spreadsheet_id = existing_ga["spreadsheet_id"] if existing_ga else None

    # Save Google account
    await user_repo.upsert_google_account(
        user_id=user_id,
        google_sub=google_sub,
        email=email,
        access_token_encrypted=access_enc,
        refresh_token_encrypted=refresh_enc,
        token_expires_at=expiry,
        spreadsheet_id=spreadsheet_id,
    )

    # Auto-create spreadsheet on first connect
    if not spreadsheet_id:
        try:
            sheet_id, _ = create_user_spreadsheet(
                access_token=creds.token,
                refresh_token=creds.refresh_token or "",
                token_expires_at=expiry,
            )
            await user_repo.save_spreadsheet_id(user_id, sheet_id)
            # Apply formatting to the new sheet
            client = UserSheetsClient(
                spreadsheet_id=sheet_id,
                access_token=creds.token,
                refresh_token=creds.refresh_token or "",
                token_expires_at=expiry,
            )
            client._ensure_headers()
        except Exception as exc:
            logger.error("Failed to create spreadsheet for user %s: %s", user_id, exc)

    response = RedirectResponse(f"{setup_url}?connected=google")
    session_token = create_session_token(user_id)
    response.set_cookie(
        "ohsheet_session",
        session_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400 * 30,
    )
    return response


@router.post("/auth/google/disconnect")
async def google_disconnect(
    ohsheet_session: Annotated[str | None, Cookie()] = None,
) -> dict:
    user = await require_user(ohsheet_session)
    await user_repo.delete_google_account(str(user["id"]))
    return {"status": "ok"}


# ── Canvas Setup ──────────────────────────────────────────────────────────────

class CanvasSetupRequest(BaseModel):
    canvas_token: str
    canvas_domain: str


@router.post("/api/setup/canvas")
async def setup_canvas(
    payload: CanvasSetupRequest,
    ohsheet_session: Annotated[str | None, Cookie()] = None,
) -> dict:
    user = await require_user(ohsheet_session)

    # Quick sanity-check: verify the token works
    from app.canvas_client import CanvasClient, CanvasAuthError
    try:
        CanvasClient(token=payload.canvas_token, domain=payload.canvas_domain)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Canvas config: {exc}")

    encrypted = crypto.encrypt(payload.canvas_token)
    await user_repo.save_canvas_credentials(
        str(user["id"]), encrypted, payload.canvas_domain
    )
    return {"status": "ok"}


# ── Current user status ───────────────────────────────────────────────────────

@router.get("/api/me")
async def get_me(ohsheet_session: Annotated[str | None, Cookie()] = None) -> dict:
    if not ohsheet_session:
        return {"authenticated": False}
    user_id = decode_session_token(ohsheet_session)
    if not user_id:
        return {"authenticated": False}
    user = await user_repo.get_user_by_id(user_id)
    if not user:
        return {"authenticated": False}

    ga = await user_repo.get_google_account(user_id)

    return {
        "authenticated": True,
        "user_id": user_id,
        "email": user["email"],
        "name": user["name"],
        "sync_token": user["sync_token"],
        "canvas_connected": bool(user.get("canvas_token_encrypted")),
        "canvas_domain": user.get("canvas_domain") or "",
        "google_connected": ga is not None,
        "google_email": ga["email"] if ga else None,
        "spreadsheet_id": ga["spreadsheet_id"] if ga else None,
    }


@router.post("/auth/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie("ohsheet_session")
    return {"status": "ok"}


# ── Bookmarklet script ────────────────────────────────────────────────────────

@router.get("/api/bookmarklet/ls")
async def get_ls_bookmarklet(ohsheet_session: Annotated[str | None, Cookie()] = None) -> dict:
    user = await require_user(ohsheet_session)
    token = user["sync_token"]
    api_url = f"{settings.app_base_url.rstrip('/')}/api/sync/learning-suite"
    # Return the JS source so the setup page can render it as a bookmarklet href
    js = (
        f"javascript:(function(){{"
        f"var token='{token}';"
        f"var url='{api_url}';"
        f"var courses=[];"
        f"document.querySelectorAll('.course-info').forEach(function(c){{"
        f"var title=(c.querySelector('.course-title')||{{}}).innerText||'Unknown';"
        f"var assignments=[];"
        f"c.querySelectorAll('.assignment-row').forEach(function(a){{"
        f"assignments.push({{id:a.dataset.id,name:(a.querySelector('.title')||{{}}).innerText||'',dueDate:(a.dataset.due||'')}});"
        f"}});"
        f"if(assignments.length)courses.push({{title:title,assignments:assignments}});"
        f"}});"
        f"if(!courses.length){{alert('OhSheet: No assignments found on this page.');return;}}"
        f"fetch(url,{{method:'POST',headers:{{'Content-Type':'application/json'}},"
        f"body:JSON.stringify({{token:token,courses:courses,page_url:location.href}})}}).then(function(r){{return r.json()}}).then(function(d){{alert('OhSheet: '+d.synced+' synced, '+d.skipped+' skipped')}}).catch(function(e){{alert('OhSheet error: '+e)}});"
        f"}})();"
    )
    return {"js": js}


@router.get("/api/bookmarklet/gas")
async def get_gas_script(ohsheet_session: Annotated[str | None, Cookie()] = None) -> dict:
    user = await require_user(ohsheet_session)
    token = user["sync_token"]
    sync_url = f"{settings.app_base_url.rstrip('/')}/api/sync/canvas"
    script = f"""// OhSheet — Google Apps Script
// Install: Extensions → Apps Script → paste this → Save → reload the sheet.
//
// When you run the script for the first time Google will show an
// "app not verified" warning — this is normal for private scripts.
// Click "Advanced" → "Go to OhSheet (unsafe)" to continue.

// @OnlyCurrentDoc

var SYNC_URL = "{sync_url}";
var SYNC_TOKEN = "{token}";

function onOpen() {{
  SpreadsheetApp.getUi()
    .createMenu("OhSheet")
    .addItem("Sync — This week (7 days)",     "syncWeek")
    .addItem("Sync — Next 2 weeks (14 days)", "syncTwoWeeks")
    .addItem("Sync — Next 30 days",           "syncMonth")
    .addSeparator()
    .addItem("Sync — Custom days...",          "syncCustom")
    .addToUi();
}}

function syncWeek()     {{ runSync(7);  }}
function syncTwoWeeks() {{ runSync(14); }}
function syncMonth()    {{ runSync(30); }}

function syncCustom() {{
  var ui = SpreadsheetApp.getUi();
  var response = ui.prompt(
    "OhSheet — Custom sync",
    "How many days ahead should be fetched? (1–365)",
    ui.ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() !== ui.Button.OK) return;
  var days = parseInt(response.getResponseText(), 10);
  if (isNaN(days) || days < 1 || days > 365) {{
    ui.alert("Invalid input. Please enter a number between 1 and 365.");
    return;
  }}
  runSync(days);
}}

function runSync(days) {{
  var sheet = SpreadsheetApp.getActiveSpreadsheet();
  sheet.toast("Syncing assignments for the next " + days + " day(s)...", "OhSheet", 5);
  try {{
    var response = UrlFetchApp.fetch(
      SYNC_URL + "?token=" + SYNC_TOKEN + "&days=" + days,
      {{ method: "get", muteHttpExceptions: true }}
    );
    var code = response.getResponseCode();
    if (code !== 200) {{
      sheet.toast("Sync failed (HTTP " + code + ").", "OhSheet", 8);
      return;
    }}
    var result = JSON.parse(response.getContentText());
    var msg = "Done! Fetched: " + result.total_fetched +
              " | New: " + result.newly_inserted +
              " | Skipped: " + result.skipped_duplicates +
              (result.failures > 0 ? " | Failures: " + result.failures : "");
    sheet.toast(msg, "OhSheet", 10);
  }} catch (e) {{
    sheet.toast("Error: " + e.message, "OhSheet", 8);
  }}
}}
"""
    return {"script": script}
