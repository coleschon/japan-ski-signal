from ski_signal.models import EnsoObservation
from ski_signal.sources.common import get_text


RONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt"
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
SEASON_ORDER = {
    season: index
    for index, season in enumerate(
        ("DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ")
    )
}


def parse_anomaly(text: str) -> float:
    rows: list[tuple[int, int, float]] = []
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < 3:
            continue
        try:
            season = tokens[0].upper()
            year = int(tokens[1])
            anomaly = float(tokens[-1])
        except ValueError:
            continue
        if season in SEASON_ORDER and 1800 <= year <= 2200:
            rows.append((year, SEASON_ORDER[season], anomaly))
    if not rows:
        raise ValueError("No dated ENSO anomaly rows found")
    return max(rows, key=lambda row: (row[0], row[1]))[2]


def fetch_enso() -> EnsoObservation:
    try:
        text = get_text(RONI_URL)
        return EnsoObservation(parse_anomaly(text), RONI_URL)
    except (ValueError, OSError):
        text = get_text(ONI_URL)
        return EnsoObservation(parse_anomaly(text), ONI_URL)
