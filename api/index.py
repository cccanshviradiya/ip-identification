import os
import sys
import traceback
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Define `app` at the top level so Vercel's AST parser can find it during the Build step!
app = FastAPI()

try:
    # Try to load the real application
    from app.main import app as real_app
    from app.database.models import init_db
    init_db()
    
    # If successful, replace the dummy app with the real app
    app = real_app

except Exception as e:
    error_msg = traceback.format_exc()
    
    # If it fails, the dummy app remains and serves the error message
    @app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def catch_all(path_name: str):
        return PlainTextResponse(f"Initialization Error:\n{error_msg}", status_code=500)
# The variable name must be "app" for FastAPI/ASGI apps
