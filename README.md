# japan-ski-signal

Autonomous Japan ski trip signaler: snow, crowds/events, fares, lodging, JPY → email alerts.

A daily signaler that scores Friday departures from Southern California for Niseko, Hakuba Valley, Nozawa Onsen, and Myoko Kogen. It combines AMeDAS base depth, Open-Meteo snowfall forecasts and climatology, CPC ENSO, crowd/event calendars, flight and lodging observations, and the USD/JPY rate. The scoring and operating limits are defined in [`config.yaml`](config.yaml).

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

## Tests and CI

With the Python 3.12 virtual environment active, run:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

GitHub Actions runs the same suite for pull requests targeting `main` and pushes to `main`. The suite does not need AWS or SerpApi credentials.

To enforce the check after its first successful run, a repository admin must configure [branch protection](https://github.com/coleschon/japan-ski-signal/settings/branches) for `main`: require a pull request and require the **Unit tests** status check from GitHub Actions, with bypass disabled. GitHub requires Pro to protect branches in a private personal repository.

## Deploy

Before initializing Terraform, bootstrap the remote-state bucket once in `us-west-2`. Use your AWS account ID for `<ACCOUNT_ID>` and create `<ACCOUNT_ID>-japan-ski-signal-tfstate` with versioning enabled, all S3 Block Public Access settings enabled, and default server-side encryption (SSE-S3/AES-256). The bucket must exist before Terraform initialization because Terraform cannot create its own backend.

For example, with a working AWS CLI:

```sh
ACCOUNT_ID=123456789012
STATE_BUCKET="${ACCOUNT_ID}-japan-ski-signal-tfstate"
aws s3api create-bucket --bucket "$STATE_BUCKET" --region us-west-2 \
  --create-bucket-configuration LocationConstraint=us-west-2
aws s3api put-bucket-versioning --bucket "$STATE_BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket "$STATE_BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$STATE_BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

The system `aws` CLI on this VM is broken with `botocore KeyError: 'opsworkscm'`; if you need to bootstrap from this VM, use boto3 from the project virtual environment or the AWS Console.

Copy the backend example, replace `<ACCOUNT_ID>` with your account ID, then initialize the S3 backend. Build the Lambda package and apply:

```sh
cp infra/backend.hcl.example infra/backend.hcl
cp infra/terraform.tfvars.example infra/terraform.tfvars
# Replace <ACCOUNT_ID> in infra/backend.hcl with your AWS account ID.
# Edit infra/terraform.tfvars with your verified SES email identities.
export SERPAPI_API_KEY='your-serpapi-key'
cd infra
terraform init -backend-config=backend.hcl
cd ..
./scripts/build.sh
cd infra
TF_VAR_serpapi_api_key="$SERPAPI_API_KEY" terraform apply
```

Terraform provisions the Lambda, least-privilege runtime and scheduler roles, on-demand DynamoDB table, S3 snapshot bucket with 90-day expiration, daily 06:00 America/Los_Angeles schedule, CloudWatch log group with 14-day retention, and an SES email identity for the configured recipient. After apply, click the verification link SES sends to `email_to`; SES sandbox accounts also require the recipient to be verified before email delivery.

Set the email addresses in `infra/terraform.tfvars`; both must be verified SES identities.
