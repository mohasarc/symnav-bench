from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path


LIMIT_MARKERS: tuple[str, ...] = (
    "rate limit",
    "usage limit",
    "try again",
    "too many requests",
    "quota exceeded",
)


def find_limit_marker(jobs_dir: Path) -> str | None:
    if not jobs_dir.exists():
        return None
    for path in sorted(jobs_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lowered = text.lower()
        for marker in LIMIT_MARKERS:
            if marker in lowered:
                return text
    return None


def parse_limit_reset(text: str, now: datetime) -> datetime | None:
    match = re.search(r"try again at\s+(\d{1,2}):(\d{2})\s*(AM|PM)\s*UTC", text, re.I)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    suffix = match.group(3).upper()
    if suffix == "PM" and hour != 12:
        hour += 12
    if suffix == "AM" and hour == 12:
        hour = 0
    reset = now.astimezone(UTC).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset <= now.astimezone(UTC):
        reset += timedelta(days=1)
    return reset


def next_backoff(previous: list[timedelta]) -> timedelta:
    sequence = [timedelta(minutes=5), timedelta(minutes=10), timedelta(minutes=20)]
    if len(previous) < len(sequence):
        return sequence[len(previous)]
    return sequence[-1]
