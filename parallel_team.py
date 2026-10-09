"""Experimental parallel specialist coordination for Miloš Team 3.0.

Standalone module: importing it does not change the existing FastAPI routes.
Call run_parallel_team() only from a separate test entrypoint.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

from agents import Runner
from team import mirjana, milorad, doktor_mladen, scout, james_bond, pinky

AGENTS = {
    "Mirjana": mirjana,
    "Milorad": milorad,
    "Doktor Mladen": doktor_mladen,
    "Scout": scout,
    "James Bond": james_bond,
    "Pinky": pinky,
}

EventSink = Callable[[dict], Awaitable[None]]

@dataclass
class Task:
    agent: str
    instruction: str
    depends_on: list[str] = field(default_factory=list)

@dataclass
class TaskResult:
    agent: str
    output: str
    status: str
    error: str | None = None

async def run_parallel_team(
    user_goal: str,
    tasks: list[Task],
    *,
    event_sink: EventSink | None = None,
    max_concurrency: int = 3,
    max_turns: int = 8,
) -> dict:
    """Run independent agents concurrently and dependent agents after handoff.

    Dependencies must reference agents in the task list. One task per agent.
    Failed dependencies cause dependent tasks to be skipped. No external
    actions are performed by this coordinator. The caller controls approvals.
    """
    if not user_goal.strip():
        raise ValueError("user_goal must not be empty")
    if not 1 <= max_concurrency <= 6:
        raise ValueError("max_concurrency must be between 1 and 6")
    names = [task.agent for task in tasks]
    if not tasks or len(names) != len(set(names)):
        raise ValueError("Specify at least one task and no duplicate agents")
    if any(name not in AGENTS for name in names):
        raise ValueError("Unknown agent in task list")
    if any(dep not in names or dep == task.agent for task in tasks for dep in task.depends_on):
        raise ValueError("Invalid task dependency")

    pending = {task.agent: task for task in tasks}
    results: dict[str, TaskResult] = {}
    events: list[dict] = []
    semaphore = asyncio.Semaphore(max_concurrency)

    async def emit(kind: str, agent: str, **details):
        event = {"time": datetime.now(timezone.utc).isoformat(),
                 "type": kind, "agent": agent, **details}
        events.append(event)
        if event_sink:
            await event_sink(event)

    async def execute(task: Task) -> TaskResult:
        async with semaphore:
            await emit("agent_started", task.agent)
            handoffs = "\n\n".join(
                f"Ergebnis von {dep}:\n{results[dep].output}"
                for dep in task.depends_on
            )
            prompt = (
                f"NUTZERZIEL:\n{user_goal}\n\n"
                f"DEIN AUFTRAG:\n{task.instruction}\n\n"
                f"ÜBERGEBENE ERGEBNISSE:\n{handoffs or 'Keine; unabhängige Erstanalyse.'}\n\n"
                "Arbeite eigenständig. Trenne Fakten, Annahmen und Empfehlungen. "
                "Zitiere überprüfbare Quellen. Keine externen Aktionen ausführen."
            )
            try:
                response = await Runner.run(AGENTS[task.agent], prompt, max_turns=max_turns)
                result = TaskResult(task.agent, str(response.final_output), "COMPLETED")
                await emit("agent_completed", task.agent)
                return result
            except Exception as exc:
                await emit("agent_failed", task.agent, error=str(exc))
                return TaskResult(task.agent, "", "FAILED", str(exc))

    while pending:
        ready = [t for t in pending.values() if all(d in results for d in t.depends_on)]
        if not ready:
            raise ValueError("Cyclic dependencies between agents")
        runnable = []
        for task in ready:
            if any(results[d].status != "COMPLETED" for d in task.depends_on):
                results[task.agent] = TaskResult(task.agent, "", "SKIPPED", "Dependency failed")
                await emit("agent_skipped", task.agent)
            else:
                runnable.append(task)
            del pending[task.agent]
        if runnable:
            finished = await asyncio.gather(*(execute(t) for t in runnable))
            for item in finished:
                results[item.agent] = item

    return {
        "status": "COMPLETED" if all(r.status == "COMPLETED" for r in results.values()) else "PARTIAL",
        "results": {name: vars(result) for name, result in results.items()},
        "events": events,
    }
