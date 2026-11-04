# Slik predikerer Elvepred vannføringen

Elvepred varsler vannføring (m³/s) for 9 dager og 48 timer fram ved NVEs målestasjoner. Hver padleseksjon
får deretter status og sannsynlighet for padlbar vannføring ut fra sine egne terskler. Prognosen lages per
målestasjon og deles av alle seksjonene som bruker samme stasjon.

## Datakilder

| Kilde | Hva | Brukes til |
|---|---|---|
| NVE HydAPI | Døgn- og timesvannføring fra 1990 | Mål og historikk |
| NVE GTS (seNorge) | Feltmiddel av nedbør, temperatur, snø (SWE), regn + snøsmelting og HBV-tilstand | Tilstanden i feltet nå |
| Open-Meteo `metno_seamless` | MET Nordic (1 km) de første ~2,5 døgnene, deretter ECMWF | Værprognose framover |
| Open-Meteo Previous Runs | Arkiv av gamle prognoser fra mars 2024 | Trening på ekte prognosefeil |
| NVE kart | Nedbørfeltpolygon per stasjon | Feltmiddel (GTS) og prognosepunkter (4 per felt) |

## Døgnmodellen (dag 1–9)

- **Én modell per horisont h = 1–9 og kvantil (p10, p50, p90).** Det blir 27 XGBoost-modeller. De er felles
  for alle stasjoner, og stasjonen er en kategorisk feature.
- **Målet er endringen i log-vannføring:** `y = log1p(q[t+h]) − log1p(q[t])`, der t er siste hele døgn med
  måling. Fordi modellen predikerer endring, kan små og store elver trenes sammen.
- **Features om fortiden:**
  - log-vannføring nå, endring siste 1/2/3/7 døgn, og 7- og 30-døgns snitt, min og maks
  - hvor langt under og hvor lenge siden siste topp (7 døgn), som skiller stigning, topp og nedgang
  - nedbørsum siste 3/7/14/30 døgn og temperaturtrend
  - snømengde og endring i snø, regn + snøsmelting og HBV-avrenning, markvann og grunnvann
  - årstid (sin/cos av dagnummer)
- **Features om framtiden (været):** nedbør per døgn fram til h, total nedbør, største døgnnedbør,
  snittemperatur, positive graddager (snøsmelting) og nedbør som faller som regn. `wx_fc` sier om været er en ekte
  prognose (1, alltid i drift) eller fasit (0).
- **Feltsignatur per stasjon** (beregnet fra stasjonens egen historikk): typisk fall per døgn i tørt vær, også
  etter flomtopper, hvor raskt elva svinger (Richards–Baker) og spennet i vannføring. I tillegg en resesjonskurve
  −dq/dt = a·qᵇ, som gir `rec_h`: hvor elva havner etter h døgn hvis det holder seg tørt. Signaturen lagres i
  modellfilen, siden driften bare har 60 døgn historikk. Uten den arvet raske elver med kort historikk
  (f.eks. Lysakerelva fra 2020) den tregere nedgangen til store, innsjørike felt.
- **Stasjon oppstrøms** (12 av 55 stasjoner, funnet fra nedbørfeltene i `elvepred/upstream.py`): andel av feltet,
  forholdet mellom vannføringene og avviket fra det normale forholdet, endring siste 1 og 3 døgn og siste
  timesmålinger. Fanger flombølger og slipp fra magasiner før de når stasjonen. Paret lagres i modellfilen.
- **Vekting i treningen:** rader med ekte prognose teller 2×, og hendelser teller 3×. En hendelse er meldt regn
  ≥ 15 mm, endring ≥ 10 % siste døgn, eller nær en topp som ligger godt over 30-døgnsnittet. Hendelsene bestemmes
  bare av features, ikke av fasit, så kvantilene forskyves ikke. 5× vekt på prognoserader ga mer treg nedgang
  etter flomtopper.
- **Nowcast:** dagens timesmålinger fram til nå gir siste nivå og endring de siste 3/6/12/24 timene. Treningen
  lager rader for kl. 03, 09, 15 og 21 UTC, så modellen fungerer uansett når den kjøres.
- **Treningsvær ("wx_mixed"):** ekte arkiverte prognoser der arkivet finnes (fra mars 2024), og faktisk vær
  (fasit) før det. Da lærer modellen både lange tidsserier og hvor upresise prognosene faktisk er.

## Timesmodellen (1–48 timer)

- **Én XGBoost-modell per kvantil.** Horisonten k i timer er en feature, og målet er
  `log1p(q[T+k]) − log1p(q[T])` fra siste timesmåling T.
- **Features:**
  - timesvannføring de siste 72 timene
  - prognosenedbør som sum over 6, 12 og 24 timer før T+k, og største timesverdi
  - temperatur, tid på døgnet ved T+k, og snø og markvann fra GTS
- **Trening på historiske flommer:** prognosearkivet (fra mars 2024) har bare moderate flommer. Derfor er også
  dagene rundt kraftige nedbørsdøgn fra 1990 med (nedbør ≥ maks(15 mm, stasjonens 99-persentil), fra 2 døgn før
  til 1 døgn etter). Fasitværet er seNorge-nedbøren fordelt på timer etter mønsteret i ERA5 (døgnet går 06–06 UTC),
  og ERA5-temperatur justert til GTS-døgnmiddelet. Radene har prognoseflagg `wx_fc` = 0, og hendelser vektes 3×.
  800 trær.
