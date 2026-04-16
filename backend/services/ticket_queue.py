"""
FIFO ticket processing queue.

A single background worker thread reads from a thread-safe queue and
processes one ticket at a time. Submissions never block the HTTP response —
tickets are enqueued instantly and processed in arrival order.

Guarantees:
  - FIFO ordering
  - Only one agent run at a time (no API rate-limit hammering)
  - No external dependencies (no Redis/Celery)
  - Safe for concurrent HTTP submissions
"""
import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TicketJob:
    ticket_id: str
    ticket_data: dict[str, Any]


class TicketQueue:
    def __init__(self) -> None:
        self._q: queue.Queue[TicketJob] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the single worker thread. Called once at app startup."""
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._run,
            name="ticket-queue-worker",
            daemon=True,
        )
        self._worker.start()
        logger.info("Ticket queue worker started.")

    def stop(self) -> None:
        """Gracefully drain the queue and stop the worker. Called at shutdown."""
        logger.info("Stopping ticket queue worker (draining %d jobs)...", self.qsize())
        self._stop_event.set()
        self._q.put(None)  # sentinel to unblock the worker's get()
        if self._worker:
            self._worker.join(timeout=120)
        logger.info("Ticket queue worker stopped.")

    # ── Public API ───────────────────────────────────────────────────────────

    def enqueue(self, ticket_id: str, ticket_data: dict[str, Any]) -> None:
        """Add a ticket to the back of the FIFO queue. Non-blocking."""
        self._q.put(TicketJob(ticket_id=ticket_id, ticket_data=ticket_data))
        logger.info(
            "Ticket %s enqueued. Queue depth: %d", ticket_id, self.qsize()
        )

    def qsize(self) -> int:
        return self._q.qsize()

    # ── Worker loop ──────────────────────────────────────────────────────────

    def _run(self) -> None:
        from db.database import SessionLocal
        from agents.support_agent import process_ticket

        while not self._stop_event.is_set():
            try:
                job = self._q.get(timeout=2)
            except queue.Empty:
                continue

            if job is None:  # shutdown sentinel
                break

            db = SessionLocal()
            try:
                logger.info(
                    "Processing ticket %s (queue depth after: %d)",
                    job.ticket_id,
                    self.qsize(),
                )
                result = process_ticket(job.ticket_data, db)
                logger.info("Ticket %s done: %s", job.ticket_id, result)
            except Exception as exc:
                logger.error(
                    "Worker error on ticket %s: %s",
                    job.ticket_id,
                    exc,
                    exc_info=True,
                )
                self._mark_failed(db, job.ticket_id, str(exc))
            finally:
                db.close()
                self._q.task_done()

    @staticmethod
    def _mark_failed(db: Any, ticket_id: str, reason: str) -> None:
        from db.models import Ticket, TicketStatus, ActionLog
        try:
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if ticket:
                ticket.status = TicketStatus.failed
                db.add(ActionLog(
                    ticket_id=ticket_id,
                    action_type="agent_error",
                    status="failed",
                    detail=reason,
                ))
                db.commit()
        except Exception as inner:
            logger.error("Failed to mark ticket %s as failed: %s", ticket_id, inner)


# Singleton — imported everywhere
ticket_queue = TicketQueue()
