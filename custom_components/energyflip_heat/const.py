"""Constants for the EnergyFlip Warmte integration."""

from datetime import timedelta

DOMAIN = "energyflip_heat"

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

# Maximum period requested per API call.
FETCH_CHUNK = timedelta(days=31)
