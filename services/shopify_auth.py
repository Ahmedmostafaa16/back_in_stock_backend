import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Shop


SHOP_DOMAIN_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com$")


def normalize_shop_domain(shop_domain: str | None) -> str:
    shop = (shop_domain or "").strip().lower()
    if not SHOP_DOMAIN_PATTERN.fullmatch(shop):
        raise HTTPException(status_code=400, detail="Invalid shop domain")

    return shop


def get_shop_token(shop_domain: str, db: Session) -> str:
    shop = normalize_shop_domain(shop_domain)
    installed_shop = db.query(Shop).filter(Shop.shop_domain == shop).first()

    if not installed_shop:
        raise HTTPException(status_code=403, detail="Shop is not installed")

    return installed_shop.access_token
