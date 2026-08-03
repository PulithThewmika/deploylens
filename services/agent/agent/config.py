import os
import re


def _parse_duration(value: str) -> int:
    """Parse a duration string like '30m', '1h', '15m' into seconds."""
    match = re.fullmatch(r"(\d+)\s*([smh])", value.strip().lower())
    if not match:
        raise ValueError(f"Invalid duration format: {value!r}. Use e.g. '30m', '1h', '90s'.")
    amount, unit = int(match.group(1)), match.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600}
    return amount * multipliers[unit]


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://deploylens:deploylens@localhost:5432/deploylens",
)

PROM_URL = os.environ.get("PROM_URL", "http://localhost:9090")

ALERTMANAGER_URL = os.environ.get("ALERTMANAGER_URL", "http://localhost:9093")

BASELINE_WINDOW = os.environ.get("BASELINE_WINDOW", "30m")
BASELINE_WINDOW_SECONDS = _parse_duration(BASELINE_WINDOW)

OBSERVATION_WINDOW = os.environ.get("OBSERVATION_WINDOW", "15m")
OBSERVATION_WINDOW_SECONDS = _parse_duration(OBSERVATION_WINDOW)

AGENT_INTERVAL_SECONDS = int(os.environ.get("AGENT_INTERVAL_SECONDS", "60"))
