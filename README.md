# Elvepred

Vannføringsprognoser for 173 padleseksjoner på 55 målestasjoner på Østlandet: time for time de neste 48 timene, deretter døgn for døgn ut 9 dager, med usikkerhet og sjanse for padlbar vannføring. Elver som styres av demninger er merket.

Siden oppdateres hver 2. time av GitHub Actions og publiseres på GitHub Pages.

## Slik virker det

- **Data:** vannføring fra NVE HydAPI, observert vær, snø og markvann fra seNorge (NVE/MET), og værprognose fra MET Nordic via Open-Meteo.
- **Døgnmodell:** XGBoost-kvantilregresjon (p10/p50/p90) per horisont 1–9 døgn, felles for alle stasjoner, trent på historikk fra 1990 og ekte arkiverte værprognoser fra mars 2024 (`backend/elvepred/features.py`, `backend/elvepred/model/train.py`).
- **Timesmodell:** én XGBoost-modell per kvantil med horisont som feature, 1–48 timer fra siste timesmåling (`backend/elvepred/hourly.py`). Den glir gradvis over i døgnprognosen og er lik den ved 48 timer (valgt med `scripts/backtest_blend.py`).
- **Usikkerhet:** p10/p90 er kalibrert konformt på en valideringsperiode, så 80 %-båndet holder omtrent.
- **Nivåer:** padlenivåer og innsett/utsett fra nokken.net og whitewater.guide, i `backend/config/rivers.yaml`.

## Drift (GitHub)

`.github/workflows/update.yml` kjører hvert andre time (minutt 17, UTC), ved push til `main` og manuelt. Den henter ferske data, beregner prognosen med de lagrede modellene i `data/models`, eksporterer JSON (`scripts/export_static.py`) og publiserer den statiske siden.

seNorge-feltmiddelet (GTS, ca. 140 kall per stasjon) oppdateres bare én gang i døgnet. Det hentes derfor ved første kjøring hver dag og første kjøring etter kl. 08 UTC, og ligger ellers i Actions-cachen (`data/cache`). Stasjonene hentes parallelt.

Oppsett én gang:

1. **Settings → Secrets and variables → Actions:** legg inn `NVE_API_KEY` (gratis nøkkel fra https://hydapi.nve.no).
2. **Settings → Pages → Source:** velg «GitHub Actions».

Planlagte kjøringer slås av etter 60 dager uten aktivitet i repoet. Ny trening med push av modellene holder det i gang, ellers kan workflowen slås på igjen under Actions.

## Lokalt

Krever [uv](https://docs.astral.sh/uv/) og Node 22. Legg `NVE_API_KEY=...` i `.env` i rotmappa.

```bash
uv sync --directory backend
uv run --directory backend python scripts/update.py
uv run --directory backend python scripts/export_static.py
npm ci --prefix frontend
npm run dev --prefix frontend
```

### Nye elver og seksjoner

Prognosen lages per målestasjon; hver seksjon på stasjonen får egne terskler, status og sannsynligheter.
`scripts/add_sections.py` legger inn alle seksjoner med nivåer fra nokken.net og whitewater.guide som ikke
allerede finnes (se docstringen for hvordan referansefilene hentes). Kjør med `--dry-run` først, og deretter:

```bash
uv run --directory backend python scripts/add_sections.py
uv run --directory backend python scripts/fetch_catchments.py
uv run --directory backend python scripts/fetch_history.py --new
uv run --directory backend python scripts/fetch_hourly.py --new
uv run --directory backend python scripts/fetch_forecasts.py
```

Deretter ny trening som under (bare nødvendig for nye stasjoner). Modellene kjenner bare stasjonene de er trent på.

### Ny trening

Trening gjøres lokalt (anbefalt omtrent månedlig), og de nye modellene pushes. Med NVIDIA-GPU trener XGBoost på CUDA (~20 min for døgnmodellene), ellers på CPU:

```bash
uv run --directory backend python scripts/fetch_history.py
uv run --directory backend python scripts/fetch_hourly.py
uv run --directory backend python scripts/fetch_forecasts.py
uv run --directory backend python scripts/train.py
uv run --directory backend python scripts/train_hourly.py
```

`scripts/evaluate_fc.py --fc-models metno_seamless --skip-gts` lager kalibrering og metrikker for døgnmodellen.

## Lisenser og kilder

- Vannføring: [NVE HydAPI](https://hydapi.nve.no), NLOD 2.0.
- Observert vær, snø og markvann: [seNorge](https://www.senorge.no) (NVE/MET), CC BY 4.0.
- Værprognose: MET Norway via [Open-Meteo](https://open-meteo.com), CC BY 4.0. Open-Meteos gratis API er bare for ikke-kommersiell bruk.
- Kart: © [Kartverket](https://www.kartverket.no), CC BY 4.0.
- Padlenivåer og innsett/utsett i `backend/config/rivers.yaml` er hentet fra [nokken.net](https://nokken.net) og [whitewater.guide](https://whitewater.guide) og er lisensiert under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

Prognosene er modellberegninger og kan ta feil, særlig i regulerte elver. Sjekk alltid siste måling før du drar.
