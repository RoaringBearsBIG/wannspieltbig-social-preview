"""Env-driven configuration for the wannspieltbig-social-preview service."""

import os


class ServiceConfig:
    """Reads settings from environment variables (see .env.example)."""

    @property
    def share_base_url(self) -> str:
        """Public base URL of the share pages (no trailing slash)."""
        return os.getenv("SHARE_BASE_URL", "https://bot.wannspieltbig.de").rstrip("/")

    @property
    def esports_api_url(self) -> str:
        """wannspieltbig match API the share pages read from."""
        return os.getenv(
            "ESPORTS_API_URL", "https://wannspieltbig.de/api/match_upcoming/"
        )

    @property
    def port(self) -> int:
        return int(os.getenv("PORT", "8080"))

    @property
    def warm_interval_minutes(self) -> int:
        """How often the background warmer pre-builds upcoming match images."""
        return int(os.getenv("WARM_INTERVAL_MINUTES", "15"))


config = ServiceConfig()
