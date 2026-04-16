from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import SystemLog, ActionLog
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

router = APIRouter(prefix="/logs", tags=["logs"])


class SystemLogOut(BaseModel):
    id: int
    level: str
    component: str
    message: str
    extra: Optional[dict] = None
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ActionLogOut(BaseModel):
    id: int
    ticket_id: str
    action_type: str
    status: str
    detail: Optional[str]
    extra: Optional[dict] = None
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


@router.get("/system", response_model=list[SystemLogOut])
def get_system_logs(
    level: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(SystemLog)
    if level:
        query = query.filter(SystemLog.level == level.upper())
    return query.order_by(SystemLog.created_at.desc()).limit(limit).all()


@router.get("/actions", response_model=list[ActionLogOut])
def get_action_logs(
    action_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(ActionLog)
    if action_type:
        query = query.filter(ActionLog.action_type == action_type)
    if status:
        query = query.filter(ActionLog.status == status)
    return query.order_by(ActionLog.created_at.desc()).limit(limit).all()
