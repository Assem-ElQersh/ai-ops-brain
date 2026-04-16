from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class TicketCreate(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_email: EmailStr
    subject: str = Field(..., min_length=1, max_length=500)
    message: str = Field(..., min_length=10)
    source: str = Field(default="api")


class ActionLogOut(BaseModel):
    id: int
    action_type: str
    status: str
    detail: Optional[str]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class TicketOut(BaseModel):
    id: UUID
    customer_name: str
    customer_email: str
    subject: str
    message: str
    source: str
    urgency: Optional[str]
    category: Optional[str]
    status: str
    ai_summary: Optional[str]
    ai_response: Optional[str]
    ai_reasoning: Optional[str]
    escalated: bool
    auto_replied: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    resolved_at: Optional[datetime]
    actions: list[ActionLogOut] = []

    model_config = {"from_attributes": True}


class TicketProcessResult(BaseModel):
    ticket_id: str
    success: bool
    summary: Optional[str] = None
    steps: Optional[int] = None
    error: Optional[str] = None


class StatsOut(BaseModel):
    total: int
    pending: int
    processing: int
    resolved: int
    escalated: int
    failed: int
    critical_open: int
