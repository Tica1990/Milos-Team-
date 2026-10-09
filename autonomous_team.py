"""Isolated Miloš Team 3.0 agent-to-agent prototype.

No FastAPI routes, deployments, or external actions are modified by importing this.
Requires openai-agents and the existing team.py only when make_live_runner is called.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

SPECIALISTS = ("Mirjana", "Milorad", "Doktor Mladen", "Scout", "James Bond", "Pinky")


@dataclass(frozen=True)
class Limits:
    max_parallel_roots: int = 3
    max_delegations: int = 6
    max_depth: int = 2
    max_agent_runs: int = 12
    timeout_seconds: float = 180.0
    max_turns: int = 8


@dataclass
class WorkItem:
    agent: str
    assignment: str
    parent: str | None = None
    depth: int = 0


@dataclass
class AgentOutcome:
    agent: str
    assignment: str
    output: str = ""
    status: str = "PENDING"
    error: str | None = None
    parent: str | None = None


class Coordinator:
    """Delegation broker. A parent can await its colleague without deadlocking a root semaphore.

    Limits cap total work, depth, and elapsed time. Tool calls only return text:
    there are no write, purchase, email, or publication capabilities here.
    """

    def __init__(self, goal: str, run_agent: Callable, limits: Limits = Limits(), event_sink=None):
        if not goal.strip():
            raise ValueError("Goal must not be empty")
        if not 1 <= limits.max_parallel_roots <= 6 or limits.max_depth < 0 or limits.max_agent_runs < 1:
            raise ValueError("Invalid limits")
        self.goal, self.run_agent, self.limits = goal, run_agent, limits
        self.event_sink = event_sink
        self.events: list[dict] = []
        self.outcomes: list[AgentOutcome] = []
        self._lock = asyncio.Lock()
        self._delegations = 0
        self._runs = 0
        self._root_gate = asyncio.Semaphore(limits.max_parallel_roots)
        self._stop = asyncio.Event()

    async def emit(self, event_type: str, **data):
        event = {"timestamp": datetime.now(timezone.utc).isoformat(), "type": event_type, **data}
        self.events.append(event)
        if self.event_sink:
            await self.event_sink(event)

    async def delegate(self, caller: WorkItem, target: str, assignment: str) -> str:
        """Agent-to-agent request; caller gets the actual colleague's answer."""
        if target not in SPECIALISTS:
            return f"DELEGATION_REJECTED: Unknown colleague {target}"
        if target == caller.agent:
            return "DELEGATION_REJECTED: Cannot delegate to yourself"
        if not assignment.strip():
            return "DELEGATION_REJECTED: Empty assignment"
        async with self._lock:
            if caller.depth >= self.limits.max_depth:
                return "DELEGATION_REJECTED: Maximum delegation depth reached"
            if self._delegations >= self.limits.max_delegations:
                return "DELEGATION_REJECTED: Delegation budget exhausted"
            if self._runs >= self.limits.max_agent_runs:
                return "DELEGATION_REJECTED: Agent-run budget exhausted"
            self._delegations += 1
        await self.emit("agent_message", sender=caller.agent, recipient=target, assignment=assignment[:500])
        result = await self._execute(WorkItem(target, assignment, caller.agent, caller.depth + 1))
        return (f"ANTWORT VON {target} ({result.status}):\n{result.output or result.error or 'Keine Antwort'}")

    async def _execute(self, item: WorkItem) -> AgentOutcome:
        outcome = AgentOutcome(item.agent, item.assignment, parent=item.parent)
        async with self._lock:
            if self._runs >= self.limits.max_agent_runs:
                outcome.status, outcome.error = "SKIPPED", "Agent-run budget exhausted"
                self.outcomes.append(outcome)
                return outcome
            self._runs += 1
            self.outcomes.append(outcome)
        outcome.status = "RUNNING"
        await self.emit("agent_started", agent=item.agent, parent=item.parent, depth=item.depth)
        prompt = (f"NUTZERZIEL:\n{self.goal}\n\nDEIN AUFTRAG:\n{item.assignment}\n\n"
                  "Arbeite fachlich eigenständig. Du darfst bei Bedarf über frage_kollege "
                  "einen anderen Spezialisten direkt beauftragen. Gib Kontext und konkrete Frage weiter. "
                  "Vermeide unnötige Delegationen. Keine externen Aktionen. "
                  "Unterscheide belegte Fakten, Annahmen und Empfehlungen.")
        try:
            outcome.output = str(await self.run_agent(item, prompt, self.delegate, self.limits.max_turns))
            outcome.status = "COMPLETED"
            await self.emit("agent_completed", agent=item.agent, parent=item.parent)
        except asyncio.CancelledError:
            outcome.status, outcome.error = "CANCELLED", "Run cancelled"
            await self.emit("agent_cancelled", agent=item.agent)
            raise
        except Exception as exc:
            outcome.status, outcome.error = "FAILED", f"{type(exc).__name__}: {exc}"
            await self.emit("agent_failed", agent=item.agent, error=outcome.error)
        return outcome

    async def run(self, assignments: dict[str, str]) -> dict:
        if not assignments or any(a not in SPECIALISTS or not text.strip() for a, text in assignments.items()):
            raise ValueError("Provide valid specialist assignments")
        if len(assignments) > self.limits.max_agent_runs:
            raise ValueError("More root assignments than run budget")

        async def root(agent, assignment):
            async with self._root_gate:
                return await self._execute(WorkItem(agent, assignment))

        try:
            async with asyncio.timeout(self.limits.timeout_seconds):
                roots = await asyncio.gather(*(root(a, v) for a, v in assignments.items()))
            status = "COMPLETED" if all(o.status == "COMPLETED" for o in roots) else "PARTIAL"
        except TimeoutError:
            status = "TIMEOUT"
            await self.emit("workflow_timeout", seconds=self.limits.timeout_seconds)
        return {"status": status, "results": [vars(o).copy() for o in self.outcomes],
                "events": self.events.copy(), "agent_runs": self._runs,
                "delegations": self._delegations}


def make_live_runner():
    """Adapter to existing team.py; specialists get a run-local colleague tool.

    No mutation of global Agent instances. No write-capable tools are added.
    """
    from agents import Runner, function_tool
    from team import mirjana, milorad, doktor_mladen, scout, james_bond, pinky

    roster = dict(zip(SPECIALISTS, (mirjana, milorad, doktor_mladen, scout, james_bond, pinky)))

    async def run_agent(item: WorkItem, prompt: str, delegate, max_turns: int):
        @function_tool
        async def frage_kollege(ziel_agent: str, auftrag: str) -> str:
            """Bitte einen anderen Team-Spezialisten um eine fachliche Einschätzung.

            Args:
                ziel_agent: Name eines anderen Spezialisten im Team.
                auftrag: Konkrete Frage mit notwendigem Kontext.
            """
            return await delegate(item, ziel_agent, auftrag)

        base = roster[item.agent]
        specialist = base.clone(tools=[*base.tools, frage_kollege])
        result = await Runner.run(specialist, prompt, max_turns=max_turns)
        return str(result.final_output)

    return run_agent


async def run_autonomous_team(goal: str, assignments: dict[str, str], *, limits=Limits(), event_sink=None):
    coordinator = Coordinator(goal, make_live_runner(), limits, event_sink)
    return await coordinator.run(assignments)
