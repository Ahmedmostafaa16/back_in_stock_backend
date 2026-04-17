try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic.v1 import BaseSettings


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"

    # Shopify
    SHOPIFY_API_SECRET: str | None = None
    SHOPIFY_ACCESS_TOKEN: str | None = None
    SHOP_DOMAIN: str | None = None
    SHOPIFY_ONLINE_LOCATION_ID: str | None = None

    # Database
    DATABASE_URL: str | None = None

    # Dashboard
    ADMIN_DASHBOARD_TOKEN: str | None = None

    # Email
    EMAIL_HOST: str | None = None
    EMAIL_PORT: int | None = None
    EMAIL_USER: str | None = None
    EMAIL_PASSWORD: str | None = None
    RESEND_API_KEY: str | None = None
    RESEND_FROM_EMAIL: str = "Back in Stock <onboarding@resend.dev>"
    RESEND_API_URL: str = "https://api.resend.com/emails"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()


def require_setting(value: str | None, name: str) -> str:
    if not value:
        raise RuntimeError(f"{name} is required")

    return value
