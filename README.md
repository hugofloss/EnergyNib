# EnergyNib for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)

A custom integration that fetches your heat usage (district heating) from [EnergyFlip](https://web.energyflip.com)
and stores it in Home Assistant as **long-term statistics with the correct timestamps**,
so it shows up correctly in the Energy dashboard, even when EnergyFlip delivers the data late.

## How it works

- Logs in to the same (undocumented) API as the web app: `api.aurumeurope.com`,
  using an OAuth2 password grant + refresh token.
- Fetches hourly heat usage every hour (`/user/v4/customers/{id}/measurements/cumulativeHistory?views=heat`).
  On first run it checks whether your meter provides hourly data; if not, daily values are used.
  That choice is stored and never changed afterwards (mixing hourly and daily values corrupts the totals).
- Imports the data as the external statistic `energynib:<customerid>_heat` (unit GJ).
  The last 3 days are re-imported on every update, so late measurements still end up in the right place.
- On first run it imports 365 days of history by default (adjustable via *Configure*, only before the first import).
- Sensors (informational): *Heat usage last day* and *Last measurement*.

## Installation

### HACS (recommended)

EnergyNib is not in the default HACS store, so you add it as a **custom repository**.
You need [HACS](https://hacs.xyz/docs/use/) installed first.

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hugofloss&repository=EnergyNib&category=integration)

Or manually in HACS:

1. Open **HACS** in Home Assistant.
2. Click the **⋮** menu (top right) → **Custom repositories**.
3. Repository: `https://github.com/hugofloss/EnergyNib`, type: **Integration**, then **Add**.
4. Search for **EnergyNib** in HACS, open it and click **Download**.
5. Restart Home Assistant.

HACS will notify you when a new version is available.

### Manual

Copy `custom_components/energynib/` to `<HA config>/custom_components/`
(e.g. using the Samba or SSH add-on) and restart Home Assistant.

## Configuration

1. *Settings → Devices & services → Add integration → EnergyNib*.
2. Log in with your EnergyFlip account.
3. Wait for the first import to finish (see *Developer tools → Statistics*).
4. *Settings → Dashboards → Energy → Gas consumption → Add gas source* and pick
   **EnergyFlip warmteverbruik**. (Home Assistant counts heat in GJ under gas.)

## Optional: test your account first

Before installing, you can check that your account returns usable data:

```bash
python3 -m venv .venv && .venv/bin/pip install aiohttp
.venv/bin/python scripts/probe.py
```

Check the output for:
1. A source called `heat`.
2. `hour1` or `day1` returning values, and those values being **usage per interval** (not a rising meter reading).
3. The numbers matching what the website shows.

If something looks off, the raw responses are saved in `probe-output/` (they contain personal data).

## Debugging

```yaml
logger:
  logs:
    custom_components.energynib: debug
```

## Caveats

- This uses an undocumented API, and EnergyFlip may change it without notice.
- To start over, delete the statistic under *Developer tools → Statistics*
  and reload the integration.
