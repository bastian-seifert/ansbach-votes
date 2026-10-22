"""Parser for the OK.VOTE open data CSV export used by the city of Ansbach.

One row per area (Gemeinde, Stimmbezirk, Briefwahlbezirk). After the
metadata columns follow, per ballot letter, the invalid/valid totals and one
column per choice::

    Stimmen ungueltige (C);Stimmen gueltige (D);D1;D2;...      Europawahl
    Direktstimmen gueltige (D);D1;...;Listenstimmen gueltige (F);F1;...  BTW

Council elections additionally carry one column per candidate, ``D<list>_<pos>``
(e.g. ``D3_12`` = list 3, position 12). Columns with a non-numeric suffix
(``D3_liste`` …) are kept as list-level extras.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

TOTAL = "GEMEINDE"
URNE = "STIMMBEZIRK"
BRIEF = "BRIEFWAHLBEZIRK"

CHOICE_RE = re.compile(r"^([D-Z])(\d+)(?:_(\w+))?$")
VALID_RE = re.compile(r"(?<!un)gueltige.*\(([D-Z])\)", re.IGNORECASE)
INVALID_RE = re.compile(r"ungueltige.*\(([C-Z])\)", re.IGNORECASE)

# Area metadata, renamed to snake_case. Missing columns are tolerated.
AREA_COLUMNS = {
    "Gebietsnummer": "gebietsnummer",
    "Gebietsart": "gebietsart",
    "Gebietsname": "gebietsname",
    "Bezirksnummer": "bezirksnummer",
    "Wahlberechtigte gesamt (A)": "wahlberechtigte",
    "Wahlberechtigte ohne Wahlschein (A1)": "wahlberechtigte_ohne_wahlschein",
    "Wahlberechtigte mit Wahlschein (A2)": "wahlberechtigte_mit_wahlschein",
    "Waehler gesamt (B)": "waehler",
    "Waehler ohne Wahlschein": "waehler_ohne_wahlschein",
    "Waehler mit Wahlschein": "waehler_mit_wahlschein",
}


@dataclass
class Ballot:
    """All results for one ballot letter (e.g. ``D`` = Erst-/Einzelstimme)."""

    letter: str
    title: str
    valid: pd.Series  # valid votes per area
    invalid: pd.Series | None
    lists: pd.DataFrame  # votes per area x list column (``D1`` …)
    candidates: pd.DataFrame  # votes per area x candidate column (``D1_1`` …)
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def has_candidates(self) -> bool:
        return not self.candidates.empty

    def label(self, column: str) -> str:
        return self.labels.get(column, column)

    def list_of(self, candidate_column: str) -> str:
        return candidate_column.split("_", 1)[0]

    def column_for(self, name: str) -> str:
        """Find a list/candidate column by column id or (case-insensitive) label."""
        if name in self.lists.columns or name in self.candidates.columns:
            return name
        wanted = name.casefold()
        matches = [c for c, lbl in self.labels.items() if lbl.casefold() == wanted]
        if not matches:
            matches = [c for c, lbl in self.labels.items() if wanted in lbl.casefold()]
        matches = [c for c in matches if c in self.lists.columns or c in self.candidates.columns]
        if len(matches) != 1:
            raise KeyError(f"{name!r} matches {matches or 'nothing'} on ballot {self.letter}")
        return matches[0]

    def labelled_lists(self) -> pd.DataFrame:
        return self.lists.rename(columns=self.label)


@dataclass
class Election:
    id: str
    name: str
    kind: str
    areas: pd.DataFrame  # index: gebietsnummer
    ballots: dict[str, Ballot]
    seats: int | None = None
    source: Path | None = None

    @property
    def total_id(self) -> str:
        return self.areas.index[self.areas.gebietsart == TOTAL][0]

    def district_ids(self, include_brief: bool = True) -> pd.Index:
        kinds = {URNE, BRIEF} if include_brief else {URNE}
        return self.areas.index[self.areas.gebietsart.isin(kinds)]

    def ballot(self, letter: str | None = None) -> Ballot:
        """The requested ballot; default is the "decisive" one (F for BTW, else D)."""
        if letter is None:
            letter = "F" if "F" in self.ballots else next(iter(self.ballots))
        return self.ballots[letter]

    def __repr__(self) -> str:
        ballots = ", ".join(
            f"{b.letter}: {b.lists.shape[1]} lists" + (f"/{b.candidates.shape[1]} candidates" if b.has_candidates else "")
            for b in self.ballots.values()
        )
        return f"<Election {self.id} {self.name!r} areas={len(self.areas)} {ballots}>"


def read_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            df = pd.read_csv(path, sep=";", dtype=str, encoding=encoding, keep_default_na=False)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 decodes everything
        raise ValueError(f"cannot decode {path}")
    df.columns = [c.strip() for c in df.columns]
    return df.loc[:, [c for c in df.columns if c and not c.startswith("Unnamed")]]


def _numeric(df: pd.DataFrame) -> pd.DataFrame:
    # "x" marks "no candidate here" in some exports; treat any non-number as 0.
    return df.apply(lambda s: pd.to_numeric(s.str.replace(".", "", regex=False), errors="coerce")).fillna(0).astype(int)


def parse(df: pd.DataFrame, *, election_id: str = "", name: str = "", kind: str = "",
          seats: int | None = None, labels: dict[str, str] | None = None,
          source: Path | None = None) -> Election:
    df = df.copy()
    if "Gebietsnummer" not in df.columns:
        raise ValueError("not an OK.VOTE results file: column 'Gebietsnummer' missing")
    df.index = df["Gebietsnummer"].str.strip()
    df.index.name = "gebietsnummer"

    present = {k: v for k, v in AREA_COLUMNS.items() if k in df.columns}
    areas = df[list(present)].rename(columns=present)
    areas["gebietsart"] = areas["gebietsart"].str.strip().str.upper()
    areas["gebietsname"] = areas["gebietsname"].str.strip()
    numeric_area_cols = [c for c in areas.columns if c not in ("gebietsnummer", "gebietsart", "gebietsname", "bezirksnummer")]
    areas[numeric_area_cols] = _numeric(areas[numeric_area_cols])
    areas = areas.drop(columns=["gebietsnummer"], errors="ignore")
    if TOTAL not in set(areas.gebietsart):
        raise ValueError("file has no GEMEINDE total row")

    valid_cols = {m.group(1): c for c in df.columns if (m := VALID_RE.search(c))}
    invalid_cols = {m.group(1): c for c in df.columns if (m := INVALID_RE.search(c))}
    labels = labels or {}

    ballots: dict[str, Ballot] = {}
    for letter, valid_col in valid_cols.items():
        list_cols, cand_cols, extra_cols = [], [], []
        for c in df.columns:
            m = CHOICE_RE.match(c)
            if not m or m.group(1) != letter:
                continue
            if m.group(3) is None:
                list_cols.append(c)
            elif m.group(3).isdigit():
                cand_cols.append(c)
            else:
                extra_cols.append(c)
        num = _numeric(df[list_cols + cand_cols + extra_cols])
        lists = num[list_cols].copy()
        candidates = num[cand_cols]
        # Some exports only carry candidate columns: derive the list totals.
        for lst in sorted({c.split("_")[0] for c in cand_cols + extra_cols} - set(list_cols), key=_sort_key):
            members = [c for c in cand_cols + extra_cols if c.split("_")[0] == lst]
            lists[lst] = num[members].sum(axis=1)
        lists = lists[sorted(lists.columns, key=_sort_key)]
        candidates = candidates[sorted(candidates.columns, key=_sort_key)]
        # the "(C)" invalid column belongs to the first ballot, "(E)" to "F"
        invalid_letter = chr(ord(letter) - 1)
        invalid = _numeric(df[[invalid_cols[invalid_letter]]]).iloc[:, 0] if invalid_letter in invalid_cols else None
        title = valid_col.split(" gueltige")[0].split(" ungueltige")[0]
        ballots[letter] = Ballot(
            letter=letter,
            title=title,
            valid=_numeric(df[[valid_col]]).iloc[:, 0],
            invalid=invalid,
            lists=lists,
            candidates=candidates,
            labels={k: v for k, v in labels.items() if k.startswith(letter)},
        )
    if not ballots:
        raise ValueError("no ballot columns found (expected e.g. 'Stimmen gueltige (D)')")
    return Election(election_id, name, kind, areas, ballots, seats, source)


def _sort_key(column: str) -> tuple:
    m = CHOICE_RE.match(column)
    if not m:
        return (column, 0, 0, "")
    suffix = m.group(3) or ""
    return (m.group(1), int(m.group(2)), int(suffix) if suffix.isdigit() else -1, suffix)


def candidate_position(column: str) -> tuple[str, int]:
    """``"D3_12"`` -> ``("D3", 12)``."""
    lst, pos = column.split("_", 1)
    return lst, int(pos)
