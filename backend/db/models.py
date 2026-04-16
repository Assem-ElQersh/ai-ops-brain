import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Text, DateTime, Enum as SAEnum,
    Integer, Boolean, ForeignKey, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.database import Base


class UrgencyLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TicketStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    resolved = "resolved"
    escalated = "escalated"
    failed = "failed"


class TicketCategory(str, enum.Enum):
    billing = "billing"
    technical = "technical"
    service_quality = "service_quality"
    scheduling = "scheduling"
    cancellation = "cancellation"
    feedback = "feedback"
    other = "other"


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_name = Column(String(255), nullable=False)
    customer_email = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    message = Column(Text, nullable=False)
    source = Column(String(50), default="webhook")

    urgency = Column(SAEnum(UrgencyLevel), nullable=True)
    category = Column(SAEnum(TicketCategory), nullable=True)
    status = Column(SAEnum(TicketStatus), default=TicketStatus.pending, nullable=False)

    ai_summary = Column(Text, nullable=True)
    ai_response = Column(Text, nullable=True)
    ai_reasoning = Column(Text, nullable=True)

    escalated = Column(Boolean, default=False)
    auto_replied = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    actions = relationship("ActionLog", back_populates="ticket", cascade="all, delete-orphan")


class ActionLog(Base):
    __tablename__ = "action_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)

    action_type = Column(String(100), nullable=False)
    status = Column(String(50), default="success")
    detail = Column(Text, nullable=True)
    extra = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("Ticket", back_populates="actions")


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(20), nullable=False)
    component = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    extra = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
