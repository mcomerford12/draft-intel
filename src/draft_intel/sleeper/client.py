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
    _last_request: float = 0.0

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < MIN_POLL_INTERVAL and self._last_request:
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
        if throttle:
            await self._throttle()

        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await self.client.get(url, timeout=self.timeout)
                if response.status_code == 404:
                    self.breaker.record_success()
                    return None
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"{response.status_code} from {url}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                self.breaker.record_success()
                return response.json()
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last = exc
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.backoff_base * (2**attempt))
        self.breaker.record_failure()
        assert last is not None
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
