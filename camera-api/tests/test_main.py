import asyncio

from app.main import _staggered


class TestStaggered:
    async def test_zero_delay_calls_immediately_without_sleeping(self, monkeypatch):
        slept = {"called": False}

        async def fake_sleep(seconds):
            slept["called"] = True

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        called = {"n": 0}

        async def marker():
            called["n"] += 1

        await _staggered(0, marker())
        assert called["n"] == 1
        assert slept["called"] is False

    async def test_positive_delay_sleeps_before_calling(self, monkeypatch):
        events: list[str] = []

        async def fake_sleep(seconds):
            events.append(f"sleep:{seconds}")

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        async def marker():
            events.append("called")

        await _staggered(4.0, marker())
        assert events == ["sleep:4.0", "called"]

    async def test_a_failing_loop_coroutine_still_propagates(self):
        async def failing():
            raise RuntimeError("simulated loop crash")

        try:
            await _staggered(0, failing())
            assert False, "expected RuntimeError to propagate"
        except RuntimeError:
            pass
