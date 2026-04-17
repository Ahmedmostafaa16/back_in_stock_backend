from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from core.config import settings
from core.deps import get_db
from models import Data


router = APIRouter(tags=["Dashboard"])


def verify_admin_token(x_admin_token: str | None = Header(default=None)):
    if not settings.ADMIN_DASHBOARD_TOKEN:
        raise HTTPException(status_code=503, detail="Dashboard admin token is not configured")

    if x_admin_token != settings.ADMIN_DASHBOARD_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid dashboard token")


@router.get("/dashboard", dependencies=[Depends(verify_admin_token)])
def get_dashboard(db: Session = Depends(get_db)):
    total = db.query(Data).count()
    pending = db.query(Data).filter(Data.status == "pending").count()
    sent = db.query(Data).filter(Data.status == "sent").count()

    return {
        "total": total,
        "pending": pending,
        "sent": sent,
    }


@router.get("/subscriptions", dependencies=[Depends(verify_admin_token)])
def get_subscriptions(db: Session = Depends(get_db)):
    subscriptions = db.query(Data).order_by(Data.created_at.desc()).all()

    return [
        {
            "id": subscription.id,
            "email": subscription.email,
            "phone_number": subscription.phone_number,
            "variant_id": subscription.variant_id,
            "status": subscription.status,
            "created_at": subscription.created_at,
        }
        for subscription in subscriptions
    ]
