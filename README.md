# japan-ski-signal

Autonomous Japan ski trip signaler: snow, crowds/events, fares, lodging, JPY → email alerts.

Keep the signal aligned with the authoritative configuration and design: [`config.yaml`](config.yaml) and [`docs/design.md`](docs/design.md).

## Changing the weights

Edit the values in [`weights.yaml`](weights.yaml); non-negative values are normalized automatically. Set a factor to `0` to disable it, then redeploy to apply changes.
