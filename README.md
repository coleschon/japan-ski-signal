# japan-ski-signal

Autonomous Japan ski trip signaler: snow, crowds/events, fares, lodging, JPY → email alerts.

A daily signaler that scores Friday departures from Southern California for Niseko, Hakuba Valley, Nozawa Onsen, and Myoko Kogen. It combines AMeDAS base depth, Open-Meteo snowfall forecasts and climatology, CPC ENSO, crowd/event calendars, flight and lodging observations, and the USD/JPY rate. The scoring and operating limits are defined in [`config.yaml`](config.yaml).

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

## Deploy

Build the Lambda package, then initialize and apply the Terraform in `infra/`:

```sh
./scripts/build.sh
cd infra
terraform init
TF_VAR_serpapi_api_key='your-serpapi-key' terraform apply
```

Terraform provisions the Lambda, least-privilege runtime and scheduler roles, on-demand DynamoDB table, S3 snapshot bucket with 90-day expiration, daily 06:00 America/Los_Angeles schedule, CloudWatch log group with 14-day retention, and an SES email identity for the configured recipient. After apply, click the verification link SES sends to `email_to`; SES sandbox accounts also require the recipient to be verified before email delivery.

The SES identity is created for the recipient address. Set `TF_VAR_email_to` and `TF_VAR_email_from` to verified SES identities if changing the defaults.
