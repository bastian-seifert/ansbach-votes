"""Write all tables (and an interactive map) for one election to ``reports/<id>/``."""

from __future__ import annotations

from pathlib import Path

from . import analysis
from .config import ROOT
from .okvote import Election

REPORTS = ROOT / "reports"


def write_report(election: Election, out_dir: Path | None = None, *, maps: bool = True, log=print) -> Path:
    out = out_dir or REPORTS / election.id
    out.mkdir(parents=True, exist_ok=True)
    tables = {"wahlbeteiligung": analysis.turnout_summary(election).to_frame("wert")}
    for letter, ballot in election.ballots.items():
        suffix = "" if len(election.ballots) == 1 else f"_{letter}"
        tables[f"stadt{suffix}"] = analysis.city_totals(election, letter)
        tables[f"bezirke{suffix}"] = analysis.districts(election, letter)
        tables[f"wahllokale{suffix}"] = analysis.by_wahllokal(election, letter)
        tables[f"urne_vs_brief{suffix}"] = analysis.urne_vs_brief(election, letter)
        tables[f"korrelationen{suffix}"] = analysis.correlations(election, letter)
        tables[f"repraesentativitaet{suffix}"] = analysis.bellwether(election, letter)
        if election.seats:
            tables[f"sitzverteilung{suffix}"] = analysis.seat_allocation(election, letter)
        if ballot.has_candidates:
            tables[f"kandidaten{suffix}"] = analysis.candidates(election, letter)
            tables[f"listen{suffix}"] = analysis.list_voting(election, letter)
            tables[f"kandidaten_hochburgen{suffix}"] = analysis.candidate_strongholds(election, letter)
            tables[f"bezirkssieger{suffix}"] = analysis.district_winners(election, letter)
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv", encoding="utf-8")
    log(f"wrote {len(tables)} tables to {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    if maps:
        try:
            from . import geo

            for letter in election.ballots:
                path = out / f"karte_{letter}.html"
                geo.folium_map(election, letter).save(path)
                log(f"wrote {path.name}")
        except ImportError:
            log("folium not installed – skipping maps (pip install folium)")
    return out
