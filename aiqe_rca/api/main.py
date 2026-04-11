"""FastAPI application entry point for the AIQE RCA Engine."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aiqe_rca.api.routes import router
from aiqe_rca.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — preload embedding model on startup."""
    # Preload embedding model so first request isn't slow
    from aiqe_rca.engine.evidence_associator import EmbeddingModel

    try:
        EmbeddingModel.get_model()
    except Exception:
        logger.warning("Embedding model preload failed; lexical fallback will be used.", exc_info=True)

    # Ensure reports directory exists
    settings.reports_dir.mkdir(parents=True, exist_ok=True)

    yield


app = FastAPI(
    title="AIQE Phase 2 — Root Cause Analysis Engine",
    description="Deterministic root cause analysis engine for manufacturing quality investigations.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
