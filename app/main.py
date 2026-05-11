"""
main.py — FastAPI application entry point.
Sets up CORS, mounts routes, initializes the database, and serves the frontend.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import sys

# Add the app directory to path for clean imports
sys.path.insert(0, os.path.dirname(__file__))

from database.models import init_db
from routes.identify import router as identify_router
from services.logger import get_logger

logger = get_logger("main")

# ─── App Instance ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="IP Company Identification API",
    description=(
        "MVP/POC for identifying B2B companies visiting a website "
        "based on their IP address. Focused on Indian corporate traffic."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS Middleware ──────────────────────────────────────────────────────────
# Allow frontend (served separately or from the same origin) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Restrict to specific domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Database Initialization ──────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    """Initialize SQLite database tables on first run."""
    logger.info("Starting IP Identification MVP...")
    init_db()
    logger.info("Database initialized successfully.")
    logger.info("IP Identification Service is ready.")
    logger.info("Check /app for the frontend, /docs for API documentation.")


# ─── API Routes ───────────────────────────────────────────────────────────────
app.include_router(identify_router, prefix="/api", tags=["Identification"])


# ─── Frontend Static Files ────────────────────────────────────────────────────
# Serve the frontend HTML/CSS/JS from the /frontend directory
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/app", include_in_schema=False)
    async def serve_frontend():
        """Serve the main frontend application."""
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        """Redirect root to frontend app."""
        return FileResponse(os.path.join(frontend_dir, "index.html"))


# ─── Health Check ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    """Simple liveness probe."""
    return {"status": "healthy", "service": "ip-identification-mvp", "version": "1.0.0"}


# ─── Run directly with: python main.py ───────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="debug",
    )
