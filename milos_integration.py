"""Miloš-led planning and synthesis for isolated Miloš Team 3.0.

Does not import or modify production app.py. Live calls require OPENAI_API_KEY.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from autonomous_team import Limits, SPECIALISTS, Coordinator, make_live_runner


def parse_plan(raw: str, *, max_roots: int = 4) -> dict[str, str]:
    """Validate Miloš's proposed independent first-round assignments."""
    cleaned = raw.strip()
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', cleaned).strip()
    plan = json.loads(cleaned)
    if not isinstance(plan, dict) or set(plan) != {'assignments'}:
        raise ValueError('Plan must contain only assignments')
    tasks = plan['assignments']
    if not isinstance(tasks, dict) or not 1 <= len(tasks) <= max_roots:
        raise ValueError('Invalid number of initial specialists')
    if any(k not in SPECIALISTS or not isinstance(v, str) or not 1 <= len(v.strip()) <= 1800 for k, v in tasks.items()):
        raise ValueError('Invalid specialist or assignment')
    return {k: v.strip() for k, v in tasks.items()}


async def run_milos_team(goal: str, *, planner: Callable | None = None,
                         specialist_runner: Callable | None = None,
                         synthesizer: Callable | None = None,
                         limits: Limits = Limits(), event_sink=None) -> dict:
    """Plan -> parallel autonomous colleagues -> Miloš synthesis.

    Dependency injection allows offline tests; actual SDK runners are loaded lazily.
    """
    if not goal.strip():
        raise ValueError('Empty goal')
    if planner is None or synthesizer is None:
        live_planner, live_synthesizer = make_milos_adapters()
        planner = planner or live_planner
        synthesizer = synthesizer or live_synthesizer
    raw_plan = await planner(goal)
    assignments = parse_plan(raw_plan, max_roots=min(4, limits.max_agent_runs))
    coordinator = Coordinator(goal, specialist_runner or make_live_runner(), limits, event_sink)
    result = await coordinator.run(assignments)
    # No false claim of completion if a colleague failed or timed out.
    summary = await synthesizer(goal, assignments, result)
    return {'goal': goal, 'assignments': assignments, 'milos_summary': summary, **result}


def make_milos_adapters():
    from agents import Runner
    from team import milos

    # Miloš is cloned WITHOUT specialist tools: this prevents untracked,
    # unlimited tool-driven runs outside the coordinator's budgets.
    planning_agent = milos.clone(tools=[], instructions=(
        'Du bist Miloš, Koordinator. Erstelle NUR gültiges JSON ohne Markdown: '
        '{"assignments":{"Scout":"konkreter Auftrag", "Milorad":"konkreter Auftrag"}}. '
        'Wähle 1 bis 4 tatsächlich relevante Spezialisten aus: '
        + ', '.join(SPECIALISTS) + '. '
        'Erste Runde: voneinander unabhängige Aufgaben, die parallel laufen können. '
        'Keine externen Aktionen, keine erfundenen Fakten. '
        'Die Spezialisten dürfen sich bei Bedarf gegenseitig beauftragen.'
    ))
    synthesis_agent = milos.clone(tools=[], instructions=(
        'Du bist Miloš, Koordinator. Fasse ausschließlich die tatsächlich gelieferten '
        'Agentenergebnisse zusammen. Zeige abweichende Meinungen, Unsicherheiten, '
        'Quellen, Grenzen und konkrete nächste Schritte. '
        'Erfinde keine erledigten Schritte. Keine externen Aktionen.'
    ))

    async def plan(goal):
        result = await Runner.run(planning_agent, goal, max_turns=3)
        return str(result.final_output)

    async def synthesize(goal, assignments, result):
        payload = {'goal': goal, 'assignments': assignments, 'status': result['status'],
                   'results': result['results'], 'agent_runs': result['agent_runs'],
                   'delegations': result['delegations']}
        output = await Runner.run(synthesis_agent, json.dumps(payload, ensure_ascii=False), max_turns=3)
        return str(output.final_output)

    return plan, synthesize
