"""Election registry (``data/elections.toml``), label files and loading."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import okvote

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
LABELS = DATA / "labels"
REGISTRY = DATA / "elections.toml"


@dataclass
class ElectionConfig:
    id: str
    name: str
    kind: str
    date: str | None = None
    file: str | None = None
    file_match: str | None = None
    source_url: str | None = None
    seats: int | None = None

    @property
    def raw_dir(self) -> Path:
        return RAW / self.id

    @property
    def labels_path(self) -> Path:
        return LABELS / f"{self.id}.json"

    def results_file(self) -> Path:
        """The CSV to analyse: the configured ``file`` or the best match in ``raw/<id>/``."""
        if self.file:
            path = DATA / self.file
            if path.exists():
                return path
        candidates = []
        for path in sorted(self.raw_dir.glob("*.csv")) if self.raw_dir.exists() else []:
            with path.open("rb") as fh:
                head = fh.readline()
            if b"Gebietsnummer" in head:
                candidates.append(path)
        if self.file_match and len(candidates) > 1:
            matching = [p for p in candidates if re.search(self.file_match, p.name)]
            candidates = matching or candidates
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise FileNotFoundError(
                f"no results for {self.id!r} yet – run `python -m ansbach_votes fetch {self.id}`"
            )
        names = ", ".join(p.name for p in candidates)
        raise FileNotFoundError(f"several CSVs for {self.id!r} ({names}); set `file` or `file_match` in {REGISTRY.name}")


def registry(path: Path = REGISTRY) -> dict[str, ElectionConfig]:
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    out = {}
    for key, entry in raw.items():
        entry = dict(entry)
        if "date" in entry:
            entry["date"] = str(entry["date"])
        out[key] = ElectionConfig(id=key, **entry)
    return out


def get(election_id: str) -> ElectionConfig:
    reg = registry()
    if election_id not in reg:
        raise KeyError(f"unknown election {election_id!r}; known: {', '.join(reg)}")
    return reg[election_id]


def load_labels(cfg: ElectionConfig) -> dict[str, str]:
    """Column id -> name. Manual entries (``columns``) win over fetched ones (``auto``)."""
    if not cfg.labels_path.exists():
        return {}
    data = json.loads(cfg.labels_path.read_text(encoding="utf-8"))
    return {**data.get("auto", {}), **data.get("columns", {})}


def save_auto_labels(cfg: ElectionConfig, auto: dict[str, str], source: str) -> Path:
    data = {"columns": {}, "auto": {}}
    if cfg.labels_path.exists():
        data.update(json.loads(cfg.labels_path.read_text(encoding="utf-8")))
    data["auto"] = dict(sorted(auto.items(), key=lambda kv: okvote._sort_key(kv[0])))
    data["auto_source"] = source
    cfg.labels_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.labels_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cfg.labels_path


def import_candidates(cfg: ElectionConfig, csv_path: Path, letter: str = "D") -> int:
    """Merge a hand-made candidate list into the manual labels.

    The CSV needs the columns ``liste`` (number of the Wahlvorschlag),
    ``platz`` (list position) and ``name``; an optional ``wahlvorschlag``
    column names the list itself. That is exactly what the official
    "Bekanntmachung der zugelassenen Wahlvorschläge" contains.
    """
    import pandas as pd

    df = pd.read_csv(csv_path, dtype=str, sep=None, engine="python").fillna("")
    data = {"columns": {}, "auto": {}}
    if cfg.labels_path.exists():
        data.update(json.loads(cfg.labels_path.read_text(encoding="utf-8")))
    for row in df.itertuples():
        data["columns"][f"{letter}{int(row.liste)}_{int(row.platz)}"] = row.name.strip()
        if getattr(row, "wahlvorschlag", ""):
            data["columns"][f"{letter}{int(row.liste)}"] = row.wahlvorschlag.strip()
    data["columns"] = dict(sorted(data["columns"].items(), key=lambda kv: okvote._sort_key(kv[0])))
    cfg.labels_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.labels_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(df)


def load(election_id: str) -> okvote.Election:
    """Load an election from the registry, with its labels applied."""
    cfg = get(election_id)
    path = cfg.results_file()
    return okvote.parse(
        okvote.read_csv(path),
        election_id=cfg.id,
        name=cfg.name,
        kind=cfg.kind,
        seats=cfg.seats,
        labels=load_labels(cfg),
        source=path,
    )
