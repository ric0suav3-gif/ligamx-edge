from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv

DEFAULT_BASE_URL = "https://v1.american-football.api-sports.io"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class APINFLError(RuntimeError):
    pass


@dataclass(frozen=True)
class APIResponse:
    response: list[Any]
    results: int | None
    paging: dict[str, Any]
    parameters: dict[str, Any]
    rate_limits: dict[str, int | None]
    raw: dict[str, Any]


class APINFLClient:
    """Thin, defensive API-Sports NFL client.

    The API key is read from NFL_API_KEY and is only sent in x-apisports-key.
    Never embed the key in browser code or commit it to Git.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        min_interval: float | None = None,
        max_retries: int | None = None,
        timeout: float = 30.0,
    ) -> None:
        load_dotenv()
        self.api_key = api_key or os.getenv("NFL_API_KEY")
        if not self.api_key:
            raise APINFLError(
                "Missing NFL_API_KEY. Put it in your local .env; do not paste it into chat or commit it."
            )

        self.base_url = (
            base_url or os.getenv("NFL_API_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.min_interval = (
            float(min_interval)
            if min_interval is not None
            else float(os.getenv("NFL_API_MIN_INTERVAL", "0.25"))
        )
        self.max_retries = (
            int(max_retries)
            if max_retries is not None
            else int(os.getenv("NFL_API_MAX_RETRIES", "6"))
        )
        self.timeout = timeout
        self._last_call = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "x-apisports-key": self.api_key,
                "Accept": "application/json",
                "User-Agent": "nfl-edge/0.1",
            }
        )

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _retry_delay(response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        if response.status_code == 429:
            return min(60.0, 8.0 * (2 ** attempt))
        return min(30.0, 1.5 * (2 ** attempt))

    @staticmethod
    def _provider_errors(payload: dict[str, Any]) -> list[str]:
        errors = payload.get("errors")
        if not errors:
            return []
        if isinstance(errors, dict):
            return [f"{key}: {value}" for key, value in errors.items()]
        if isinstance(errors, list):
            return [str(value) for value in errors if value]
        return [str(errors)]

    def get(self, path: str, **params: Any) -> APIResponse:
        clean_params = {
            key: value
            for key, value in params.items()
            if value is not None and value != ""
        }
        url = f"{self.base_url}/{path.lstrip('/')}"

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(
                    url,
                    params=clean_params,
                    timeout=self.timeout,
                )
                self._last_call = time.monotonic()
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise APINFLError(f"Request failed: {exc}") from exc
                time.sleep(min(30.0, 1.5 * (2 ** attempt)))
                continue

            if resp.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                time.sleep(self._retry_delay(resp, attempt))
                continue

            if not resp.ok:
                raise APINFLError(
                    f"HTTP {resp.status_code} for {resp.url}: {resp.text[:500]}"
                )

            try:
                payload = resp.json()
            except ValueError as exc:
                raise APINFLError(
                    f"Non-JSON response for {resp.url}: {resp.text[:500]}"
                ) from exc

            if not isinstance(payload, dict):
                raise APINFLError(
                    f"Unexpected payload type {type(payload).__name__} for {resp.url}"
                )

            provider_errors = self._provider_errors(payload)
            if provider_errors:
                raise APINFLError("; ".join(provider_errors))

            response = payload.get("response")
            if response is None:
                response = []
            if not isinstance(response, list):
                response = [response]

            def header_int(name: str) -> int | None:
                value = resp.headers.get(name)
                try:
                    return None if value is None else int(value)
                except ValueError:
                    return None

            return APIResponse(
                response=response,
                results=payload.get("results"),
                paging=payload.get("paging") or {},
                parameters=payload.get("parameters") or {},
                rate_limits={
                    "daily_limit": header_int("x-ratelimit-requests-limit"),
                    "daily_remaining": header_int("x-ratelimit-requests-remaining"),
                    "minute_limit": header_int("X-RateLimit-Limit"),
                    "minute_remaining": header_int("X-RateLimit-Remaining"),
                },
                raw=payload,
            )

        raise APINFLError(f"Request failed: {last_error or 'unknown error'}")

    def status(self) -> APIResponse:
        return self.get("status")

    def leagues(self, **params: Any) -> APIResponse:
        return self.get("leagues", **params)

    def teams(self, **params: Any) -> APIResponse:
        return self.get("teams", **params)

    def games(self, **params: Any) -> APIResponse:
        return self.get("games", **params)

    def game_events(self, game_id: int | str) -> APIResponse:
        return self.get("games/events", id=game_id)

    def team_game_statistics(
        self, game_id: int | str, team: int | None = None
    ) -> APIResponse:
        return self.get("games/statistics/teams", id=game_id, team=team)

    def player_game_statistics(
        self,
        game_id: int | str,
        team: int | None = None,
        player: int | None = None,
        group: str | None = None,
    ) -> APIResponse:
        return self.get(
            "games/statistics/players",
            id=game_id,
            team=team,
            player=player,
            group=group,
        )

    def players(self, **params: Any) -> APIResponse:
        return self.get("players", **params)

    def player_statistics(
        self,
        season: int,
        player: int | None = None,
        team: int | None = None,
    ) -> APIResponse:
        if player is None and team is None:
            raise ValueError("player_statistics requires player or team")
        return self.get(
            "players/statistics",
            season=season,
            player=player,
            team=team,
        )

    def injuries(
        self, player: int | None = None, team: int | None = None
    ) -> APIResponse:
        if player is None and team is None:
            raise ValueError("injuries requires player or team")
        return self.get("injuries", player=player, team=team)

    def odds(
        self,
        game: int | str,
        bookmaker: int | None = None,
        bet: int | None = None,
    ) -> APIResponse:
        return self.get(
            "odds",
            game=game,
            bookmaker=bookmaker,
            bet=bet,
        )

    def odds_bets(
        self,
        bet_id: int | None = None,
        search: str | None = None,
    ) -> APIResponse:
        return self.get("odds/bets", id=bet_id, search=search)

    def odds_bookmakers(
        self,
        bookmaker_id: int | None = None,
        search: str | None = None,
    ) -> APIResponse:
        return self.get(
            "odds/bookmakers",
            id=bookmaker_id,
            search=search,
        )
