"""Keeps a public deployment's model spend bounded.

- **Answer cache.** The same question to the same workspace replays the last answer's events (for a day), so a demo
  question asked a hundred times costs one answer. Replays keep a short pause between events, so the answer still
  arrives sentence by sentence.
- **Per visitor.** At most `CANON_ASK_PER_HOUR` new answers per client address per hour.
- **Per day.** At most `CANON_ASK_PER_DAY` new answers across everyone.

Cached answers count against neither limit. State is in memory: one API process, reset on restart.
"""

import asyncio
import os
import time
from collections import OrderedDict, deque

from fastapi import Request

CACHE_SECONDS = 24 * 3600


def _env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def client_address(request: Request) -> str:
    # Behind Caddy (and Traefik) the visitor is the first address in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def normalise(question: str) -> str:
    return " ".join(question.lower().replace("?", " ").split())


class Limits:
    def __init__(self, per_hour: int | None = None, per_day: int | None = None, cache_size: int = 500):
        self.per_hour = per_hour if per_hour is not None else _env("CANON_ASK_PER_HOUR", 20)
        self.per_day = per_day if per_day is not None else _env("CANON_ASK_PER_DAY", 400)
        self.cache: OrderedDict[tuple[str, str], tuple[float, list[dict]]] = OrderedDict()
        self.cache_size = cache_size
        self.visitors: dict[str, deque[float]] = {}
        self.today: deque[float] = deque()

    def cached(self, ws: str, question: str) -> list[dict] | None:
        hit = self.cache.get((ws, normalise(question)))
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        return None

    def store(self, ws: str, question: str, events: list[dict]) -> None:
        if not events or events[-1].get("type") not in ("done", "empty"):
            return  # only finished answers are worth replaying
        key = (ws, normalise(question))
        self.cache[key] = (time.time(), events)
        self.cache.move_to_end(key)
        while len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)

    def refusal(self, address: str) -> str | None:
        """A reason to refuse a new answer, or None and the answer is counted."""
        now = time.time()
        while self.today and now - self.today[0] > 24 * 3600:
            self.today.popleft()
        recent = self.visitors.setdefault(address, deque())
        while recent and now - recent[0] > 3600:
            recent.popleft()
        if len(self.today) >= self.per_day:
            return "Canon has answered as many new questions as it will today. Try one of the suggested questions."
        if len(recent) >= self.per_hour:
            return "That is a lot of questions in one hour. Try again a little later, or try a suggested question."
        recent.append(now)
        self.today.append(now)
        return None


async def replay(events: list[dict]):
    for event in events:
        if event.get("type") in ("claim", "verdict"):
            await asyncio.sleep(0.12)
        yield event
