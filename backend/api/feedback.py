"""
Customer feedback endpoint — closes the feedback loop.
Customers submit a satisfaction score after resolution.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Ticket, CustomerFeedback, TicketStatus

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackCreate(BaseModel):
    score: int = Field(..., ge=1, le=5, description="Satisfaction score 1-5")
    comment: str | None = None


class FeedbackOut(BaseModel):
    ticket_id: str
    score: int
    comment: str | None
    message: str


@router.post("/{ticket_id}", response_model=FeedbackOut)
def submit_feedback(
    ticket_id: UUID,
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
):
    """
    Customer submits satisfaction score after ticket resolution.
    This data feeds into the insight engine and resolution quality tracking.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status not in (TicketStatus.resolved, TicketStatus.escalated):
        raise HTTPException(400, "Feedback can only be submitted for resolved tickets")

    ticket.satisfaction_score = payload.score

    fb = CustomerFeedback(
        ticket_id=ticket_id,
        score=payload.score,
        comment=payload.comment,
    )
    db.add(fb)
    db.commit()

    msg = (
        "Thank you for your feedback!" if payload.score >= 4
        else "Thank you. We're sorry the experience wasn't better — a manager will review this."
    )
    return FeedbackOut(
        ticket_id=str(ticket_id),
        score=payload.score,
        comment=payload.comment,
        message=msg,
    )


@router.get("/stats/summary")
def feedback_summary(db: Session = Depends(get_db)):
    """Aggregate feedback stats for the dashboard."""
    from sqlalchemy import func

    total = db.query(func.count(CustomerFeedback.id)).scalar() or 0
    avg = db.query(func.avg(CustomerFeedback.score)).scalar()
    dist = (
        db.query(CustomerFeedback.score, func.count(CustomerFeedback.id))
        .group_by(CustomerFeedback.score)
        .all()
    )
    agent_avg = db.query(func.avg(Ticket.agent_self_score)).scalar()

    return {
        "total_feedback": total,
        "avg_satisfaction": round(float(avg), 2) if avg else None,
        "avg_agent_self_score": round(float(agent_avg), 2) if agent_avg else None,
        "score_distribution": {str(score): count for score, count in dist},
    }
