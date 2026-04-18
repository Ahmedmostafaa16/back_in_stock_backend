from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import hmac
import hashlib
import logging

from core.deps import get_db
from core.config import require_setting, settings
from models import Data
from services.shopify_auth import normalize_shop_domain
from services.shopify_service import get_inventory_item_id


router = APIRouter(prefix="/notify", tags=["Notify"])
logger = logging.getLogger(__name__)


# -------------------------
# VERIFY SHOPIFY APP PROXY HMAC
# -------------------------
def verify_proxy_request(query_params: dict):
    signature = query_params.get("signature")
    if not signature:
        return False

    # Remove signature
    params = {k: v for k, v in query_params.items() if k != "signature"}

    # Sort and build message
    sorted_params = sorted(params.items())
    message = "".join(f"{k}={v}" for k, v in sorted_params)

    # Compute HMAC
    shopify_secret = require_setting(settings.SHOPIFY_API_SECRET, "SHOPIFY_API_SECRET")
    computed_hmac = hmac.new(
        shopify_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed_hmac, signature)


# -------------------------
# MAIN ENDPOINT
# -------------------------
@router.post("")
async def create_notification(
    request: Request,
    db: Session = Depends(get_db),
):
    # 1) Read query params for Shopify App Proxy signature verification.
    params = dict(request.query_params)
    logger.info("Notify request received", extra={"shop_domain": params.get("shop")})

    # 2) Verify proxy request
    try:
        proxy_is_valid = verify_proxy_request(params)
    except RuntimeError as exc:
        logger.error("Notify request failed during proxy verification: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    if not proxy_is_valid:
        logger.error("Notify request failed: invalid proxy signature", extra={"shop_domain": params.get("shop")})
        raise HTTPException(status_code=403, detail="Invalid proxy signature")

    shop_domain = normalize_shop_domain(params.get("shop"))

    # 3) Extract subscription fields from the JSON body sent by the storefront script.
    try:
        body = await request.json()
    except Exception as exc:
        logger.error("Notify request failed: invalid JSON body: %s", exc, extra={"shop_domain": shop_domain}, exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    variant_id = str(body.get("variant_id") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    phone_number = body.get("phone_number")
    product_url = str(body.get("product_url") or "").strip()
    logger.info(
        "Notify request parsed",
        extra={"shop_domain": shop_domain, "variant_id": variant_id, "email": email},
    )

    # 4) Validate input
    if not variant_id:
        logger.error("Notify request failed: variant_id is required", extra={"shop_domain": shop_domain, "email": email})
        raise HTTPException(status_code=400, detail="variant_id is required")

    if not email:
        logger.error("Notify request failed: email is required", extra={"shop_domain": shop_domain, "variant_id": variant_id})
        raise HTTPException(status_code=400, detail="email is required")

    if not product_url:
        logger.error("Notify request failed: product_url is required", extra={"shop_domain": shop_domain, "variant_id": variant_id, "email": email})
        raise HTTPException(status_code=400, detail="product_url is required")

    # 5) Resolve inventory item (REAL Shopify call)
    try:
        inventory_item_id = get_inventory_item_id(variant_id, shop_domain, db)
    except Exception as e:
        logger.error(
            "Notify request failed resolving inventory item: %s",
            e,
            extra={"shop_domain": shop_domain, "variant_id": variant_id, "email": email},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Shopify error: {str(e)}")
    logger.info(
        "Notify inventory item resolved",
        extra={
            "shop_domain": shop_domain,
            "variant_id": variant_id,
            "email": email,
            "inventory_item_id": inventory_item_id,
        },
    )

    # 6) Dedup check
    existing = db.query(Data).filter(
        Data.shop_domain == shop_domain,
        Data.variant_id == variant_id,
        Data.email == email,
        Data.status == "pending",
    ).first()

    if existing:
        logger.info(
            "Notify subscription already exists",
            extra={"shop_domain": shop_domain, "variant_id": variant_id, "email": email},
        )
        return {"message": "Already subscribed"}

    # 7) Save new subscription
    new_row = Data(
        shop_domain=shop_domain,
        variant_id=variant_id,
        inventory_item_id=inventory_item_id,
        email=email,
        phone_number=phone_number or None,
        product_title=None,
        product_url=product_url,
        status="pending"
    )

    db.add(new_row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.error(
            "Notify subscription insert hit integrity error: %s",
            exc,
            extra={"shop_domain": shop_domain, "variant_id": variant_id, "email": email},
            exc_info=True,
        )
        return {"message": "Already subscribed"}

    logger.info(
        "Notify subscription created",
        extra={
            "shop_domain": shop_domain,
            "variant_id": variant_id,
            "email": email,
            "inventory_item_id": inventory_item_id,
        },
    )
    return {"message": "You will be notified when back in stock"}
