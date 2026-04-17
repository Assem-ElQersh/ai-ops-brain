import logging
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from db.database import init_db
from api.tickets import router as tickets_router
from api.logs import router as logs_router
from api.feedback import router as feedback_router
from api.insights import router as insights_router
from services.ticket_queue import ticket_queue

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database tables...")
    init_db()
    ticket_queue.start()
    logger.info("AI Operations Brain backend is ready.")
    yield
    ticket_queue.stop()
    logger.info("Shutting down.")


app = FastAPI(
    title="AI Operations Brain — Support Automation",
    description=(
        "Customer support ticket processing pipeline powered by "
        "LangChain agents + OpenAI. Integrates with n8n for orchestration "
        "and provides a Streamlit dashboard for monitoring."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tickets_router)
app.include_router(logs_router)
app.include_router(feedback_router)
app.include_router(insights_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "AI Operations Brain"}


@app.get("/")
def root():
    return {
        "service": "AI Operations Brain",
        "docs": "/docs",
        "health": "/health",
    }
