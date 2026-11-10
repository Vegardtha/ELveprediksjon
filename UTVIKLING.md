# Utvikling av Elvepred

Kort logg over stegene, fra start til nå, og hva som kommer. Detaljer om modellen står i MODELL.md.

## Gjort

| Dato | Steg | Resultat |
|---|---|---|
| 27.10 | Første versjon: NVE HydAPI + seNorge (GTS), LightGBM per horisont, statisk nettside på GitHub Pages, oppdatert hver 2. time | Prognose dag 1–9 for elver på Østlandet |
| 27.10 | Robust drift: hurtiglager for GTS, parallell henting, tydelige feil ved manglende nøkkel | Driftsjobben kjører stabilt |
| 28.10 | 40 elver på Østlandet, ny trening | |
| 29.10 | 15 nye målestasjoner og alle padleseksjoner (nokken.net, whitewater.guide); XGBoost på GPU | Like god som LightGBM, ~3× raskere |
| 29.10 | Seksjoner tegnet langs elva, nytt kart og ny liste; Pæddekummen med bare målt vannføring | |
| 29.10–02.11 | Værprognoser fra Open-Meteo (MET Nordic + ECMWF) og arkiv av gamle prognoser fra mars 2024; trening på fasitvær før og ekte prognoser etter («wx_mixed») | Modellen lærer hvor upresise prognosene er |
| | Timesmodell 1–48 t, blandet mot døgnprognosen fra 6 til 48 t | NSE 48 t: 0.65 → 0.72 |
| 02.11 | Kritisk gjennomgang: prioritert liste med 9 tiltak (under) | |
| 02.11 | Rask evaluering (`eval_fast.py`, 4 halvårsperioder) og test av driftsoppsettet (`calibrate.py`) | Varianter kan sammenlignes på minutter |
| 02.11 | Lysakerelva tømte seg raskere enn varslet: modellen arvet treg nedgang fra store, innsjørike felt | Årsak funnet |
| 02.11 | Feltsignatur og resesjonskurve per stasjon, avstand til siste topp, prognoseflagg (2× vekt), hendelser 3× vekt | NSE opp på alle dager (dag 9: 0.497 → 0.512); Lysakerelva dag 4: 13.1 → 9.8 (målt 7.9) |
| 02.11 | Samme features i timesmodellen | Ingen gevinst, ikke tatt med |
| 02.11 | 92 nye stasjoner i hele Norge (254 seksjoner) lagt inn lokalt; henting av prognosearkiv startet | 75 av 145 stasjoner hentet |
| 03.11 | Oppstrømsstasjoner som features (12 av 55 stasjoner har en) | NSE dag 4 for disse: 0.714 → 0.720; Gudbrandsdalslågen +0.02. I driftsmodellen |
| 03.11 | Timesmodell på historiske flommer: ERA5 hentes rundt kraftige nedbørsdøgn fra 1990, seNorge-nedbøren fordeles på timer | ERA5 hentet for de 55 stasjonene |
| 04.11 | Timesmodellen trent på arkiv + flommer fra 1990, hendelser 3× vekt | NSE 48 t: 0.740 → 0.781; flomtest 2019–2024: 0.497 → 0.698. I driftsmodellen |
| 05.–09.11 | Prognosearkiv og ERA5 for alle 145 stasjoner; vaktsjekk som starter hentingen på nytt etter dvale (`fetch_supervised.py`) | Ferdig 09.11 |
| 09.11 | Trening med alle 145 stasjoner, samme oppsett | De 55 gamle litt dårligere fra dag 3 (dag 5: 0.699 → 0.687) |
| 09.11 | Mer kapasitet (31 → 63 → 127 blader) og lik vekt per stasjon testet i `eval_fast.py` | 127 blader best i alle halvår; lik vekt ingen gevinst |
| 10.11 | Driftsmodell med 145 stasjoner og 127 blader | De 55 gamle dag 5: 0.699 → 0.707; nye 90: 0.648; timer 48 t: 0.781 → 0.791. Jori dårligere. Modellfilene 65 → 360 MB |

**Testet og forkastet:** egen MET Nordic-nedbør dag 1–2, prognoseflagg uten vekting, 5× vekt på prognoserader
(tregere nedgang etter topper), feltsignatur i timesmodellen.

## De 9 tiltakene fra gjennomgangen

| # | Tiltak | Status |
|---|---|---|
| 1 | Rask og pålitelig evaluering | Gjort (mangler pinball-tap, Brier, bootstrap) |
| 2 | Prognoseflagg og vekting av prognoserader | Gjort (2×), pluss hendelsesvekt 3× |
| 3 | Oppstrømsstasjoner som features | Gjort (liten gevinst) |
| 4 | Hyperparametre / én modell for alle kvantiler | Delvis: 127 blader (10.11) |
| 5 | Snøsmelting som egen feature | Gjenstår |
| 6 | Sjekk ledetid i prognosearkivet (dag 2–3, dag 9) | Gjenstår |
| 7 | Bedre kalibrering (kryssvalidert, skalert med bredde) | Gjenstår; dekning 76–82 % mot 80 % |
| 8 | Skalaforskjell i nedbør seNorge vs. prognoser | Gjenstår |
| 9 | Metrikker for regulerte og uregulerte elver hver for seg | Gjenstår |

## Videre

1. **Publisere de 90 nye stasjonene:** sjekke at driftsjobben holder seg under 20 min på GitHub, så committe
   `rivers.yaml` og `catchments.geojson`.
2. **Mindre modellfiler** (komprimering eller utenfor git), siden hver ny trening legger ~360 MB til repoet.
3. **Resten av tiltakene,** i rekkefølgen 7 → 6 → 4 → 5 → 8 → 9.
