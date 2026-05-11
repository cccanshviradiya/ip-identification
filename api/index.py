import os
import sys

# Add the project root to the system path so imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database.models import init_db

# Vercel serverless functions do not consistently trigger FastAPI's @app.on_event("startup")
# Therefore, we initialize the database explicitly when the module is loaded.
init_db()

# This is required by Vercel to handle requests
# The variable name must be "app" for FastAPI/ASGI apps
