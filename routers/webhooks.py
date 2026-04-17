import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from core.config import require_setting, settings
from core.deps import get_db
from models import Data
from services.email_service import send_back_in_stock_email


router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def verify_webhook(raw_body: bytes, shopify_hmac: str):
    shopify_secret = require_setting(settings.SHOPIFY_API_SECRET, "SHOPIFY_API_SECRET")
    computed_hmac = base64.b64encode(
        hmac.new(
            shopify_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).digest()
    ).decode()

    return hmac.compare_digest(computed_hmac, shopify_hmac)


@router.post("/inventory")
async def inventory_update(
    request: Request,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()

    shopify_hmac = request.headers.get("X-Shopify-Hmac-Sha256")
    if not shopify_hmac:
        raise HTTPException(status_code=400, detail="Missing HMAC")

    try:
        webhook_is_valid = verify_webhook(raw_body, shopify_hmac)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not webhook_is_valid:
        raise HTTPException(status_code=403, detail="Invalid HMAC")

    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    inventory_item_id = data.get("inventory_item_id")
    location_id = data.get("location_id")
    available = data.get("available")

    if not inventory_item_id or available is None or not location_id:
        return {"status": "ignored"}

    inventory_item_id = str(inventory_item_id)
    location_id = str(location_id)
    online_location_id = require_setting(
        settings.SHOPIFY_ONLINE_LOCATION_ID,
        "SHOPIFY_ONLINE_LOCATION_ID",
    )

    if location_id != online_location_id:
        return {"status": "ignored - wrong location"}

    if available <= 0:
        return {"status": "ignored - no stock"}

    subscriptions = db.query(Data).filter(
        Data.inventory_item_id == inventory_item_id,
        Data.status == "pending",
    ).all()

    if not subscriptions:
        return {"status": "no subscribers"}

    for subscription in subscriptions:
        try:
            if not subscription.email:
                raise RuntimeError("subscription has no email")

            send_back_in_stock_email(
                to_email=subscription.email,
                product_url=subscription.product_url,
                shop_domain=settings.SHOP_DOMAIN,
            )
            subscription.status = "sent"
            subscription.sent_at = datetime.now(timezone.utc)
        except Exception:
            subscription.status = "failed"

    db.commit()

    return {"status": "processed"}
