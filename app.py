
import os
import uuid
import json
import sqlite3
import traceback
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents import Runner
from agents.extensions.memory import AsyncSQLiteSession

from team import milos


# ============================================================
# PFADE
# ============================================================

APP_DIR = Path(__file__).resolve().parent

MEMORY_DB_PATH = APP_DIR / "milos_memory.db"
WORKFLOW_DB_PATH = APP_DIR / "milos_workflows.db"

app = FastAPI(title="Miloš Team")


# ============================================================
# REQUEST MODELLE
# ============================================================

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


# ============================================================
# HILFSFUNKTIONEN
# ============================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_workflow_db():
    conn = sqlite3.connect(
        WORKFLOW_DB_PATH,
        timeout=30,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_workflow_db():
    conn = get_workflow_db()

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflows (
                workflow_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_message TEXT NOT NULL,
                status TEXT NOT NULL,

                final_message TEXT,
                final_agent TEXT,

                consulted_agents TEXT,
                workflow_events TEXT,

                error TEXT,

                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflows_session
            ON workflows(session_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflows_status
            ON workflows(status)
            """
        )

        conn.commit()

    finally:
        conn.close()


init_workflow_db()


def update_workflow(
    workflow_id: str,
    *,
    status: str | None = None,
    final_message: str | None = None,
    final_agent: str | None = None,
    consulted_agents: list[str] | None = None,
    workflow_events: list[dict] | None = None,
    error: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
):
    fields = []
    values = []

    if status is not None:
        fields.append("status = ?")
        values.append(status)

    if final_message is not None:
        fields.append("final_message = ?")
        values.append(final_message)

    if final_agent is not None:
        fields.append("final_agent = ?")
        values.append(final_agent)

    if consulted_agents is not None:
        fields.append("consulted_agents = ?")
        values.append(
            json.dumps(
                consulted_agents,
                ensure_ascii=False
            )
        )

    if workflow_events is not None:
        fields.append("workflow_events = ?")
        values.append(
            json.dumps(
                workflow_events,
                ensure_ascii=False
            )
        )

    if error is not None:
        fields.append("error = ?")
        values.append(error)

    if started_at is not None:
        fields.append("started_at = ?")
        values.append(started_at)

    if completed_at is not None:
        fields.append("completed_at = ?")
        values.append(completed_at)

    fields.append("updated_at = ?")
    values.append(utc_now())

    values.append(workflow_id)

    conn = get_workflow_db()

    try:
        conn.execute(
            f"""
            UPDATE workflows
            SET {", ".join(fields)}
            WHERE workflow_id = ?
            """,
            values,
        )

        conn.commit()

    finally:
        conn.close()


# ============================================================
# AGENTEN / WORKFLOW-EVENTS AUS RESULT.NEW_ITEMS LESEN
# ============================================================

def extract_workflow_information(result):
    """
    Best-effort-Auswertung der tatsächlich im Run erzeugten Items.

    Wichtig:
    Wir erfinden hier keine Agentenaktivitäten.
    Nur Informationen, die im RunResult wirklich vorhanden sind,
    werden übernommen.
    """

    consulted_agents = []
    events = []

    def add_agent(name):
        if not name:
            return

        name = str(name).strip()

        if name and name not in consulted_agents:
            consulted_agents.append(name)

    # Der Agent, der die finale Antwort geliefert hat
    try:
        last_agent = getattr(result, "last_agent", None)

        if last_agent:
            add_agent(getattr(last_agent, "name", None))

    except Exception:
        pass

    # Alle während dieses Runs entstandenen Items
    for item in getattr(result, "new_items", []) or []:

        try:
            item_type = type(item).__name__

            event = {
                "type": item_type
            }

            # ------------------------------------------------
            # Agent aus dem RunItem
            # ------------------------------------------------

            agent = getattr(item, "agent", None)

            if agent:
                agent_name = getattr(agent, "name", None)

                if agent_name:
                    event["agent"] = agent_name
                    add_agent(agent_name)

            # ------------------------------------------------
            # Raw Item
            # ------------------------------------------------

            raw_item = getattr(item, "raw_item", None)

            if raw_item is not None:

                raw_type = getattr(raw_item, "type", None)

                if raw_type:
                    event["raw_type"] = str(raw_type)

                # Einige SDK-Items enthalten einen Namen
                raw_name = getattr(raw_item, "name", None)

                if raw_name:
                    event["name"] = str(raw_name)

                # Toolname
                tool_name = getattr(raw_item, "tool_name", None)

                if tool_name:
                    event["tool_name"] = str(tool_name)

            # ------------------------------------------------
            # Handoff-Ziel erkennen
            # ------------------------------------------------

            target_agent = getattr(item, "target_agent", None)

            if target_agent:
                target_name = getattr(
                    target_agent,
                    "name",
                    None
                )

                if target_name:
                    event["target_agent"] = target_name
                    add_agent(target_name)

            source_agent = getattr(item, "source_agent", None)

            if source_agent:
                source_name = getattr(
                    source_agent,
                    "name",
                    None
                )

                if source_name:
                    event["source_agent"] = source_name
                    add_agent(source_name)

            events.append(event)

        except Exception as exc:

            events.append(
                {
                    "type": "unparsed_item",
                    "error": str(exc)
                }
            )

    return consulted_agents, events


# ============================================================
# EIGENTLICHER MILOŠ-WORKFLOW
# ============================================================

async def run_milos_workflow(
    workflow_id: str,
    session_id: str,
    message: str
):
    print(
        f"[WORKFLOW {workflow_id}] "
        f"START session={session_id}"
    )

    update_workflow(
        workflow_id,
        status="RUNNING",
        started_at=utc_now(),
    )

    try:
        # ----------------------------------------------------
        # Persistente Conversation Memory
        # ----------------------------------------------------

        session = AsyncSQLiteSession(
            session_id,
            db_path=MEMORY_DB_PATH
        )

        # ----------------------------------------------------
        # Agentenlauf
        # ----------------------------------------------------

        result = await Runner.run(
            milos,
            message,
            session=session
        )

        # ----------------------------------------------------
        # Ergebnis
        # ----------------------------------------------------

        final_output = result.final_output

        if final_output is None:
            final_message = ""
        elif isinstance(final_output, str):
            final_message = final_output
        else:
            final_message = str(final_output)

        last_agent = getattr(
            result,
            "last_agent",
            None
        )

        final_agent = (
            getattr(last_agent, "name", None)
            if last_agent
            else None
        )

        consulted_agents, workflow_events = (
            extract_workflow_information(result)
        )

        # Falls Miloš finaler Agent war und nicht bereits enthalten
        if (
            final_agent
            and final_agent not in consulted_agents
        ):
            consulted_agents.append(final_agent)

        update_workflow(
            workflow_id,
            status="COMPLETED",
            final_message=final_message,
            final_agent=final_agent or "Miloš",
            consulted_agents=consulted_agents,
            workflow_events=workflow_events,
            completed_at=utc_now(),
        )

        print(
            f"[WORKFLOW {workflow_id}] COMPLETED "
            f"agents={consulted_agents}"
        )

    except Exception as exc:

        error_text = (
            f"{type(exc).__name__}: {exc}"
        )

        print(
            f"[WORKFLOW {workflow_id}] FAILED: "
            f"{error_text}"
        )

        traceback.print_exc()

        update_workflow(
            workflow_id,
            status="FAILED",
            error=error_text,
            completed_at=utc_now(),
        )


# ============================================================
# ROUTEN
# ============================================================

@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "Miloš Team"
    }


@app.get("/")
async def root():
    return FileResponse(
        APP_DIR / "index.html"
    )


# ============================================================
# NEU:
# Request startet nur den Workflow und wartet NICHT auf Miloš
# ============================================================

@app.post("/api/chat")
async def chat(
    req: ChatRequest,
    background_tasks: BackgroundTasks
):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail=(
                "OPENAI_API_KEY ist auf dem Server "
                "noch nicht gesetzt."
            )
        )

    message = req.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Leere Nachricht."
        )

    session_id = (
        req.session_id
        or str(uuid.uuid4())
    )

    # --------------------------------------------------------
    # Schutz gegen Doppelabsenden
    # --------------------------------------------------------

    conn = get_workflow_db()

    try:
        running = conn.execute(
            """
            SELECT workflow_id, status
            FROM workflows
            WHERE session_id = ?
              AND status IN ('QUEUED', 'RUNNING')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()

    finally:
        conn.close()

    if running:
        return {
            "session_id": session_id,
            "workflow_id": running["workflow_id"],
            "status": running["status"],
            "already_running": True
        }

    # --------------------------------------------------------
    # Neuer Workflow
    # --------------------------------------------------------

    workflow_id = str(uuid.uuid4())
    now = utc_now()

    conn = get_workflow_db()

    try:
        conn.execute(
            """
            INSERT INTO workflows (
                workflow_id,
                session_id,
                user_message,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                workflow_id,
                session_id,
                message,
                "QUEUED",
                now,
                now,
            ),
        )

        conn.commit()

    finally:
        conn.close()

    # --------------------------------------------------------
    # Workflow nach HTTP-Antwort weiterlaufen lassen
    # --------------------------------------------------------

    background_tasks.add_task(
        run_milos_workflow,
        workflow_id,
        session_id,
        message
    )

    # --------------------------------------------------------
    # Sofortige Antwort an iPhone
    # --------------------------------------------------------

    return {
        "session_id": session_id,
        "workflow_id": workflow_id,
        "status": "QUEUED",
        "already_running": False
    }


# ============================================================
# STATUS-POLLING
# ============================================================

@app.get("/api/workflow/{workflow_id}")
async def workflow_status(workflow_id: str):

    conn = get_workflow_db()

    try:
        row = conn.execute(
            """
            SELECT *
            FROM workflows
            WHERE workflow_id = ?
            """,
            (workflow_id,),
        ).fetchone()

    finally:
        conn.close()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Workflow nicht gefunden."
        )

    consulted_agents = []

    if row["consulted_agents"]:
        try:
            consulted_agents = json.loads(
                row["consulted_agents"]
            )
        except Exception:
            consulted_agents = []

    workflow_events = []

    if row["workflow_events"]:
        try:
            workflow_events = json.loads(
                row["workflow_events"]
            )
        except Exception:
            workflow_events = []

    return {
        "workflow_id": row["workflow_id"],
        "session_id": row["session_id"],
        "status": row["status"],

        "agent": row["final_agent"],
        "message": row["final_message"],

        "consulted_agents": consulted_agents,
        "workflow_events": workflow_events,

        "error": row["error"],

        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "updated_at": row["updated_at"],
    }
