# TODO

## Timesmodellen: tren på historiske flommer (tilbake til 1990)

Timesmodellen (1–48 t, `backend/elvepred/hourly.py`) trenes bare på prognosearkivet fra mars 2024. Det gir
115 flomtopper over middelflom (52 stasjoner), og de største er bare ca. 1,2× middelflom. Før mars 2024 finnes
1171 slike topper, og de største er ca. 2,3× middelflom, blant dem ekstremværet Hans i 2023. Trær kan ikke
ekstrapolere, så ved store flommer vil timesmodellen trolig bomme på hvor fort og hvor høyt elva stiger de første
6–24 timene.

Tiltak:
- Lag nedbør per time før mars 2024: seNorge-nedbøren per døgn fordelt på timer etter mønsteret i ERA5 (Open-Meteo
  Historical Weather API, ett punkt per felt). Døgnsummene blir da de samme som døgnmodellen ser.
- Tren timesmodellen på dette før mars 2024 og på ekte prognoser etter, med prognoseflagget `wx_fc` og vekt på
  hendelser (som døgnmodellen, `train.weights`).
- Sammenlign mot dagens timesmodell, med egen vekt på flomhendelser (f.eks. RMSE ved stigning og ved toppen).

Kostnad: ca. ett døgn med henting fra Open-Meteo (ett punkt per felt holder, siden ERA5 er grovt og bare skal gi
timemønsteret), deretter ny trening og en sammenligning med vekt på flomhendelser. Hentingen deler gratiskvoten med
prognosearkivet for de nye stasjonene, som går nå, så de to må gå etter hverandre.
