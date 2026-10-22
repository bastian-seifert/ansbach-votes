# Ansbach votes – Wahlergebnisse auf Stimmbezirksebene

Tools to pull, analyse and map election results for the city of Ansbach down to
the individual **Stimmbezirk** (polling district), including a **per-candidate
analysis for the Kommunalwahl** (Stadtratswahl with Kumulieren/Panaschieren).

Included data:

| id | election | data |
|----|----------|------|
| `europawahl_2024` | Europawahl 2024 | `data/stimmen_europawahl_2024.csv` |
| `bundestagswahl_2025` | Bundestagswahl 2025 (Erst- `D` and Zweitstimmen `F`) | `data/stimmen_btw_2025.csv` |
| `stadtratswahl_2026` | Stadtratswahl 2026 (40 seats) | `fetch` from <https://wahlen2026.ansbach.de/kommunal/> |
| `oberbuergermeisterwahl_2026` | OB-Wahl 2026 | `fetch` from the same portal |

Elections are registered in [`data/elections.toml`](data/elections.toml); add a
block there to support further elections (Landtag, Bezirk, Stichwahl …).

## Setup

```bash
pip install -e ".[maps]"      # pandas, requests, folium, matplotlib
pytest                         # optional: pip install -e ".[dev]"
```

## Pull the latest data

```bash
python -m ansbach_votes fetch stadtratswahl_2026      # one election
python -m ansbach_votes fetch                          # every election with a source_url
python -m ansbach_votes fetch stadtratswahl_2026 --url https://…/opendata.html
```

`fetch` crawls the official OK.VOTE results portal, downloads every open data
CSV it finds to `data/raw/<election>/` (with a `manifest.json` holding URL,
checksum and time) and reports which files are `new`, `updated` or
`unchanged`. On election night you can re-run it to pick up new reports.

The CSVs only number the lists and candidates (`D3` = list 3, `D3_12` = list 3,
position 12). `fetch` names them automatically by matching the city-wide
totals in the CSV against the numbers on the portal's HTML pages and stores the
result in `data/labels/<election>.json` under `auto`. Columns whose totals
are ambiguous stay unnamed. You can fix or complete them by hand under
`columns` (hand-made entries win), or import the official list of candidates
("Bekanntmachung der zugelassenen Wahlvorschläge") as a CSV with the columns
`liste,platz,name[,wahlvorschlag]`:

```bash
python -m ansbach_votes import-candidates stadtratswahl_2026 kandidaten.csv
```

## Analyse

```bash
python -m ansbach_votes list
python -m ansbach_votes summary bundestagswahl_2025
python -m ansbach_votes districts bundestagswahl_2025 AfD           # strongholds of a party
python -m ansbach_votes districts bundestagswahl_2025 --wahllokal   # per polling station
python -m ansbach_votes swing europawahl_2024 bundestagswahl_2025   # change per district
python -m ansbach_votes report                                      # all tables + maps -> reports/

# Kommunalwahl, per candidate
python -m ansbach_votes candidates stadtratswahl_2026               # ranking, elected, moved up/down
python -m ansbach_votes candidates stadtratswahl_2026 --list CSU
python -m ansbach_votes candidates stadtratswahl_2026 "Deffner"     # one candidate, per district
python -m ansbach_votes candidates stadtratswahl_2026 --district Eyb  # top candidates in Eyb
```

Or from Python / the notebook [`ansbach_votes_visualization.ipynb`](ansbach_votes_visualization.ipynb):

```python
import ansbach_votes as av
from ansbach_votes import analysis, geo

srw = av.load("stadtratswahl_2026")
analysis.seat_allocation(srw)
analysis.candidates(srw)
analysis.candidate_districts(srw, "Deffner")
geo.plot_candidate(srw, "Deffner")
```

### What is computed

Per district (`analysis.districts`, `by_wahllokal`, `strongholds`):
share of every list, turnout at the polling station, share of voters with a
Wahlschein, deviation from the city-wide result in percentage points and as an
index. Districts sharing a building are combined by `by_wahllokal` (votes are
summed, then divided).

Across districts:

* `correlations`: which parties' voters live in the same districts.
* `bellwether`: which districts come closest to the city-wide result.
* `urne_vs_brief`: polling-station voters compared with postal voters.
* `swing`: change per district between two elections. Lists are matched by
  label, districts by name or number.

Kommunalwahl:

* `seat_allocation`: Sainte-Laguë/Schepers, the Bavarian method since 2020
  (Art. 35 GLKrWG). A tie for the last seat is flagged. Listenverbindungen are
  not modelled.
* `candidates`: city-wide votes, rank within the list, places gained against
  the list position ("hochgewählt"), elected or Listennachfolger.
* `candidate_districts`: one candidate per district. It gives their share of
  their own list's votes there, and the **home advantage** (`heimvorteil`) as
  that share divided by their city-wide share. A value of 2 means the
  candidate is twice as strong within their list as on average, which usually
  points to their own neighbourhood.
* `candidate_strongholds`, `district_winners`, `list_voting` (how much a
  list's votes concentrate on its top candidate).

Maps (`geo.plot_share`, `geo.plot_candidate`, `geo.folium_map`) place every
Stimmbezirk at its polling station from `data/Ansbach_Wahllokale.geojson`.
Briefwahlbezirke have no geography, so they appear in the tables but not on
the maps. If the city adds a polling station, add its coordinates to that file;
`geo.located` warns about stations it cannot place.

## Caveats

* Turnout per Urnenbezirk only counts voters at the polling station. Postal
  votes are counted in separate Briefwahlbezirke that cannot be assigned to
  neighbourhoods.
* Only the larger parties are named in `data/labels/` for 2024/2025. They were
  derived from the ballot order. The remaining columns keep their ids (`F8` …)
  until you add names.
* The automatic naming in `fetch` and the open data discovery have been tested
  against a mocked portal, not against the live site. Check the output, which
  lists how many columns could be named.
