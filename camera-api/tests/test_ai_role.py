"""AI_ROLE: AI alohida ai-worker konteynerida (deploy/docker-compose.ai-worker.yml)."""

import asyncio

from app import main


class TestWorkerWaitsForTheLock:
    async def test_worker_retries_until_the_lock_is_free(self, monkeypatch):
        attempts = {"n": 0}
        started: list[bool] = []

        async def busy_twice():
            attempts["n"] += 1
            return attempts["n"] >= 3

        async def no_sync():
            return None

        monkeypatch.setattr(main, "try_become_leader", busy_twice)
        monkeypatch.setattr(main, "_sync_streams_once", no_sync)
        monkeypatch.setattr(main, "_start_ai_loops", lambda tasks: started.append(True))
        monkeypatch.setattr(main.settings, "ai_worker_lock_retry_seconds", 0)
        monkeypatch.setitem(main._leader_state, "is_leader", False)

        tasks: list = []
        await asyncio.wait_for(main._become_leader_when_free(tasks), timeout=5)
        await asyncio.gather(*tasks)
        assert attempts["n"] == 3
        assert started == [True]
        assert main._leader_state["is_leader"] is True
