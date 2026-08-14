
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


@app.get("/")
async def root():
    return FileResponse(APP_DIR / "index.html")


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY ist auf dem Server noch nicht gesetzt."
        )

    message = req.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Leere Nachricht."
        )

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

    consulted_agents = []

    tool_to_agent = {
        "frage_mirjana": "Mirjana",
        "frage_milorad": "Milorad",
        "frage_doktor_mladen": "Doktor Mladen",
        "frage_scout": "Scout",
        "frage_james_bond": "James Bond",
        "frage_pinky": "Pinky",
    }

    for item in result.new_items:
        tool_name = getattr(item, "tool_name", None)

        if tool_name in tool_to_agent:
            agent_name = tool_to_agent[tool_name]

            if agent_name not in consulted_agents:
                consulted_agents.append(agent_name)

    return {
        "session_id": session_id,
        "agent": result.last_agent.name,
        "message": result.final_output,
        "consulted_agents": consulted_agents,
    }
