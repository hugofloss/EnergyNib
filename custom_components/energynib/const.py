"""Constants for the EnergyNib integration."""

from datetime import timedelta

DOMAIN = "energynib"

API_URL = "https://api.aurumeurope.com"
OAUTH_CLIENT_ID = "b58efc0b"
OAUTH_SCOPE = "role:enduser realm:aurum"

SOURCE_TYPE_HEAT = "heat"

UPDATE_INTERVAL = timedelta(hours=1)

# How far back to import history the first time the integration runs.
CONF_BACKFILL_DAYS = "backfill_days"
DEFAULT_BACKFILL_DAYS = 365

# Heat meters report with a delay, so every update re-imports this window
# to pick up hours that were empty or incomplete during a previous poll.
REFETCH_WINDOW = timedelta(days=3)

# Interval of the data ("hour1" or "day1"). Detected once and stored in the
# config entry, because mixing resolutions in one statistic breaks the sums.
CONF_RESOLUTION = "resolution"
RESOLUTION_HOUR = "hour1"
RESOLUTION_DAY = "day1"
DETECT_WINDOW = timedelta(days=2)

# Maximum period requested per API call. The API answers 500 to long hourly
# ranges; the web app itself requests hourly data one day at a time.
FETCH_CHUNK = {RESOLUTION_HOUR: timedelta(days=1), RESOLUTION_DAY: timedelta(days=31)}
