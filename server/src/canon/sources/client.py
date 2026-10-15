"""The HTTP client every API connector shares: retries, rate limits, and errors a person can act on.

- A 429 (or a source's own rate-limit signal) waits out the `Retry-After` the service sends, up to `max_wait`
  seconds a time and `wait_budget` seconds a sync. Past that the sync stops with a clear message, and the next
  scheduled sync carries on from the cursor the last good sync left.
- A 5xx or a dropped connection is retried with backoff, a few times.
- Anything else that is not a success raises `SourceError`, whose `public_message` says what to do in words, with no
  URL or token in it. Jobs show that message as is.

Tokens go in headers only and are never logged or put in an error. `sleep` is injectable so tests never wait.
"""

import random
import time
from collections.abc import Callable
from typing import Any

import httpx


class SourceError(Exception):
    """A failure to show a person as is. `str(e)` is safe: it never carries a token or a URL with a secret."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.public_message = message
        self.status = status


class Client:
    def __init__(
        self,
        name: str,
        *,
        http: Callable[[], httpx.Client] | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_wait: float = 60.0,
        wait_budget: float = 300.0,
        retries: int = 4,
        rate_limited: Callable[[httpx.Response], float | None] | None = None,
    ):
        self.name = name  # "Slack": how errors name the service
        self._http = http or (lambda: httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0)))
        self._client: httpx.Client | None = None
        self.headers = {"User-Agent": "canon", **(headers or {})}
        self.auth = auth
        self.sleep = sleep
        self.max_wait = max_wait
        self.wait_budget = wait_budget
        self.waited = 0.0
        self.retries = retries
        self.rate_limited = rate_limited
        self.calls = 0

    def _c(self) -> httpx.Client:
        if self._client is None:
            self._client = self._http()
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _wait(self, seconds: float) -> None:
        seconds = max(0.0, seconds)
        if seconds > self.max_wait or self.waited + seconds > self.wait_budget:
            raise SourceError(f"{self.name} is rate limiting Canon. The next sync will carry on from here.", status=429)
        self.waited += seconds
        self.sleep(seconds)

    def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        """One request, retried on rate limits and server errors. Returns any response below 500 that is not a
        rate limit; the caller decides what a 4xx means."""
        headers = {**self.headers, **kw.pop("headers", {})}
        for attempt in range(self.retries + 1):
            try:
                self.calls += 1
                r = self._c().request(method, url, headers=headers, auth=self.auth, **kw)
            except httpx.TransportError:
                if attempt == self.retries:
                    raise SourceError(f"{self.name} could not be reached. Try again in a moment.") from None
                self._wait(min(30.0, 2**attempt) + random.random())
                continue
            wait = self.rate_limited(r) if self.rate_limited else None
            if wait is None and r.status_code == 429:
                wait = retry_after(r)
            if wait is not None:
                if attempt == self.retries:
                    raise SourceError(f"{self.name} is rate limiting Canon. The next sync will carry on from here.", status=429)
                self._wait(wait)
                continue
            if r.status_code >= 500:
                if attempt == self.retries:
                    raise SourceError(f"{self.name} did not answer. Try again in a moment.", status=r.status_code)
                self._wait(min(30.0, 2**attempt) + random.random())
                continue
            return r
        raise SourceError(f"{self.name} did not answer. Try again in a moment.")  # pragma: no cover

    def json(self, method: str, url: str, *, ok: tuple[int, ...] = (200,), **kw: Any) -> Any:
        """The JSON body of a successful response; `SourceError` for anything else."""
        r = self.request(method, url, **kw)
        if r.status_code not in ok:
            raise status_error(self.name, r.status_code)
        try:
            return r.json()
        except ValueError:
            raise SourceError(f"{self.name} sent an answer Canon could not read.", status=r.status_code) from None


def retry_after(r: httpx.Response, default: float = 5.0) -> float:
    value = r.headers.get("retry-after")
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def status_error(name: str, status: int) -> SourceError:
    if status == 401:
        return SourceError(f"{name} did not accept the token. Check it, or make a new one.", status=status)
    if status == 403:
        return SourceError(f"{name} refused access. The token is missing a permission Canon needs.", status=status)
    if status == 404:
        return SourceError(f"{name} could not find what Canon asked for. Check the address and permissions.", status=status)
    return SourceError(f"{name} answered with an error ({status}). Try again in a moment.", status=status)


def capped(config: dict, key: str, default: int, hard_max: int) -> int:
    """A volume cap from the connection's config, between 1 and `hard_max`."""
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, hard_max))
