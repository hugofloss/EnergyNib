"""Check the EnergyFlip API with your own account, outside Home Assistant.

    python3 -m venv .venv && .venv/bin/pip install aiohttp
    .venv/bin/python scripts/probe.py

Asks for e-mail and password, prints a summary and saves the raw responses
to probe-output/ (contains personal data - don't share those files as-is).
"""

from __future__ import annotations

import asyncio
import getpass
import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "custom_components" / "energyflip_heat"
OUT = ROOT / "probe-output"


def _load_client_module():
    """Import api.py without the HA-dependent package __init__."""
    pkg = types.ModuleType("energyflip_heat")
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules["energyflip_heat"] = pkg
    for name in ("const", "api"):
        spec = importlib.util.spec_from_file_location(f"energyflip_heat.{name}", PKG_DIR / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return sys.modules["energyflip_heat.api"]


def _save(name: str, data) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))


async def main() -> None:
    import aiohttp

    api = _load_client_module()
    username = input("EnergyFlip e-mail: ")
    password = getpass.getpass("Wachtwoord: ")

    async with aiohttp.ClientSession() as session:
        client = api.EnergyFlipClient(session, username, password)
        try:
            await client.login()
            print("✓ Ingelogd")
            overview = await client.customer_overview()
        except api.EnergyFlipAuthError:
            sys.exit("✗ Inloggen mislukt: controleer e-mailadres en wachtwoord.")
        except api.EnergyFlipError as err:
            sys.exit(f"✗ EnergyFlip niet bereikbaar of onverwacht antwoord: {err}")
        _save("overview", overview)
        print(f"✓ Customer id: {client.customer_id}")
        print(f"  Bronnen: {', '.join(sorted(client.sources)) or '(geen)'}")
        if "heat" not in client.sources:
            print("✗ Geen 'heat'-bron gevonden; kijk in probe-output/overview.json welke types er zijn.")

        now = datetime.now(timezone.utc)
        for resolution, days in (("hour1", 3), ("day1", 14)):
            start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
            try:
                raw = await client.cumulative_history_raw("heat", resolution, start, now)
            except api.EnergyFlipError as err:
                print(f"✗ {resolution}: {err}")
                continue
            _save(f"heat_{resolution}", raw)
            try:
                points = api.parse_heat_points(raw)
            except api.EnergyFlipError as err:
                print(f"✗ {resolution}: kan antwoord niet verwerken: {err}")
                continue
            print(f"\n{resolution}: {len(points)} waarden met data")
            for p in points[-8:]:
                print(f"  {p.start.isoformat()}  {p.value:.4f} {p.unit}")

    print(f"\nRuwe responses opgeslagen in {OUT}/")
    print("Controleer: zijn de waarden verbruik PER interval (niet oplopend)? En klopt het met de website?")


if __name__ == "__main__":
    asyncio.run(main())
