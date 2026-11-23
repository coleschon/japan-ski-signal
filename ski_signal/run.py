import argparse
import logging

from ski_signal.config import load_config
from ski_signal.runner import run_signal


def main() -> None:
    parser = argparse.ArgumentParser(description="Score Japan ski trip opportunities")
    parser.add_argument("--dry-run", action="store_true", help="Write the email to ./out instead of SES")
    parser.add_argument("--force-digest", action="store_true", help="Include a digest on any weekday")
    parser.add_argument("--no-serpapi", action="store_true", help="Skip all SerpApi searches")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run_signal(
        dry_run=args.dry_run,
        force_digest=args.force_digest,
        no_serpapi=args.no_serpapi,
    )
    print(
        f"Processed {len(result['combos'])} combinations for {result['today']}; "
        f"HTML: {result['html_path'] or 'not generated'}"
    )
    config = load_config()
    depths = ", ".join(
        f"{station} {value:g} cm" if value is not None else f"{station} unavailable"
        for station, value in result["depths_by_station"].items()
    )
    anomaly = "unavailable" if result["enso_anomaly"] is None else f"{result['enso_anomaly']:.2f}"
    rate = "unavailable" if result["usd_jpy"] is None else f"{result['usd_jpy']:.2f}"
    print(
        f"AMeDAS depths: {depths}; ENSO anomaly: {anomaly}; USD/JPY: {rate}; "
        f"Niseko Village events parsed: {result['event_count']}"
    )
    forecasts = ", ".join(
        f"{config['resorts'][key]['name']} {value:g} cm"
        if value is not None
        else f"{config['resorts'][key]['name']} unavailable"
        for key, value in result["forecast_horizon_median_cm"].items()
    )
    print(f"Open-Meteo current forecast-horizon snowfall medians: {forecasts}")
    print("Top-ranked departure by resort:")
    for resort_key, resort in config["resorts"].items():
        resort_combos = [
            combo for combo in result["combos"] if combo["resort_key"] == resort_key
        ]
        top = max(resort_combos, key=lambda combo: combo["total_score"])
        print(
            f"{resort['name']}: {top['departure']} total={top['total_score']:.3f} "
            f"snow={top['components']['snow']:.3f} "
            f"climatology={top['details']['climatology']:.3f}"
        )
    print("Beyond-horizon climatology by departure:")
    for resort_key, resort in config["resorts"].items():
        values = [
            f"{combo['departure']} raw={combo['details']['climatology_raw']:.3f} "
            f"adjusted={combo['details']['climatology']:.3f}"
            for combo in result["combos"]
            if combo["resort_key"] == resort_key
            and combo["details"].get("climatology_raw") is not None
        ]
        print(f"{resort['name']}: {', '.join(values) if values else 'unavailable'}")


if __name__ == "__main__":
    main()
