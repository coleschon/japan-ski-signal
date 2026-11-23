# japan-ski-signal

Autonomous Japan ski trip signaler: snow, crowds/events, fares, lodging, JPY → email alerts.

Keep the signal aligned with the authoritative configuration and design: [`config.yaml`](config.yaml) and [`docs/design.md`](docs/design.md).

## Changing the weights

Edit the values in [`weights.yaml`](weights.yaml); non-negative values are normalized automatically. Set a factor to `0` to disable it, then redeploy to apply changes.

## Local run

Use Python 3.12 and install the dependencies:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Write a local HTML digest using the live free data sources without running paid SerpApi searches:

```sh
python -m ski_signal.run --dry-run --no-serpapi --force-digest
```

The report is written under `out/`. Local observations, dedupe state, and usage counts live in `.localdata/`. To enable flight and hotel quote refreshes, set `SERPAPI_API_KEY`; each paid search is checked against the configured monthly cap and SerpApi account usage.
