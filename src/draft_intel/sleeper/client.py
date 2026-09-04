"""Async Sleeper client.

Sleeper's documented limit is 1000 calls per minute per IP, and exceeding it risks an IP
block - which on draft night is unrecoverable. A 1 second floor on a single polled endpoint
is 60/min, roughly a 16x safety margin, and the floor is enforced here rather than left to
callers to remember.

The circuit breaker exists because the failure that matters is not one bad response, it is
hammering a struggling API until we get blocked. After repeated failures the client stops
trying for a cooldown and the UI shows a connection banner, which is the correct behaviour:
the last known state stays on screen and stays usable.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

API_V1 = "https://api.sleeper.app/v1"
API_INTERNAL = "https://api.sleeper.com"
MIN_POLL_INTERVAL = 1.0


class CircuitOpen(Exception):
    """Raised while the breaker is open; callers should serve last known state."""


@dataclass
class Breaker:
    threshold: int = 5
    cooldown: float = 30.0
    failures: int = 0
    opened_at: float | None = None

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self, now: float | None = None) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = now if now is not None else time.monotonic()

    def is_open(self, now: float | None = None) -> bool:
        if self.opened_at is None:
            return False
        current = now if now is not None else time.monotonic()
        if current - self.opened_at >= self.cooldown:
            self.failures = 0
            self.opened_at = None
            return False
        return True


@dataclass
class SleeperClient:
    """Read-only client for the public and internal Sleeper APIs.

    Never attempts Sleeper's internal websocket or GraphQL channel. That is out of scope by
    charter: it is unstable, likely against terms of service, and a failure there on draft
    day would be unrecoverable.
    """

    client: httpx.AsyncClient
    timeout: float = 10.0
    max_retries: int = 3
    backoff_base: float = 0.5
    breaker: Breaker = field(default_factory=Breaker)
    _last_request: float | None = None
    _gate: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def _throttle(self) -> None:
        """Hold every caller to one request per second, globally.

        Two defects are closed here. The lock makes the floor hold under concurrency -- four
        concurrent calls previously fired three of them simultaneously, degrading the floor to
        one-second-per-burst. And callers now throttle before *each* attempt rather than once
        per logical call, so a retry storm cannot exceed the floor: retries were sleeping
        0.5s and 1.0s of backoff and issuing requests 502ms apart, which is exactly when an
        IP block is most likely and most unrecoverable.

        ``None`` rather than ``0.0`` marks "no request yet", so the first call is not gated by
        a truthiness test on a monotonic timestamp.
        """
        async with self._gate:
            if self._last_request is not None:
                elapsed = time.monotonic() - self._last_request
                if elapsed < MIN_POLL_INTERVAL:
                    await asyncio.sleep(MIN_POLL_INTERVAL - elapsed)
            self._last_request = time.monotonic()

    async def get_json(self, url: str, *, throttle: bool = True) -> Any:
        """GET with retries, exponential backoff and breaker accounting.

        Retries on timeouts, transport errors and 5xx/429. A 404 is returned as ``None``
        rather than retried - it is an answer, not a failure, and the undocumented endpoints
        are allowed to simply not exist.
        """
        if self.breaker.is_open():
            raise CircuitOpen(f"circuit open, not calling {url}")

        last: Exception | None = None
        for attempt in range(self.max_retries):
            if throttle:
                await self._throttle()
            try:
                response = await self.client.get(url, timeout=self.timeout)
                if response.status_code == 404:
                    # An answer, not a failure: the undocumented endpoints are allowed not to
                    # exist. Deliberately does NOT clear the breaker - a 404 from
                    # api.sleeper.com must not reset the failure count for the v1 endpoints.
                    return None
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"{response.status_code} from {url}",
                        request=response.request,
                        response=response,
                    )
                # A 4xx other than 404 is a request we got wrong. Retrying cannot fix it and
                # only spends rate budget, so it fails immediately without breaker credit.
                if response.status_code >= 400:
                    response.raise_for_status()
                self.breaker.record_success()
                return response.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 and exc.response.status_code != 429:
                    raise
                last = exc
            except httpx.TransportError as exc:
                last = exc
            if attempt < self.max_retries - 1:
                await asyncio.sleep(self.backoff_base * (2**attempt))
        self.breaker.record_failure()
        if last is None:  # pragma: no cover - defensive; the loop always sets it
            raise RuntimeError(f"retries exhausted for {url} with no recorded error")
        raise last

    # -- endpoints -----------------------------------------------------------

    async def user(self, username: str) -> Any:
        return await self.get_json(f"{API_V1}/user/{username}")

    async def leagues(self, user_id: str, season: str) -> Any:
        return await self.get_json(f"{API_V1}/user/{user_id}/leagues/nfl/{season}")

    async def league(self, league_id: str) -> Any:
        return await self.get_json(f"{API_V1}/league/{league_id}")

    async def rosters(self, league_id: str) -> Any:
        return await self.get_json(f"{API_V1}/league/{league_id}/rosters")

    async def users(self, league_id: str) -> Any:
        return await self.get_json(f"{API_V1}/league/{league_id}/users")

    async def draft(self, draft_id: str) -> Any:
        return await self.get_json(f"{API_V1}/draft/{draft_id}")

    async def picks(self, draft_id: str) -> Any:
        """The core feed. Settled picks only - there is no public feed for a live nomination."""
        return await self.get_json(f"{API_V1}/draft/{draft_id}/picks")

    async def players(self) -> Any:
        """~15MB. Cache once per day; never call this on a poll cycle."""
        return await self.get_json(f"{API_V1}/players/nfl")

    async def projections(self, season: str, positions: list[str]) -> Any:
        """Undocumented endpoint. No feature may hard-depend on it returning anything."""
        query = "&".join(f"position[]={p}" for p in positions)
        return await self.get_json(
            f"{API_INTERNAL}/projections/nfl/{season}?season_type=regular&{query}"
        )
