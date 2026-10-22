"""Command line interface: ``python -m ansbach_votes <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import analysis, config


def _print(df) -> None:
    with pd.option_context("display.max_rows", 200, "display.max_columns", 30, "display.width", 200):
        print(df)


def cmd_list(args) -> None:
    for cfg in config.registry().values():
        try:
            status = str(cfg.results_file().relative_to(config.ROOT))
        except FileNotFoundError:
            status = "not fetched yet"
        print(f"{cfg.id:30} {cfg.name:30} {status}")


def cmd_fetch(args) -> None:
    from .fetch import fetch

    ids = args.election or [c.id for c in config.registry().values() if c.source_url]
    for election_id in ids:
        fetch(election_id, args.url, label=not args.no_labels)


def cmd_summary(args) -> None:
    e = config.load(args.election)
    print(e)
    _print(analysis.turnout_summary(e))
    for letter, ballot in e.ballots.items():
        print(f"\n{ballot.title} ({letter})")
        _print(analysis.city_totals(e, letter).head(args.top))
    if e.seats:
        print("\nSitzverteilung")
        _print(analysis.seat_allocation(e))


def cmd_district(args) -> None:
    e = config.load(args.election)
    if args.choice:
        _print(analysis.strongholds(e, args.choice, args.ballot, include_brief=args.brief))
    elif args.wahllokal:
        _print(analysis.by_wahllokal(e, args.ballot))
    else:
        _print(analysis.districts(e, args.ballot, include_brief=args.brief))


def cmd_swing(args) -> None:
    old, new = config.load(args.old), config.load(args.new)
    _print(analysis.swing(old, new, old_letter=args.old_ballot, new_letter=args.new_ballot, key=args.key))


def cmd_candidates(args) -> None:
    e = config.load(args.election)
    if args.name:
        d = analysis.candidate_districts(e, args.name, args.ballot, include_brief=args.brief)
        print(f"{d.attrs['candidate']} ({d.attrs['list']})")
        _print(d)
    elif args.district:
        w = analysis.district_winners(e, args.ballot, top=args.top)
        _print(w[w.gebietsname.str.contains(args.district, case=False, regex=False)])
    else:
        c = analysis.candidates(e, args.ballot)
        if args.list:
            col = e.ballot(args.ballot).column_for(args.list)
            c = c[c.liste_spalte == col]
        _print(c.head(args.top))


def cmd_report(args) -> None:
    from .report import write_report

    for election_id in args.election or list(config.registry()):
        try:
            e = config.load(election_id)
        except FileNotFoundError as exc:
            print(exc)
            continue
        write_report(e, Path(args.out) / election_id if args.out else None, maps=not args.no_maps)


def cmd_import_candidates(args) -> None:
    n = config.import_candidates(config.get(args.election), Path(args.csv), args.ballot or "D")
    print(f"imported {n} candidates into {config.get(args.election).labels_path.relative_to(config.ROOT)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m ansbach_votes", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="known elections and their data files")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("fetch", help="download the latest results from the official portal")
    s.add_argument("election", nargs="*", help="election ids (default: all with a source_url)")
    s.add_argument("--url", help="override the portal / open data URL")
    s.add_argument("--no-labels", action="store_true", help="do not name columns automatically")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("summary", help="city-wide result, turnout and seats")
    s.add_argument("election")
    s.add_argument("--top", type=int, default=15)
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("districts", help="results per Stimmbezirk / Wahllokal")
    s.add_argument("election")
    s.add_argument("choice", nargs="?", help="list/party: rank the districts by its share")
    s.add_argument("--ballot", help="ballot letter, e.g. D (Erststimme) or F (Zweitstimme)")
    s.add_argument("--wahllokal", action="store_true", help="aggregate per polling station")
    s.add_argument("--brief", action="store_true", help="include Briefwahlbezirke")
    s.set_defaults(func=cmd_district)

    s = sub.add_parser("swing", help="change of shares per district between two elections")
    s.add_argument("old")
    s.add_argument("new")
    s.add_argument("--old-ballot")
    s.add_argument("--new-ballot")
    s.add_argument("--key", default="gebietsname", choices=["gebietsname", "bezirksnummer"])
    s.set_defaults(func=cmd_swing)

    s = sub.add_parser("candidates", help="per-candidate analysis (Stadtratswahl)")
    s.add_argument("election")
    s.add_argument("name", nargs="?", help="candidate (name or column like D3_12): results per district")
    s.add_argument("--list", help="only candidates of this list")
    s.add_argument("--district", help="top candidates in districts whose name contains this")
    s.add_argument("--ballot")
    s.add_argument("--top", type=int, default=50)
    s.add_argument("--brief", action="store_true", help="include Briefwahlbezirke")
    s.set_defaults(func=cmd_candidates)

    s = sub.add_parser("report", help="write all tables + interactive maps to reports/")
    s.add_argument("election", nargs="*")
    s.add_argument("--out")
    s.add_argument("--no-maps", action="store_true")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("import-candidates", help="name candidate columns from a CSV (liste,platz,name)")
    s.add_argument("election")
    s.add_argument("csv")
    s.add_argument("--ballot")
    s.set_defaults(func=cmd_import_candidates)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except (KeyError, FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
