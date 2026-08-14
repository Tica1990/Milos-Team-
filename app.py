
import os
import uuid
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents import Runner, SQLiteSession
from agents.items import ToolCallItem, ToolCallOutputItem

from team import milos


# ============================================================
# GRUNDEINSTELLUNGEN
# ============================================================

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "milos_memory.db"

app = FastAPI(title="Miloš Team 3.0")


# ============================================================
# REQUEST-MODELL
# ============================================================

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


# ============================================================
# TOOL → AGENT ZUORDNUNG
# ============================================================

TOOL_TO_AGENT = {
    "frage_mirjana": "Mirjana",
    "frage_milorad": "Milorad",
    "frage_doktor_mladen": "Doktor Mladen",
    "frage_scout": "Scout",
    "frage_james_bond": "James Bond",
    "frage_pinky": "Pinky",
}


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():
    return {
        "ok": True,
        "app": "Miloš Team 3.0",
    }


# ============================================================
# WEB-OBERFLÄCHE
# ============================================================

@app.get("/")
async def root():
    index_path = APP_DIR / "index.html"

    if not index_path.exists():
        raise HTTPException(
            status_code=500,
            detail="index.html wurde auf dem Server nicht gefunden.",
        )

    return FileResponse(index_path)


# ============================================================
# TOOL-AUSGABE IN TEXT UMWANDELN
# ============================================================

def tool_output_to_text(output):
    if output is None:
        return ""

    if isinstance(output, str):
        return output

    try:
        return json.dumps(
            output,
            ensure_ascii=False,
        )
    except Exception:
        return str(output)


# ============================================================
# WAITING_FOR_USER AUS TOOL-AUSGABE LESEN
# ============================================================

def parse_user_question(text):
    if not text:
        return None

    if "WAITING_FOR_USER" not in text:
        return None

    question = ""
    reason = ""

    for line in text.splitlines():
        line = line.strip()

        if line.startswith("FRAGE:"):
            question = line.removeprefix("FRAGE:").strip()

        elif line.startswith("GRUND:"):
            reason = line.removeprefix("GRUND:").strip()

    if not question:
        return None

    return {
        "question": question,
        "reason": reason,
    }


# ============================================================
# AGENTENLAUF ANALYSIEREN
# ============================================================

def analyse_run(result):
    consulted_agents = []
    agent_flow = ["Miloš"]
    tool_calls = []

    waiting_for_user = None

    # call_id → tool_name
    tool_calls_by_id = {}

    for item in result.new_items:

        # ----------------------------------------------------
        # TOOL-AUFRUF
        # ----------------------------------------------------

        if isinstance(item, ToolCallItem):
            tool_name = item.tool_name

            if not tool_name:
                continue

            tool_calls.append(tool_name)

            call_id = item.call_id

            if call_id:
                tool_calls_by_id[call_id] = tool_name

            # Spezialisten erkennen
            agent_name = TOOL_TO_AGENT.get(tool_name)

            if agent_name:
                if agent_name not in consulted_agents:
                    consulted_agents.append(agent_name)

                agent_flow.append(agent_name)

        # ----------------------------------------------------
        # TOOL-AUSGABE
        # ----------------------------------------------------

        elif isinstance(item, ToolCallOutputItem):

            call_id = item.call_id

            if not call_id:
                continue

            tool_name = tool_calls_by_id.get(call_id)

            if tool_name != "frage_nutzer":
                continue

            output_text = tool_output_to_text(item.output)

            parsed = parse_user_question(output_text)

            if parsed:
                waiting_for_user = parsed

    agent_flow.append("Miloš")

    return {
        "consulted_agents": consulted_agents,
        "agent_flow": agent_flow,
        "tool_calls": tool_calls,
        "waiting_for_user": waiting_for_user,
    }


# ============================================================
# CHAT-ENDPOINT
# ============================================================

@app.post("/api/chat")
async def chat(req: ChatRequest):

    # --------------------------------------------------------
    # API KEY PRÜFEN
    # --------------------------------------------------------

    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY ist auf dem Server nicht gesetzt.",
        )

    # --------------------------------------------------------
    # NACHRICHT PRÜFEN
    # --------------------------------------------------------

    message = req.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Leere Nachricht.",
        )

    # --------------------------------------------------------
    # SESSION
    # --------------------------------------------------------

    session_id = req.session_id or str(uuid.uuid4())

    session = SQLiteSession(
        session_id=session_id,
        db_path=str(DB_PATH),
    )

    # --------------------------------------------------------
    # MILOŠ STARTEN
    # --------------------------------------------------------

    try:
        result = await Runner.run(
            milos,
            message,
            session=session,
            max_turns=30,
        )

    except Exception as exc:
        print(
            "MILOŠ RUN ERROR:",
            type(exc).__name__,
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Agentenlauf fehlgeschlagen: "
                f"{type(exc).__name__}"
            ),
        ) from exc

    # --------------------------------------------------------
    # RUN ANALYSIEREN
    # --------------------------------------------------------

    run_info = analyse_run(result)

    waiting = run_info["waiting_for_user"]

    # --------------------------------------------------------
    # STATUS: WAITING_FOR_USER
    # --------------------------------------------------------

    if waiting:
        return {
            "session_id": session_id,

            "status": "WAITING_FOR_USER",

            "agent": "Miloš",

            "message": waiting["question"],

            "question": waiting["question"],

            "reason": waiting["reason"],

            "consulted_agents":
                run_info["consulted_agents"],

            "agent_flow":
                run_info["agent_flow"],

            "tool_calls":
                run_info["tool_calls"],
        }

    # --------------------------------------------------------
    # STATUS: COMPLETED
    # --------------------------------------------------------

    return {
        "session_id": session_id,

        "status": "COMPLETED",

        "agent": result.last_agent.name,

        "message": str(result.final_output),

        "consulted_agents":
            run_info["consulted_agents"],

        "agent_flow":
            run_info["agent_flow"],

        "tool_calls":
            run_info["tool_calls"],
    }
