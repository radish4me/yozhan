"""Runs the agents that aren't driven by a user message: `mode: scheduled`
agents on a cron expression, and `mode: continuous` agents on a fixed
interval. Both dispatch through the same Orchestrator as everything else, so
a scheduled agent gets the same model assignment, skills, memory, sandbox
policy, and trace logging as an interactive one.

The loop ticks once a minute (cron's resolution). due_agents() is separated
from the loop so scheduling decisions are testable without waiting on wall
-clock time.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from yozhan_runtime.scheduling.cron import CronError, matches

logger = logging.getLogger(__name__)

TICK_SECONDS = 60
DEFAULT_CONTINUOUS_INTERVAL = 300


@dataclass
class ScheduledAgent:
    name: str
    mode: str
    task: str
    schedule: str | None = None
    interval_seconds: int = DEFAULT_CONTINUOUS_INTERVAL
    last_run: float | None = None


def load_scheduled_agents(agents_config: dict) -> list[ScheduledAgent]:
    """Every agent in config/agents.yaml whose mode is scheduled or continuous."""
    out: list[ScheduledAgent] = []
    for name, spec in (agents_config.get("agents", {}) or {}).items():
        mode = spec.get("mode", "on-demand")
        if mode not in ("scheduled", "continuous"):
            continue
        task = spec.get("task")
        if not task:
            logger.warning("agent '%s' is %s but has no `task:` to run — skipping", name, mode)
            continue
        if mode == "scheduled":
            schedule = spec.get("schedule")
            if not schedule:
                logger.warning("scheduled agent '%s' has no `schedule:` — skipping", name)
                continue
            try:
                matches(schedule, datetime.now(timezone.utc))
            except CronError as exc:
                logger.warning("scheduled agent '%s' has an invalid schedule (%s) — skipping", name, exc)
                continue
            out.append(ScheduledAgent(name=name, mode=mode, task=task, schedule=schedule))
        else:
            out.append(
                ScheduledAgent(
                    name=name,
                    mode=mode,
                    task=task,
                    interval_seconds=int(spec.get("interval_seconds", DEFAULT_CONTINUOUS_INTERVAL)),
                )
            )
    return out


def due_agents(
    agents: list[ScheduledAgent], now: datetime, monotonic: float
) -> list[ScheduledAgent]:
    """Which agents should run at this tick. Continuous agents fire
    immediately on first tick, then every interval_seconds."""
    due = []
    for agent in agents:
        if agent.mode == "scheduled":
            if agent.schedule and matches(agent.schedule, now):
                due.append(agent)
        elif agent.last_run is None or (monotonic - agent.last_run) >= agent.interval_seconds:
            due.append(agent)
    return due


class Scheduler:
    def __init__(self, orchestrator, agents_config: dict):
        self.orchestrator = orchestrator
        self.agents = load_scheduled_agents(agents_config)

    def tick(self, now: datetime | None = None, monotonic: float | None = None) -> list[str]:
        """Runs everything due right now. Returns the agent names dispatched."""
        now = now or datetime.now(timezone.utc)
        monotonic = time.monotonic() if monotonic is None else monotonic

        dispatched = []
        for agent in due_agents(self.agents, now, monotonic):
            agent.last_run = monotonic
            try:
                result = self.orchestrator.dispatch(agent.name, agent.task, session_id=f"scheduled:{agent.name}")
                if result.error:
                    logger.warning("scheduled agent '%s' failed: %s", agent.name, result.error)
                dispatched.append(agent.name)
            except Exception as exc:
                # A misbehaving scheduled agent must not take the whole loop down.
                logger.exception("scheduled agent '%s' raised: %s", agent.name, exc)
        return dispatched

    def run_forever(self) -> None:
        if not self.agents:
            # Idle rather than exit. Under a process supervisor (systemd,
            # Docker `restart: unless-stopped`) exiting here would produce a
            # restart loop over what is really just an empty config.
            logger.warning(
                "no scheduled or continuous agents configured — idling. "
                "Add one with mode: scheduled to config/agents.yaml and restart."
            )
        else:
            logger.info("scheduler started with %d agent(s)", len(self.agents))
        while True:
            self.tick()
            time.sleep(TICK_SECONDS)
