import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_db
from .models import User

router = APIRouter(tags=["auth"])

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_SCOPES = "openid email profile"
_JWT_ALGORITHM = "HS256"
_SESSION_DAYS = 30


def _redirect_uri() -> str:
    return f"{settings.backend_url}/auth/google/callback"


def _make_state() -> str:
    payload = {
        "nonce": secrets.token_urlsafe(16),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def _verify_state(state: str) -> bool:
    try:
        jwt.decode(state, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
        return True
    except JWTError:
        return False


def _mint_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=_SESSION_DAYS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "__session",
        token,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=_SESSION_DAYS * 24 * 3600,
        path="/",
    )


# --------------------------------------------------------------------------- #
# Routes                                                                        #
# --------------------------------------------------------------------------- #

@router.get("/auth/google")
async def login_google():
    state = _make_state()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": _SCOPES,
        "state": state,
        "access_type": "online",
    }
    return RedirectResponse(f"{_GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/auth/google/callback")
async def auth_google_callback(
    request: Request,
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    if not _verify_state(state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(_GOOGLE_TOKEN_URL, data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri(),
        })
        token_resp.raise_for_status()
        tokens = token_resp.json()

        userinfo_resp = await client.get(
            _GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        userinfo_resp.raise_for_status()
        userinfo = userinfo_resp.json()

    google_id: str = userinfo["sub"]
    email: str = userinfo["email"]
    name: str | None = userinfo.get("name")

    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()
    if user:
        user.email = email
        user.name = name
    else:
        user = User(google_id=google_id, email=email, name=name)
        db.add(user)
    await db.commit()
    await db.refresh(user)

    token = _mint_jwt(str(user.id))
    response = RedirectResponse(settings.frontend_url, status_code=302)
    _set_session_cookie(response, token)
    return response


@router.post("/auth/logout")
async def logout():
    response = Response()
    response.delete_cookie("__session", path="/")
    return response


# --------------------------------------------------------------------------- #
# Dependency                                                                    #
# --------------------------------------------------------------------------- #

async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    token = request.cookies.get("__session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
        user_id: str = payload["sub"]
    except (JWTError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid session")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
