import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from core.config import require_setting, settings
from core.deps import get_db
from models import Data
from services.email_service import send_back_in_stock_email
from services.shopify_auth import get_shop_token, normalize_shop_domain


router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger(__name__)


def verify_webhook(raw_body: bytes, shopify_hmac: str):
    shopify_secret = require_setting(settings.SHOPIFY_API_SECRET, "SHOPIFY_API_SECRET")

    computed_hmac = base64.b64encode(
        hmac.new(
            shopify_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).digest()
    ).decode().strip()

    shopify_hmac = shopify_hmac.strip()

    return hmac.compare_digest(computed_hmac, shopify_hmac)


@router.post("/inventory")
async def inventory_update(
    request: Request,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()

    shopify_hmac = request.headers.get("X-Shopify-Hmac-Sha256")
    if not shopify_hmac:
        logger.error("Inventory webhook failed: missing HMAC")
        raise HTTPException(status_code=400, detail="Missing HMAC")

    try:
        webhook_is_valid = verify_webhook(raw_body, shopify_hmac)
    except RuntimeError as exc:
        logger.error("Inventory webhook failed during HMAC verification: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    if not webhook_is_valid:
        logger.error("Inventory webhook failed: invalid HMAC")
        raise HTTPException(status_code=403, detail="Invalid HMAC")

    shop_domain = normalize_shop_domain(request.headers.get("X-Shopify-Shop-Domain"))
    logger.info("Inventory webhook received", extra={"shop_domain": shop_domain})
    get_shop_token(shop_domain, db)

    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        logger.error("Inventory webhook failed: invalid JSON body: %s", exc, extra={"shop_domain": shop_domain}, exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    inventory_item_id = data.get("inventory_item_id")
    location_id = data.get("location_id")
    available = data.get("available")
    print("WEBHOOK RECEIVED")
    print("Shop:", request.headers.get("X-Shopify-Shop-Domain"))
    print("Inventory Item ID:", data.get("inventory_item_id"))
    print("Location ID:", data.get("location_id"))
    print("Available:", data.get("available"))
    logger.info(
        "Inventory webhook payload parsed",
        extra={
            "shop_domain": shop_domain,
            "inventory_item_id": inventory_item_id,
            "location_id": location_id,
            "available": available,
        },
    )

    if not inventory_item_id or available is None or not location_id:
        logger.info(
            "Inventory webhook ignored: missing required payload fields",
            extra={
                "shop_domain": shop_domain,
                "inventory_item_id": inventory_item_id,
                "location_id": location_id,
                "available": available,
            },
        )
        return {"status": "ignored"}

    inventory_item_id = str(inventory_item_id)
    location_id = str(location_id)
    online_location_id = require_setting(
        settings.SHOPIFY_ONLINE_LOCATION_ID,
        "SHOPIFY_ONLINE_LOCATION_ID",
    )

    if location_id != online_location_id:
        logger.info(
            "Inventory webhook ignored: wrong location",
            extra={
                "shop_domain": shop_domain,
                "inventory_item_id": inventory_item_id,
                "location_id": location_id,
                "available": available,
            },
        )
        return {"status": "ignored - wrong location"}

    if available <= 0:
        logger.info(
            "Inventory webhook ignored: no stock",
            extra={
                "shop_domain": shop_domain,
                "inventory_item_id": inventory_item_id,
                "location_id": location_id,
                "available": available,
            },
        )
        return {"status": "ignored - no stock"}

    subscriptions = db.query(Data).filter(
        Data.shop_domain == shop_domain,
        Data.inventory_item_id == inventory_item_id,
        Data.status == "pending",
    ).all()

    if not subscriptions:
        logger.info(
            "Inventory webhook processed: no subscribers",
            extra={
                "shop_domain": shop_domain,
                "inventory_item_id": inventory_item_id,
                "location_id": location_id,
                "available": available,
                "subscribers_notified": 0,
            },
        )
        return {"status": "no subscribers"}

    subscribers_notified = 0
    for subscription in subscriptions:
        try:
            if not subscription.email:
                raise RuntimeError("subscription has no email")

            send_back_in_stock_email(
                to_email=subscription.email,
                product_url=subscription.product_url,
                shop_domain=shop_domain,
            )
            subscription.status = "sent"
            subscription.sent_at = datetime.now(timezone.utc)
            subscribers_notified += 1
        except Exception:
            logger.error(
                "Inventory webhook failed sending subscriber email",
                extra={
                    "shop_domain": shop_domain,
                    "inventory_item_id": inventory_item_id,
                    "subscription_id": subscription.id,
                    "email": subscription.email,
                },
                exc_info=True,
            )
            subscription.status = "failed"

    db.commit()
    logger.info(
        "Inventory webhook processed",
        extra={
            "shop_domain": shop_domain,
            "inventory_item_id": inventory_item_id,
            "location_id": location_id,
            "available": available,
            "subscribers_notified": subscribers_notified,
        },
    )

    return {"status": "processed"}
