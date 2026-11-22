# Japan ski trip signaler - design

Daily Lambda (06:00 America/Los_Angeles via EventBridge Scheduler) that scores every (resort, departure Friday) combo 1-8 weeks out and emails:
- Storm alert (any day): ECMWF ensemble shows a big 72h storm 7-15 days out at an eligible resort.
- Book-now alert: total score >= config.alerts.book_now_score.
- Weekly digest (Mondays): ranked table of all combos with component scores.

All numbers/rules live in `config.yaml`. Score = sum(weight_i * component_i), each component in [0,1]. Ineligible resorts (base below gate) score 0.

## Data sources (all verified reachable, no key unless noted)
| Signal | Source |
|---|---|
| Base depth | JMA AMeDAS `https://www.jma.go.jp/bosai/amedas/data/latest_time.txt` then `.../data/point/{station}/{YYYYMMDD}_{HH3}.json` (`snow` = [cm, quality]; quality must be 0 or 1). Unofficial JSON; cite "出典：気象庁ホームページ". |
| Snow forecast | Open-Meteo ensemble `https://ensemble-api.open-meteo.com/v1/ensemble?...&daily=snowfall_sum&models=ecmwf_ifs025&forecast_days=15&elevation=..&timezone=Asia/Tokyo` (members `snowfall_sum_memberNN`). |
| Climatology | Open-Meteo archive `https://archive-api.open-meteo.com/v1/archive` daily `snowfall_sum`, cached in storage (fetch once per season). |
| ENSO | NOAA CPC `https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt` (fallback `oni.ascii.txt`), latest ANOM. |
| Flights | SerpApi `engine=google_flights` (key `SERPAPI_API_KEY`), round trip, multi-airport `departure_id`, `adults`, `currency=USD`; use `best_flights/other_flights` min price, `price_insights`, `search_metadata.google_flights_url`. |
| Lodging | SerpApi `engine=google_hotels`, `q`, `check_in_date`, `check_out_date`, `adults`, `currency=USD`; lowest `total_rate.extracted_lowest`, top 3 properties with links. |
| Yen | Frankfurter `https://api.frankfurter.dev/v1/` (latest + 365-day series). |
| Niseko events | https://www.niseko-village.com/events/ scraped, keyword-filtered, date ranges parsed. (Powderlife dropped: bot-challenge page, no dated entries in markup.) Scraper failure must degrade to events_score from cached data / 0.5, never crash the run. |

## Infra (AWS us-west-2, Terraform)
Lambda (Python 3.12) + EventBridge Scheduler + DynamoDB (on-demand, single table) + S3 (raw JSON snapshots, 90-day lifecycle) + SES (sandbox; verified identity = email_to) + CloudWatch Logs (14-day retention). Secrets passed to Lambda as env vars from Terraform variables (SERPAPI_API_KEY); never committed.
