import os
import sys

# Add the app directory to the system path so imports work correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app.main import app

# This is required by Vercel to handle requests
# The variable name must be "app" for FastAPI/ASGI apps
