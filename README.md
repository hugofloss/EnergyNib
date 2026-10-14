# EnergyFlip Warmte voor Home Assistant

Custom integratie die je warmteverbruik (stadsverwarming) uit [EnergyFlip](https://web.energyflip.com)
ophaalt en als **langetermijnstatistiek met de juiste tijdstempels** in Home Assistant zet,
zodat het correct in het energiedashboard verschijnt, ook als EnergyFlip de data pas later levert.

## Hoe het werkt

- Logt in op dezelfde (ongedocumenteerde) API als de webapp: `api.aurumeurope.com`,
  OAuth2 password grant + refresh token.
- Haalt elk uur het warmteverbruik per uur op (`/user/v4/customers/{id}/measurements/cumulativeHistory?views=heat`).
  Levert de meter geen uurdata, dan valt hij automatisch terug op dagwaarden.
- Importeert dit als externe statistiek `energyflip_heat:<customerid>_heat` (eenheid GJ).
  De laatste 3 dagen worden elke keer opnieuw geïmporteerd, zodat late metingen alsnog goed terechtkomen.
- Eerste keer: importeert standaard 365 dagen historie (aan te passen via *Configureren*).
- Sensoren (informatief): *Warmteverbruik laatste dag* en *Laatste meting*.

## Stap 1: eerst testen met je account (aanbevolen)

```bash
python3 -m venv .venv && .venv/bin/pip install aiohttp
.venv/bin/python scripts/probe.py
```

Controleer in de uitvoer:
1. Er is een bron `heat`.
2. `hour1` of `day1` geeft waarden, en die waarden zijn **verbruik per interval** (geen oplopende meterstand).
3. De getallen komen overeen met wat de website toont.

Klopt iets niet, dan staan de ruwe responses in `probe-output/` (bevatten persoonsgegevens).

## Stap 2: installeren

**Handmatig:** kopieer `custom_components/energyflip_heat/` naar `<HA-config>/custom_components/`
(bijv. via de Samba- of SSH-add-on) en herstart Home Assistant.

**Via HACS:** zet deze map in een (privé) GitHub-repo, voeg die toe als *Custom repository*
(type *Integration*) en installeer *EnergyFlip Warmte*.

## Stap 3: instellen

1. *Instellingen → Apparaten & diensten → Integratie toevoegen → EnergyFlip Warmte*.
2. Log in met je EnergyFlip-account.
3. Wacht tot de eerste import klaar is (zie *Ontwikkelaarstools → Statistieken*).
4. *Instellingen → Dashboards → Energie → Gasverbruik → Gasbron toevoegen* en kies
   **EnergyFlip warmteverbruik**. (HA telt warmte in GJ mee onder gas.)

## Debuggen

```yaml
logger:
  logs:
    custom_components.energyflip_heat: debug
```

## Kanttekeningen

- Ongedocumenteerde API: EnergyFlip kan die zonder aankondiging wijzigen.
- Wil je opnieuw beginnen: verwijder de statistiek via *Ontwikkelaarstools → Statistieken*
  en herlaad de integratie.
