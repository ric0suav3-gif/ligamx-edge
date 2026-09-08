from __future__ import annotations

import os
from dataclasses import dataclass
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
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        load_dotenv()
        self.api_key = api_key or os.getenv("API_FOOTBALL_KEY")
        self.base_url = (
            base_url
            or os.getenv("API_FOOTBALL_BASE_URL")
            or "https://v3.football.api-sports.io"
        ).rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

        if not self.api_key:
            raise APIFootballError(
                "Missing API_FOOTBALL_KEY. Copy .env.example to .env and add the key locally."
            )

    def get(self, endpoint: str, **params: Any) -> APIResponse:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = self.session.get(
            url,
            params=clean,
            headers={"x-apisports-key": self.api_key},
            timeout=self.timeout,
        )

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