- **Gevinst** (NSE; flomtest = dager med kraftig nedbør 2019–2024, utenfor treningen):

  | Timer fram | 6 | 12 | 24 | 36 | 48 |
  |---|---|---|---|---|---|
  | Vanlig test, bare arkiv | 0.966 | 0.926 | 0.859 | 0.796 | 0.740 |
  | Vanlig test, med historikk | 0.970 | 0.937 | 0.884 | 0.831 | 0.781 |
  | Flomtest, bare arkiv | 0.956 | 0.881 | 0.729 | 0.610 | 0.497 |
  | Flomtest, med historikk | 0.966 | 0.921 | 0.835 | 0.767 | 0.698 |

  Ved flomtopper var modellen bare med arkiv for lav (skjevhet −0.58 i log ved 48 t); med historikk −0.23.
- Feltsignatur, resesjonskurve og avstand til topp ga ingen gevinst her (likt til 24 t, litt dårligere ved
  36–48 t), så de er ikke med.
- **Blanding med døgnprognosen:** timesprognosen trekkes gradvis mot døgnprognosen fra 6 til 48 timer.
  Vekten øker lineært fra 0 til 1, så de to møtes uten sprang. Backtest ga NSE 0.72 mot 0.65 ved 48 timer.

## Usikkerhet og status

- **Kalibrering:** p10 og p90 kalibreres med konforme tillegg, beregnet på en egen periode
  (nov. 2024–juni 2025) med samme oppsett som i drift (`scripts/calibrate.py`), slik at p10–p90-båndet skal
  treffe om lag 80 % av gangene. På testen treffer det 76–82 %, lavest på de lengste horisontene. Kvantilene
  sorteres hvis de krysser.
- **Sannsynlighet for padlbar vannføring:** p10/p50/p90 tolkes som en delt lognormalfordeling, med egen bredde
  under og over medianen. Sannsynligheten er arealet mellom seksjonens minimum og maksimum.
- **Status per seksjon** følger whitewater.guide: tørr, lav, min–opt, opt–maks, høy, umulig.
  Tersklene er hentet fra nokken.net og whitewater.guide.
- **Unntak:** stasjoner uten nedbørfelt hos NVE (f.eks. Pæddekummen) får bare målt vannføring, ikke prognose.

## Evaluering

- **Tidssplitt:** trening til okt. 2024, validering og kalibrering nov. 2024–juni 2025, test fra juli 2025 til i
  dag. Testen bruker ekte arkiverte værprognoser.
- **NSE på testsettet** (snitt av NSE per stasjon, 55 stasjoner), med samme oppsett som i drift
  (600 trær, ingen early stopping; `scripts/calibrate.py`, `--baseline` for oppsettet før 2026-11-02):

  | Dag | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
  |---|---|---|---|---|---|---|---|---|---|
  | Modell | 0.976 | 0.888 | 0.812 | 0.755 | 0.699 | 0.646 | 0.597 | 0.549 | 0.512 |
  | Før 2026-11-02 | 0.972 | 0.880 | 0.807 | 0.748 | 0.691 | 0.635 | 0.589 | 0.541 | 0.497 |
  | Persistens (i dag = i morgen) | 0.948 | 0.773 | 0.550 | 0.404 | 0.273 | 0.162 | 0.068 | −0.004 | −0.049 |

  F1 for padlbar vannføring går opp på alle dagene (dag 5: 0.629 → 0.644). 37–41 av 55 stasjoner blir bedre.
  Svakest er store, regulerte elver (Jori, Gudbrandsdalslågen, Mistra). Stasjon oppstrøms ga i `eval_fast.py`
  NSE 0.714 → 0.720 på dag 4 for de 12 stasjonene som har en (Gudbrandsdalslågen +0.02), og ingen endring for
  de andre. Gevinsten er liten fordi vannet bruker timer, ikke døgn, og dagens timesmålinger allerede er med. Tallene i
  tidligere versjoner (0.98/0.90/0.82/0.71/0.61/0.51) kom fra `scripts/evaluate_fc.py` med early stopping og
  er ikke direkte sammenlignbare.
- **Rask evaluering av varianter:** `scripts/eval_fast.py` bruker fire halvårsperioder fra 2025, der hver
  trenes på alt før perioden. Den måler også feilen i log-vannføring ved stigning og fall (> 20 %) og hvor treg
  nedgangen er etter flomtopper. Hendelsesvekting ga størst gevinst. Vekting av prognoserader ga mest i siste
  periode, som har mest prognosedata å lære av.
- **Feilen domineres av værprognosen fra dag 4–5.** Med perfekt vær holdt modellen seg rundt 0.70 også på dag 9.
- **Testet og forkastet:**
  - Egen MET Nordic-nedbør for dag 1–2 ga ingen gevinst.
  - LightGBM og XGBoost er like gode. XGBoost ble valgt fordi den er raskere på GPU.
  - Prognoseflagget `wx_fc` alene, uten vekting, ga ingen gevinst.

## Drift

- **Trening og evaluering** kjøres lokalt (GPU), og modellene lagres i `data/models/`.
- **GitHub Actions** kjører hver 2. time: henter siste målinger, GTS (1–2 ganger i døgnet) og værprognose,
  predikerer, eksporterer statisk JSON og publiserer til GitHub Pages.
- **Koden:**
  - `backend/elvepred/features.py`, `hourly.py` og `model/{train,predict}.py`
  - `classify.py` (status og sannsynligheter)
  - `scripts/calibrate.py` (kalibrering og test av driftsoppsettet), `scripts/eval_fast.py` (varianter) og
    `scripts/evaluate_fc.py` (eldre sammenligning av værkilder)
