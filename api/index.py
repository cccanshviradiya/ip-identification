import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from app.main import app
    from app.database.models import init_db
    init_db()
except Exception as e:
    import traceback
    error_msg = traceback.format_exc()
    # Create a dummy FastAPI app to return the error
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    app = FastAPI()
    @app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def catch_all(path_name: str):
        return PlainTextResponse(f"Initialization Error:\n{error_msg}", status_code=500)
# The variable name must be "app" for FastAPI/ASGI apps
