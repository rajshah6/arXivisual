"""
ArXiviz Backend API - FastAPI Entry Point

Run with: uvicorn main:app --reload --port 8000
Docs at: http://localhost:8000/docs
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load environment variables BEFORE any local imports
# (rendering/storage.py reads STORAGE_MODE at import time)
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Set specific logger levels
logging.getLogger("rendering").setLevel(logging.INFO)
logging.getLogger("jobs").setLevel(logging.INFO)
logging.getLogger("agents").setLevel(logging.INFO)

# Application Insights (no-op without APPLICATIONINSIGHTS_CONNECTION_STRING).
# Must run BEFORE `from fastapi import FastAPI`: the distro instruments by
# swapping the FastAPI class, so an app built from a class imported earlier
# would carry no request telemetry. It also binds Langfuse to its own
# TracerProvider before any pipeline code can create a client (telemetry.py).
import telemetry

telemetry.configure()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

import analytics
from api.cors import allowed_origins
from api.routes import router as api_router
from db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # Startup: Initialize database
    print("Initializing database...")
    await init_db()
    print("Database ready!")
    yield
    # Shutdown: flush queued product events (no-op when PostHog is off).
    print("Shutting down...")
    analytics.shutdown()


# Create FastAPI app
app = FastAPI(
    title="ArXiviz API",
    description="Transform arXiv papers into animated visual explanations",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS: the production hosts plus CORS_EXTRA_ORIGINS (see api/cors.py). The
# frontend is a Container App in this environment, so there are no per-PR
# preview hosts to admit any more.
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API router
app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to API documentation."""
    return RedirectResponse(url="/docs")


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    # Support PORT (Render, Railway, Fly) and API_PORT (local)
    port = int(os.getenv("PORT") or os.getenv("API_PORT", "8000"))

    uvicorn.run("main:app", host=host, port=port, reload=True)
