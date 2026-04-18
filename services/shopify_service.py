import requests
from sqlalchemy.orm import Session

from services.shopify_auth import get_shop_token, normalize_shop_domain


SHOPIFY_API_VERSION = "2026-04"
REQUEST_TIMEOUT_SECONDS = 10


def get_inventory_item_id(variant_id: str, shop_domain: str, db: Session) -> str:
    shop_domain = normalize_shop_domain(shop_domain)
    access_token = get_shop_token(shop_domain, db)
    url = f"https://{shop_domain}/admin/api/{SHOPIFY_API_VERSION}/variants/{variant_id}.json"

    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise RuntimeError(f"Shopify API request failed: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"Shopify API error {response.status_code}: {response.text}"
        )

    try:
        data = response.json()
        return str(data["variant"]["inventory_item_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Shopify API response did not include inventory_item_id") from exc
