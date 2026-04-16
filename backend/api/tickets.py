import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Ticket, TicketStatus, UrgencyLevel
from api.schemas import TicketCreate, TicketOut, TicketProcessResult, StatsOut
from services.ticket_queue import ticket_queue

router = APIRouter(prefix="/tickets", tags=["tickets"])
logger = logging.getLogger(__name__)


@router.post("/", response_model=TicketProcessResult, status_code=202)
def ingest_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
):
    """
    Ingest a new support ticket and add it to the FIFO processing queue.
    Returns 202 immediately; the single queue worker processes tickets in order.
    """
    ticket = Ticket(
        customer_name=payload.customer_name,
        customer_email=payload.customer_email,
        subject=payload.subject,
        message=payload.message,
        source=payload.source,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    ticket_data = {
        "id": str(ticket.id),
        "customer_name": ticket.customer_name,
        "customer_email": ticket.customer_email,
        "subject": ticket.subject,
        "message": ticket.message,
    }

    ticket_queue.enqueue(str(ticket.id), ticket_data)

    queue_depth = ticket_queue.qsize()
    position_msg = (
        "You are next in line."
        if queue_depth <= 1
        else f"Position in queue: {queue_depth}."
    )

    return TicketProcessResult(
        ticket_id=str(ticket.id),
        success=True,
        summary=f"Ticket queued for processing. {position_msg}",
    )


@router.post("/webhook", response_model=TicketProcessResult, status_code=202)
def n8n_webhook(
    payload: TicketCreate,
    db: Session = Depends(get_db),
):
    """n8n-compatible webhook endpoint — same FIFO queue as POST /tickets/."""
    payload.source = "n8n_webhook"
    return ingest_ticket(payload, db)


@router.get("/queue/depth")
def queue_depth():
    """Returns how many tickets are currently waiting to be processed."""
    return {"queued": ticket_queue.qsize()}


@router.get("/", response_model=list[TicketOut])
def list_tickets(
    status: str | None = Query(default=None),
    urgency: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: Session = Depends(get_db),
):
    query = db.query(Ticket)
    if status:
        try:
            query = query.filter(Ticket.status == TicketStatus(status))
        except ValueError:
            raise HTTPException(400, f"Invalid status '{status}'")
    if urgency:
        try:
            query = query.filter(Ticket.urgency == UrgencyLevel(urgency))
        except ValueError:
            raise HTTPException(400, f"Invalid urgency '{urgency}'")

    return (
        query.order_by(Ticket.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/stats", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)):
    from sqlalchemy import func

    def count(status):
        return db.query(func.count(Ticket.id)).filter(Ticket.status == TicketStatus(status)).scalar() or 0

    critical_open = (
        db.query(func.count(Ticket.id))
        .filter(
            Ticket.urgency == UrgencyLevel.critical,
            Ticket.status.notin_([TicketStatus.resolved]),
        )
        .scalar() or 0
    )

    return StatsOut(
        total=db.query(func.count(Ticket.id)).scalar() or 0,
        pending=count("pending"),
        processing=count("processing"),
        resolved=count("resolved"),
        escalated=count("escalated"),
        failed=count("failed"),
        critical_open=critical_open,
    )


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: UUID, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: UUID, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    db.delete(ticket)
    db.commit()
