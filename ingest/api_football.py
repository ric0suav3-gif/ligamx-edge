from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import requests
from dotenv import load_dotenv


class APIFootballError(RuntimeError):
    """Raised when API-Football returns an HTTP or API-level error."""


@dataclass(frozen=True)
class APIResponse:
    endpoint: str
    parameters: Mapping[str, Any]
    results: int
    response: list[Any]
    paging: Mapping[str, Any]
    raw: Mapping[str, Any]


class APIFootballClient:
    """Small, explicit wrapper around API-Football v3.

    The key is read from API_FOOTBALL_KEY by default and is sent only in the
    x-apisports-key header. It is never written to disk by this client.

    The client deliberately throttles requests and retries HTTP 429 / transient
    5xx responses so historical backfills can run safely against per-minute
    provider limits.
    """

    RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        session: requests.Session | None = None,
        min_interval: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        env_path = Path(__file__).resolve().parents[1] / ".env"
        load_dotenv(dotenv_path=env_path, override=False)
        self.api_key = api_key or os.getenv("API_FOOTBALL_KEY")
        self.base_url = (
            base_url
            or os.getenv("API_FOOTBALL_BASE_URL")
            or "https://v3.football.api-sports.io"
        ).rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

        configured_interval = os.getenv("API_FOOTBALL_MIN_INTERVAL", "0.40")
        configured_retries = os.getenv("API_FOOTBALL_MAX_RETRIES", "6")
        self.min_interval = (
            float(configured_interval) if min_interval is None else float(min_interval)
        )
        self.max_retries = (
            int(configured_retries) if max_retries is None else int(max_retries)
        )
        self._last_request_started = 0.0

        if not self.api_key:
            raise APIFootballError(
                f"Missing API_FOOTBALL_KEY. Run scripts/setup_api_football_env.sh "
                f"or add it to {env_path}."
            )

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_started
        remaining = self.min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    @staticmethod
    def _retry_delay(response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(1.0, float(retry_after))
            except ValueError:
                pass

        if response.status_code == 429:
            return min(60.0, 8.0 * (attempt + 1))

        return min(30.0, 2.0 ** attempt)

    def get(self, endpoint: str, **params: Any) -> APIResponse:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        response: requests.Response | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            self._last_request_started = time.monotonic()

            response = self.session.get(
                url,
                params=clean,
                headers={"x-apisports-key": self.api_key},
                timeout=self.timeout,
            )

            if response.status_code not in self.RETRYABLE_STATUS:
                break

            if attempt >= self.max_retries:
                break

            delay = self._retry_delay(response, attempt)
            print(
                f"API-Football HTTP {response.status_code} on {endpoint}; "
                f"waiting {delay:.0f}s then retrying "
                f"({attempt + 1}/{self.max_retries})..."
            )
            time.sleep(delay)

        if response is None:
            raise APIFootballError(f"No response received from {endpoint}")

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise APIFootballError(
                f"HTTP {response.status_code} from {endpoint}: {response.text[:500]}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise APIFootballError(f"Non-JSON response from {endpoint}") from exc

        errors = payload.get("errors")
        if errors:
            raise APIFootballError(f"API-Football error from {endpoint}: {errors}")

        return APIResponse(
            endpoint=endpoint,
            parameters=payload.get("parameters", clean),
            results=int(payload.get("results", 0) or 0),
            response=list(payload.get("response", [])),
            paging=payload.get("paging", {}),
            raw=payload,
        )

    def leagues(self, **params: Any) -> APIResponse:
        return self.get("leagues", **params)

    def teams(self, **params: Any) -> APIResponse:
        return self.get("teams", **params)

    def fixtures(self, **params: Any) -> APIResponse:
        return self.get("fixtures", **params)

    def fixture_statistics(self, fixture_id: int) -> APIResponse:
        return self.get("fixtures/statistics", fixture=fixture_id)

    def fixture_lineups(self, fixture_id: int) -> APIResponse:
        return self.get("fixtures/lineups", fixture=fixture_id)

    def injuries(self, **params: Any) -> APIResponse:
        return self.get("injuries", **params)

    def odds(self, **params: Any) -> APIResponse:
        return self.get("odds", **params)
