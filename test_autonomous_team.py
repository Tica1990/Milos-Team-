import asyncio
import unittest
from autonomous_team import Coordinator, Limits


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_delegation_and_events(self):
        async def fake(item, prompt, delegate, turns):
            if item.agent == "Scout":
                return await delegate(item, "Mirjana", "Bewerte die Fakten")
            return "Wirtschaftliche Bewertung"
        c = Coordinator("Geschäftsidee", fake)
        result = await c.run({"Scout": "Recherchiere"})
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["delegations"], 1)
        self.assertEqual(result["agent_runs"], 2)
        self.assertIn("Wirtschaftliche Bewertung", result["results"][0]["output"])
        self.assertIn("agent_message", [e["type"] for e in result["events"]])

    async def test_parallel_roots(self):
        current = peak = 0
        async def fake(item, prompt, delegate, turns):
            nonlocal current, peak
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(.03)
            current -= 1
            return "OK"
        c = Coordinator("Ziel", fake, Limits(max_parallel_roots=2))
        r = await c.run({"Scout": "A", "Mirjana": "B", "Milorad": "C"})
        self.assertEqual(peak, 2)
        self.assertEqual(r["status"], "COMPLETED")

    async def test_depth_guard(self):
        async def fake(item, prompt, delegate, turns):
            return await delegate(item, "Mirjana" if item.agent == "Scout" else "Scout", "Weiter")
        c = Coordinator("Ziel", fake, Limits(max_depth=1))
        r = await c.run({"Scout": "Start"})
        self.assertEqual(r["agent_runs"], 2)
        self.assertIn("DELEGATION_REJECTED", r["results"][0]["output"])

    async def test_timeout(self):
        async def fake(item, prompt, delegate, turns):
            await asyncio.sleep(1)
            return "late"
        c = Coordinator("Ziel", fake, Limits(timeout_seconds=.02))
        r = await c.run({"Scout": "Start"})
        self.assertEqual(r["status"], "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
