"""FastAPI application entry point for the AIQE RCA Engine."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aiqe_rca.api.routes import router
from aiqe_rca.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — preload embedding model on startup."""
    # Preload embedding model so first request isn't slow
    from aiqe_rca.engine.evidence_associator import EmbeddingModel

    EmbeddingModel.get_model()

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
