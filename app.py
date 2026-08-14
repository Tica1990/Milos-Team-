
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents import Runner
from agents.items import ToolCallItem
from agents.memory import SQLiteSession

from team import milos


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "milos_memory.db"

app = FastAPI(title="Miloš Team 3.0")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


TOOL_TO_AGENT = {
    "frage_mirjana": "Mirjana",
    "frage_milorad": "Milorad",
    "frage_doktor_mladen": "Doktor Mladen",
    "frage_scout": "Scout",
    "frage_james_bond": "James Bond",
    "frage_pinky": "Pinky",
}


@app.get("/health")
async def health():
    return {
        "ok": True,
        "app": "Miloš Team 3.0",
    }


@app.get("/")
async def root():
    index_path = APP_DIR / "index.html"

    if not index_path.exists():
        raise HTTPException(
            status_code=500,
            detail="index.html wurde auf dem Server nicht gefunden.",
        )

    return FileResponse(index_path)


def analyse_run(result):
    consulted_agents = []
    agent_flow = ["Miloš"]
    tool_calls = []

    for item in result.new_items:
        if not isinstance(item, ToolCallItem):
            continue

        tool_name = item.tool_name

        if not tool_name:
            continue

        tool_calls.append(tool_name)

        agent_name = TOOL_TO_AGENT.get(tool_name)

        if not agent_name:
            continue

        if agent_name not in consulted_agents:
            consulted_agents.append(agent_name)

        agent_flow.append(agent_name)

    agent_flow.append("Miloš")

    return {
        "consulted_agents": consulted_agents,
        "agent_flow": agent_flow,
        "tool_calls": tool_calls,
    }


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY ist auf dem Server nicht gesetzt.",
        )

    message = req.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Leere Nachricht.",
        )

    session_id = req.session_id or str(uuid.uuid4())

    session = SQLiteSession(
        session_id=session_id,
        db_path=str(DB_PATH),
    )

    try:
        result = await Runner.run(
            milos,
            message,
            session=session,
            max_turns=30,
        )

    except Exception as exc:
        print("MILOŠ RUN ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail=f"Agentenlauf fehlgeschlagen: {type(exc).__name__}",
        ) from exc

    run_info = analyse_run(result)

    return {
        "session_id": session_id,
        "agent": result.last_agent.name,
        "message": str(result.final_output),
        "consulted_agents": run_info["consulted_agents"],
        "agent_flow": run_info["agent_flow"],
        "tool_calls": run_info["tool_calls"],
    }
