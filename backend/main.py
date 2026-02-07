"""
ArXiviz Backend API - FastAPI Entry Point

Run with: uvicorn main:app --reload --port 8000
Docs at: http://localhost:8000/docs
"""

import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from api.routes import router as api_router
from db import init_db

# Load environment variables
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # Startup: Initialize database
    print("Initializing database...")
    await init_db()
    print("Database ready!")
    yield
    # Shutdown: cleanup if needed
    print("Shutting down...")


# Create FastAPI app
app = FastAPI(
    title="ArXiviz API",
    description="Transform arXiv papers into animated visual explanations",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for hackathon development
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
