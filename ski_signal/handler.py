import logging
from typing import Any

from ski_signal.runner import run_signal


LOGGER = logging.getLogger(__name__)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    logging.basicConfig(level=logging.INFO)
    result = run_signal(
        force_digest=bool(event.get("force_digest", False)),
        no_serpapi=bool(event.get("no_serpapi", False)),
    )
    return {
        "today": result["today"],
        "combination_count": len(result["combos"]),
        "alerts": result["alerts"],
    }
