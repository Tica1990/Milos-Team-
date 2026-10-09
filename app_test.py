
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel


# ============================================================
# MILOŠ TEAM 3.0 – ISOLIERTER TESTSERVER
# ============================================================

APP_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Miloš Team 3.0 TEST",
    version="3.0-test"
)


# ============================================================
# REQUEST-MODELLE
# ============================================================

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
async def health():
    return {
        "ok": True,
        "version": "3.0-test",
        "mode": "isolated"
    }


# ============================================================
# BENUTZEROBERFLÄCHE
# ============================================================

@app.get("/")
async def root():
    return FileResponse(
        APP_DIR / "index.html",
        media_type="text/html"
    )


# ============================================================
# TEST-CHAT
# ============================================================

@app.post("/api/chat")
async def chat(req: ChatRequest):

    session_id = req.session_id or str(uuid4())

    return {
        "status": "TEST_READY",
        "message": (
            "Miloš Team 3.0 Testserver läuft. "
            "Agenten noch nicht aktiviert."
        ),
        "session_id": session_id
    }
