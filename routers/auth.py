import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from core.config import require_setting, settings
from core.deps import get_db
from models import Shop
from services.shopify_auth import normalize_shop_domain


router = APIRouter(prefix="/auth", tags=["Auth"])
REQUEST_TIMEOUT_SECONDS = 10
logger = logging.getLogger(__name__)


def get_redirect_uri() -> str:
    if settings.SHOPIFY_OAUTH_SUCCESS_URL and settings.SHOPIFY_APP_URL:
        return f"{settings.SHOPIFY_APP_URL.rstrip('/')}/auth/callback"

    app_url = require_setting(settings.SHOPIFY_APP_URL, "SHOPIFY_APP_URL")
    return f"{app_url.rstrip('/')}/auth/callback"


def verify_oauth_hmac(query_params: dict) -> bool:
    received_hmac = query_params.get("hmac")
    if not received_hmac:
        return False

    secret = require_setting(settings.SHOPIFY_API_SECRET, "SHOPIFY_API_SECRET")
    params = {
        key: value
        for key, value in query_params.items()
        if key not in {"hmac", "signature"}
    }
    message = urlencode(sorted(params.items()))
    computed_hmac = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed_hmac, received_hmac)


@router.get("/install")
def install(shop: str = Query(...)):
    shop_domain = normalize_shop_domain(shop)
    client_id = require_setting(settings.SHOPIFY_API_KEY, "SHOPIFY_API_KEY")
    redirect_uri = get_redirect_uri()
    state = secrets.token_urlsafe(32)

    oauth_params = {
        'client_id': client_id,
        'scope': settings.SHOPIFY_SCOPES,
        'redirect_uri': redirect_uri,
        'state': state,
    }
    oauth_url = f"https://{shop_domain}/admin/oauth/authorize?{urlencode(oauth_params)}"
    logger.info("OAuth install started", extra={"shop_domain": shop_domain, "redirect_url": oauth_url})

    response = RedirectResponse(oauth_url)
    response.set_cookie(
        key="shopify_oauth_state",
        value=state,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600,
    )
    return response


@router.get("/callback")
def callback(request: Request, db: Session = Depends(get_db)):
    params = dict(request.query_params)
    shop_domain = normalize_shop_domain(params.get("shop"))
    logger.info("OAuth callback received", extra={"shop_domain": shop_domain})
    code = params.get("code")
    state = params.get("state")
    saved_state = request.cookies.get("shopify_oauth_state")

    if not code:
        logger.error("OAuth callback failed: missing code", extra={"shop_domain": shop_domain})
        raise HTTPException(status_code=400, detail="Missing OAuth code")

    if not state or not saved_state or not hmac.compare_digest(state, saved_state):
        logger.error("OAuth callback failed: invalid state", extra={"shop_domain": shop_domain})
        raise HTTPException(status_code=403, detail="Invalid OAuth state")

    try:
        oauth_is_valid = verify_oauth_hmac(params)
    except RuntimeError as exc:
        logger.error("OAuth callback failed: %s", exc, extra={"shop_domain": shop_domain}, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    if not oauth_is_valid:
        logger.error("OAuth callback failed: invalid HMAC", extra={"shop_domain": shop_domain})
        raise HTTPException(status_code=403, detail="Invalid OAuth HMAC")

    client_id = require_setting(settings.SHOPIFY_API_KEY, "SHOPIFY_API_KEY")
    client_secret = require_setting(settings.SHOPIFY_API_SECRET, "SHOPIFY_API_SECRET")
    token_url = f"https://{shop_domain}/admin/oauth/access_token"

    try:
        token_response = requests.post(
            token_url,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.error("OAuth token exchange failed: %s", exc, extra={"shop_domain": shop_domain}, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Shopify token exchange failed: {exc}")

    if token_response.status_code >= 400:
        logger.error(
            "OAuth token exchange failed with Shopify response",
            extra={"shop_domain": shop_domain, "status_code": token_response.status_code},
        )
        raise HTTPException(
            status_code=502,
            detail=f"Shopify token exchange failed: {token_response.text}",
        )

    access_token = token_response.json().get("access_token")
    if not access_token:
        logger.error("OAuth callback failed: missing access token", extra={"shop_domain": shop_domain})
        raise HTTPException(status_code=502, detail="Shopify did not return an access token")

    installed_shop = db.query(Shop).filter(Shop.shop_domain == shop_domain).first()
    if installed_shop:
        installed_shop.access_token = access_token
        installed_shop.installed_at = datetime.now(timezone.utc)
    else:
        db.add(
            Shop(
                shop_domain=shop_domain,
                access_token=access_token,
            )
        )

    db.commit()
    logger.info("OAuth callback succeeded; token saved", extra={"shop_domain": shop_domain})

    success_url = settings.SHOPIFY_OAUTH_SUCCESS_URL or f"https://{shop_domain}/admin/apps"
    response = RedirectResponse(success_url)
    response.delete_cookie("shopify_oauth_state")
    return response
