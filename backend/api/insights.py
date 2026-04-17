from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.database import get_db
from services.insights import generate_insights

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/")
def get_insights(db: Session = Depends(get_db)):
    """
    Run the insight engine and return anomalies, patterns, and recommendations.
    This is what makes the system a 'business brain' not just a ticket processor.
    """
    return generate_insights(db)
