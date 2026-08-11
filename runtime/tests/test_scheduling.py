from datetime import datetime, timezone

import pytest

from yozhan_runtime.scheduling.cron import CronError, matches, parse
from yozhan_runtime.scheduling.scheduler import Scheduler, due_agents, load_scheduled_agents

# 2026-08-12 is a Wednesday (cron day-of-week 3).
WED_0800 = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)


# --- cron parsing -----------------------------------------------------------


def test_wildcard_expands_to_the_full_range():
    minute, *_ = parse("* * * * *")
    assert minute == set(range(60))


def test_list_and_range_and_step():
    assert parse("1,2 * * * *")[0] == {1, 2}
    assert parse("1-4 * * * *")[0] == {1, 2, 3, 4}
    assert parse("*/15 * * * *")[0] == {0, 15, 30, 45}
    assert parse("0-30/10 * * * *")[0] == {0, 10, 20, 30}


@pytest.mark.parametrize("expr", ["* * * *", "* * * * * *", "99 * * * *", "* 25 * * *", "a * * * *", "5-1 * * * *"])
def test_malformed_expressions_are_rejected(expr):
    with pytest.raises(CronError):
        parse(expr)


def test_daily_at_0800_matches_only_at_that_minute():
    assert matches("0 8 * * *", WED_0800)
    assert not matches("0 8 * * *", WED_0800.replace(minute=1))
    assert not matches("0 8 * * *", WED_0800.replace(hour=9))


def test_day_of_week_uses_cron_numbering_with_sunday_zero():
    assert matches("0 8 * * 3", WED_0800)  # Wednesday
    assert not matches("0 8 * * 0", WED_0800)  # Sunday
    sunday = datetime(2026, 8, 16, 8, 0, tzinfo=timezone.utc)
    assert matches("0 8 * * 0", sunday)


def test_every_fifteen_minutes():
    assert matches("*/15 * * * *", WED_0800.replace(minute=30))
    assert not matches("*/15 * * * *", WED_0800.replace(minute=31))


# --- loading agents ---------------------------------------------------------


CONFIG = {
    "agents": {
        "chat": {"mode": "on-demand"},
        "digest": {"mode": "scheduled", "schedule": "0 8 * * *", "task": "summarize"},
        "watcher": {"mode": "continuous", "interval_seconds": 900, "task": "watch"},
        "broken": {"mode": "scheduled", "schedule": "not a cron", "task": "x"},
        "taskless": {"mode": "scheduled", "schedule": "0 8 * * *"},
        "scheduleless": {"mode": "scheduled", "task": "x"},
    }
}


def test_only_scheduled_and_continuous_agents_are_loaded():
    names = {a.name for a in load_scheduled_agents(CONFIG)}
    assert names == {"digest", "watcher"}


def test_misconfigured_agents_are_skipped_not_fatal():
    # A bad schedule shouldn't stop the other agents from running.
    loaded = load_scheduled_agents(CONFIG)
    assert all(a.name not in {"broken", "taskless", "scheduleless"} for a in loaded)


def test_continuous_interval_is_read_from_config():
    watcher = next(a for a in load_scheduled_agents(CONFIG) if a.name == "watcher")
    assert watcher.interval_seconds == 900


# --- due calculation --------------------------------------------------------


def test_scheduled_agent_is_due_only_when_cron_matches():
    agents = load_scheduled_agents({"agents": CONFIG["agents"]})
    digest = [a for a in agents if a.name == "digest"]
    assert [a.name for a in due_agents(digest, WED_0800, 0)] == ["digest"]
    assert due_agents(digest, WED_0800.replace(hour=9), 0) == []


def test_continuous_agent_runs_immediately_then_waits_its_interval():
    agents = [a for a in load_scheduled_agents(CONFIG) if a.name == "watcher"]
    assert due_agents(agents, WED_0800, 0) == agents

    agents[0].last_run = 0.0
    assert due_agents(agents, WED_0800, 100) == []       # too soon
    assert due_agents(agents, WED_0800, 900) == agents   # interval elapsed


# --- scheduler tick ---------------------------------------------------------


class FakeOrchestrator:
    def __init__(self, fail: set[str] | None = None, raise_for: set[str] | None = None):
        self.dispatched: list[tuple[str, str, str]] = []
        self.fail = fail or set()
        self.raise_for = raise_for or set()

    def dispatch(self, agent_name, task, session_id=None):
        if agent_name in self.raise_for:
            raise RuntimeError("agent blew up")
        self.dispatched.append((agent_name, task, session_id))

        class Result:
            error = "failed" if agent_name in self.fail else None

        return Result()


def test_tick_dispatches_due_agents_with_their_configured_task():
    orchestrator = FakeOrchestrator()
    scheduler = Scheduler(orchestrator, {"agents": {"digest": CONFIG["agents"]["digest"]}})

    dispatched = scheduler.tick(now=WED_0800, monotonic=0)

    assert dispatched == ["digest"]
    assert orchestrator.dispatched == [("digest", "summarize", "scheduled:digest")]


def test_tick_skips_agents_that_are_not_due():
    orchestrator = FakeOrchestrator()
    scheduler = Scheduler(orchestrator, {"agents": {"digest": CONFIG["agents"]["digest"]}})
    assert scheduler.tick(now=WED_0800.replace(hour=3), monotonic=0) == []


def test_one_raising_agent_does_not_stop_the_others():
    orchestrator = FakeOrchestrator(raise_for={"a"})
    config = {
        "agents": {
            "a": {"mode": "continuous", "task": "boom", "interval_seconds": 1},
            "b": {"mode": "continuous", "task": "fine", "interval_seconds": 1},
        }
    }
    scheduler = Scheduler(orchestrator, config)

    scheduler.tick(now=WED_0800, monotonic=0)

    assert [name for name, _, _ in orchestrator.dispatched] == ["b"]


def test_a_failing_dispatch_is_still_recorded_as_run():
    # Otherwise a persistently failing agent would retry every single tick.
    orchestrator = FakeOrchestrator(fail={"watcher"})
    scheduler = Scheduler(orchestrator, {"agents": {"watcher": CONFIG["agents"]["watcher"]}})

    scheduler.tick(now=WED_0800, monotonic=0)
    assert scheduler.tick(now=WED_0800, monotonic=10) == []
