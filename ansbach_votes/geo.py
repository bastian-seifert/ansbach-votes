"""Maps: results per polling station on top of the city boundary.

Stimmbezirke are located by their polling station (``data/Ansbach_Wahllokale.geojson``).
Briefwahlbezirke have no geography and are left off the maps.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

import pandas as pd

from . import analysis
from .config import DATA
from .okvote import Election

WAHLLOKALE = DATA / "Ansbach_Wahllokale.geojson"
STADT = DATA / "Ansbach_Stadt.geojson"


def polling_stations(path: Path = WAHLLOKALE) -> pd.DataFrame:
    """Polling station name -> lon/lat (Briefwahl placeholders are skipped)."""
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    rows = [{"wahllokal": f["properties"]["name"], "lon": f["geometry"]["coordinates"][0],
             "lat": f["geometry"]["coordinates"][1]}
            for f in features if not f["properties"]["name"].startswith("Briefwahl")]
    return pd.DataFrame(rows).set_index("wahllokal")


def city_outline(path: Path = STADT) -> list[list[tuple[float, float]]]:
    rings = []
    for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        rings += [[tuple(p) for p in poly[0]] for poly in polys]
    return rings


def located(table: pd.DataFrame, stations: pd.DataFrame | None = None) -> pd.DataFrame:
    """Join a ``by_wahllokal`` table with coordinates; warns about unknown stations."""
    stations = polling_stations() if stations is None else stations
    missing = sorted(set(table.index) - set(stations.index))
    if missing:
        print(f"no coordinates for: {', '.join(missing)} – add them to {WAHLLOKALE.name}")
    return table.join(stations, how="inner")


def plot_share(election: Election, choice: str, letter: str | None = None, *, ax=None, cmap: str = "Blues"):
    """Static map: one dot per polling station, colour = share of ``choice``."""
    import matplotlib.pyplot as plt

    ballot = election.ballot(letter)
    label = ballot.label(ballot.column_for(choice))
    table = located(analysis.by_wahllokal(election, letter))
    if ax is None:
        _, ax = plt.subplots(figsize=(9, 9))
    for ring in city_outline():
        xs, ys = zip(*ring)
        ax.plot(xs, ys, color="#888", linewidth=1)
    sc = ax.scatter(table.lon, table.lat, c=table[label], s=40 + table.wahlberechtigte / 15,
                    cmap=cmap, edgecolors="white", linewidths=1.5, zorder=3)
    for name, r in table.iterrows():
        ax.annotate(f"{name}\n{r[label]:.1f} %", (r.lon, r.lat), fontsize=7, xytext=(6, 4),
                    textcoords="offset points", color="#333")
    city = analysis.city_totals(election, letter).loc[label, "anteil"]
    ax.set_title(f"{election.name}: {label} (stadtweit {city:.1f} %)")
    ax.set_aspect(1 / 0.65)  # ~cos(49.3°)
    ax.set_axis_off()
    plt.colorbar(sc, ax=ax, shrink=0.6, label=f"Anteil {label} in %")
    return ax


def plot_candidate(election: Election, candidate: str, letter: str | None = None, *, ax=None,
                   cmap: str = "Purples"):
    """Static map of a candidate's home advantage (share within the own list vs. city-wide)."""
    import matplotlib.pyplot as plt

    per_station = analysis.candidate_by_wahllokal(election, candidate, letter)
    table = located(per_station)
    if ax is None:
        _, ax = plt.subplots(figsize=(9, 9))
    for ring in city_outline():
        xs, ys = zip(*ring)
        ax.plot(xs, ys, color="#888", linewidth=1)
    sc = ax.scatter(table.lon, table.lat, c=table.heimvorteil, s=40 + table.stimmen * 2, cmap=cmap,
                    edgecolors="white", linewidths=1.5, zorder=3)
    for name, r in table.iterrows():
        ax.annotate(f"{name}\n{int(r.stimmen)} St. ({r.anteil_an_liste:.1f} %)", (r.lon, r.lat), fontsize=7,
                    xytext=(6, 4), textcoords="offset points", color="#333")
    ax.set_title(f"{election.name}: {per_station.attrs['candidate']} ({per_station.attrs['list']})")
    ax.set_aspect(1 / 0.65)
    ax.set_axis_off()
    plt.colorbar(sc, ax=ax, shrink=0.6, label="Heimvorteil (1 = wie stadtweit)")
    return ax


def folium_map(election: Election, letter: str | None = None, *, choices: list[str] | None = None,
               min_share: float = 2.0):
    """Interactive map with one switchable layer per list (requires ``folium``)."""
    import branca.colormap as cm
    import folium

    ballot = election.ballot(letter)
    table = located(analysis.by_wahllokal(election, letter))
    city = analysis.city_totals(election, letter)
    if choices is None:
        choices = [c for c in city.index if city.at[c, "anteil"] >= min_share]
    else:
        choices = [ballot.label(ballot.column_for(c)) for c in choices]
    m = folium.Map(location=[table.lat.mean(), table.lon.mean()], zoom_start=12, tiles="OpenStreetMap")
    folium.GeoJson(json.loads(STADT.read_text(encoding="utf-8")), name="Stadtgebiet",
                   style_function=lambda _: {"color": "#555", "weight": 2, "fillOpacity": 0.03}).add_to(m)
    for i, choice in enumerate(choices):
        values = table[choice]
        scale = cm.LinearColormap(["#deebf7", "#08519c"], vmin=values.min(), vmax=values.max())
        layer = folium.FeatureGroup(name=f"{choice} (stadtweit {city.at[choice, 'anteil']:.1f} %)", show=i == 0, overlay=False)
        for name, r in table.iterrows():
            others = "".join(f"<tr><td>{escape(c)}</td><td style='text-align:right'>{r[c]:.1f} %</td></tr>"
                             for c in choices)
            popup = (f"<b>{escape(name)}</b> ({int(r.bezirke)} Bezirk(e))<br>"
                     f"Beteiligung Urne: {r.beteiligung_urne:.1f} %<table>{others}</table>")
            folium.CircleMarker(
                [r.lat, r.lon], radius=6 + r.wahlberechtigte ** 0.5 / 6, color="white", weight=2,
                fill=True, fill_color=scale(r[choice]), fill_opacity=0.9,
                tooltip=f"{name}: {choice} {r[choice]:.1f} %", popup=folium.Popup(popup, max_width=300),
            ).add_to(layer)
        layer.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    return m
