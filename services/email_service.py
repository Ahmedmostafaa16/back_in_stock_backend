import requests

from core.config import require_setting, settings


def send_back_in_stock_email(
    to_email: str,
    product_url: str,
    shop_domain: str | None = None,
):
    api_key = require_setting(settings.RESEND_API_KEY, "RESEND_API_KEY")

    shop_line = f" for {shop_domain}" if shop_domain else ""

    response = requests.post(
        settings.RESEND_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": settings.RESEND_FROM_EMAIL,
            "to": [to_email],
            "subject": "Your item is back in stock",
            "text": (
                f"Good news. The item you asked about is back in stock{shop_line}.\n\n"
                f"Shop now: {product_url}"
            ),
        },
        timeout=10,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"Resend error: {response.text}")
