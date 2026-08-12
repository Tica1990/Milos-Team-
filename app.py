
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents import Runner
from agents.extensions.memory import AsyncSQLiteSession

from team import milos

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "milos_memory.db"

app = FastAPI(title="Miloš Team")

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY ist auf dem Server noch nicht gesetzt."
        )

    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Leere Nachricht.")

    session_id = req.session_id or str(uuid.uuid4())
    session = AsyncSQLiteSession(
        session_id=session_id,
        db_path=str(DB_PATH),
    )

    result = await Runner.run(
        milos,
        message,
        session=session,
    )

    return {
        "session_id": session_id,
        "agent": result.last_agent.name,
        "message": result.final_output,
    }

app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

@app.get("/")
async def index():
    return FileResponse(APP_DIR / "static" / "index.html")
