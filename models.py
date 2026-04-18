from sqlalchemy import Column, String, DateTime, Integer, UniqueConstraint
from sqlalchemy.sql import func
from database import Base


class Shop(Base):
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    shop_domain = Column(String, unique=True, index=True, nullable=False)
    access_token = Column(String, nullable=False)
    installed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Data(Base):
    __tablename__ = "data"

    id = Column(Integer, primary_key=True, index=True)

    # Shop
    shop_domain = Column(String, index=True, nullable=False)

    # Shopify identifiers
    variant_id = Column(String, nullable=False)
    inventory_item_id = Column(String, index=True, nullable=False)

    # Customer
    email = Column(String, nullable=False, index=True)
    phone_number = Column(String, nullable=True)

    # Product info
    product_title = Column(String, nullable=True)
    product_url = Column(String, nullable=False)

    # Status: pending / sent / failed
    status = Column(String, default="pending", index=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sent_at = Column(DateTime(timezone=True), nullable=True)

    # Prevent duplicate subscriptions
    __table_args__ = (
        UniqueConstraint('shop_domain', 'variant_id', 'email', name='uq_subscription_email'),
        UniqueConstraint('shop_domain', 'variant_id', 'phone_number', name='uq_subscription'),
    )
    
