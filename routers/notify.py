from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import hmac
import hashlib

from core.deps import get_db
from core.config import require_setting, settings
from models import Data
from services.shopify_service import get_inventory_item_id


router = APIRouter(prefix="/notify", tags=["Notify"])


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

    # 2) Verify proxy request
    try:
        proxy_is_valid = verify_proxy_request(params)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not proxy_is_valid:
        raise HTTPException(status_code=403, detail="Invalid proxy signature")

    # 3) Extract subscription fields from the JSON body sent by the storefront script.
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    variant_id = str(body.get("variant_id") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    phone_number = body.get("phone_number")
    product_url = str(body.get("product_url") or "").strip()

    # 4) Validate input
    if not variant_id:
        raise HTTPException(status_code=400, detail="variant_id is required")

    if not email:
        raise HTTPException(status_code=400, detail="email is required")

    if not product_url:
        raise HTTPException(status_code=400, detail="product_url is required")

    # 5) Resolve inventory item (REAL Shopify call)
    try:
        inventory_item_id = get_inventory_item_id(variant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Shopify error: {str(e)}")

    # 6) Dedup check
    existing = db.query(Data).filter(
        Data.variant_id == variant_id,
        Data.email == email,
        Data.status == "pending",
    ).first()

    if existing:
        return {"message": "Already subscribed"}

    # 7) Save new subscription
    new_row = Data(
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
    except IntegrityError:
        db.rollback()
        return {"message": "Already subscribed"}

    return {"message": "You will be notified when back in stock"}
