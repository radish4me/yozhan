"""A minimal 5-field cron matcher — no new dependency for what is, in the end,
five integer set-membership tests.

    ┌─ minute (0-59)
    │ ┌─ hour (0-23)
    │ │ ┌─ day of month (1-31)
    │ │ │ ┌─ month (1-12)
    │ │ │ │ ┌─ day of week (0-6, Sunday = 0)
    * * * * *

Supports `*`, `N`, `A-B` ranges, `A,B,C` lists, and `*/N` or `A-B/N` steps.
Deliberately does NOT support @reboot/@daily aliases or seconds — an agent
schedule that needs sub-minute precision wants a continuous agent instead.
"""

from __future__ import annotations

from datetime import datetime

FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


class CronError(ValueError):
    pass


def _parse_field(field: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"empty element in cron field {field!r}")

        step = 1
        if "/" in part:
            part, _, raw_step = part.partition("/")
            if not raw_step.isdigit() or int(raw_step) < 1:
                raise CronError(f"invalid step in {field!r}")
            step = int(raw_step)

        if part == "*":
            start, end = low, high
        elif "-" in part:
            raw_start, _, raw_end = part.partition("-")
            if not (raw_start.isdigit() and raw_end.isdigit()):
                raise CronError(f"invalid range in {field!r}")
            start, end = int(raw_start), int(raw_end)
        elif part.isdigit():
            start = end = int(part)
        else:
            raise CronError(f"invalid cron element {part!r}")

        if start < low or end > high or start > end:
            raise CronError(f"cron element {part!r} out of range {low}-{high}")
        values.update(range(start, end + 1, step))
    return values


def parse(expression: str) -> list[set[int]]:
    fields = expression.split()
    if len(fields) != 5:
        raise CronError(f"expected 5 cron fields, got {len(fields)}: {expression!r}")
    return [_parse_field(field, low, high) for field, (low, high) in zip(fields, FIELD_RANGES)]


def matches(expression: str, when: datetime) -> bool:
    minute, hour, dom, month, dow = parse(expression)
    # cron uses Sunday = 0; Python's weekday() uses Monday = 0.
    weekday = (when.weekday() + 1) % 7
    return (
        when.minute in minute
        and when.hour in hour
        and when.day in dom
        and when.month in month
        and weekday in dow
    )
