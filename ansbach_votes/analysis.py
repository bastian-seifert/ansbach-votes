"""District-level ("hyperregional") analysis on top of :mod:`okvote`."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .okvote import BRIEF, TOTAL, URNE, Ballot, Election


def wahllokal_name(gebietsname: str) -> str:
    """``"14 Luitpoldschule"`` -> ``"Luitpoldschule"``; Briefwahl names stay as they are."""
    return re.sub(r"^\d+\s+", "", gebietsname).strip()


def districts(election: Election, letter: str | None = None, *, include_brief: bool = True,
              labelled: bool = True) -> pd.DataFrame:
    """One row per Stimm-/Briefwahlbezirk: turnout indicators and the share of every list (in %)."""
    ballot = election.ballot(letter)
    ids = election.district_ids(include_brief)
    a = election.areas.loc[ids]
    out = a[["gebietsart", "gebietsname", "bezirksnummer"]].copy()
    out["wahllokal"] = out.gebietsname.map(wahllokal_name)
    out = out.join(_turnout(a))
    out["gueltige"] = ballot.valid.loc[ids]
    shares = ballot.lists.loc[ids].div(ballot.valid.loc[ids].replace(0, np.nan), axis=0) * 100
    if labelled:
        shares = shares.rename(columns=ballot.label)
    return out.join(shares.round(2))


def _turnout(a: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=a.index)
    if "wahlberechtigte" in a:
        wb = a.wahlberechtigte.replace(0, np.nan)
        out["wahlberechtigte"] = a.wahlberechtigte
        out["waehler"] = a.waehler
        # For Urnenbezirke this is the turnout *at the polling station*; postal
        # voters of the district are counted in the Briefwahlbezirke.
        out["beteiligung_urne"] = (a.waehler / wb * 100).round(2)
        if "wahlberechtigte_mit_wahlschein" in a:
            out["wahlschein_quote"] = (a.wahlberechtigte_mit_wahlschein / wb * 100).round(2)
    return out


def city_totals(election: Election, letter: str | None = None, *, labelled: bool = True) -> pd.DataFrame:
    """Votes and share per list for the whole city."""
    ballot = election.ballot(letter)
    total = election.total_id
    votes = ballot.lists.loc[total]
    out = pd.DataFrame({"stimmen": votes, "anteil": (votes / ballot.valid.loc[total] * 100).round(2)})
    if labelled:
        out.index = out.index.map(ballot.label)
    return out.sort_values("stimmen", ascending=False)


def turnout_summary(election: Election) -> pd.Series:
    a = election.areas.loc[election.total_id]
    s = pd.Series({"wahlberechtigte": a.wahlberechtigte, "waehler": a.waehler,
                   "wahlbeteiligung": round(a.waehler / a.wahlberechtigte * 100, 2)})
    if "waehler_mit_wahlschein" in a:
        s["briefwahl_anteil"] = round(a.waehler_mit_wahlschein / a.waehler * 100, 2)
    return s


def by_wahllokal(election: Election, letter: str | None = None, *, labelled: bool = True) -> pd.DataFrame:
    """Aggregate the Urnenbezirke sharing one polling station (sum of votes, then shares)."""
    ballot = election.ballot(letter)
    ids = election.district_ids(include_brief=False)
    names = election.areas.loc[ids, "gebietsname"].map(wahllokal_name)
    votes = ballot.lists.loc[ids].groupby(names).sum()
    valid = ballot.valid.loc[ids].groupby(names).sum()
    shares = votes.div(valid.replace(0, np.nan), axis=0) * 100
    if labelled:
        shares = shares.rename(columns=ballot.label)
    a = election.areas.loc[ids].groupby(names)[["wahlberechtigte", "waehler"]].sum()
    a["beteiligung_urne"] = (a.waehler / a.wahlberechtigte * 100).round(2)
    a["bezirke"] = names.value_counts()
    a["gueltige"] = valid
    a.index.name = "wahllokal"
    return a.join(shares.round(2))


def urne_vs_brief(election: Election, letter: str | None = None) -> pd.DataFrame:
    """Share of each list among polling-station vs. postal voters."""
    ballot = election.ballot(letter)
    out = {}
    for kind, label in ((URNE, "urne"), (BRIEF, "brief")):
        ids = election.areas.index[election.areas.gebietsart == kind]
        out[label] = ballot.lists.loc[ids].sum() / ballot.valid.loc[ids].sum() * 100
    df = pd.DataFrame(out).round(2)
    df["differenz_pp"] = (df.brief - df.urne).round(2)
    df.index = df.index.map(ballot.label)
    return df.sort_values("urne", ascending=False)


def strongholds(election: Election, choice: str, letter: str | None = None, *,
                include_brief: bool = False) -> pd.DataFrame:
    """Districts ranked by the share of ``choice`` (column id or label).

    ``abweichung_pp`` is the difference to the city-wide share in percentage
    points, ``index`` the ratio to it (1.25 = 25 % stronger than city-wide).
    """
    ballot = election.ballot(letter)
    col = ballot.column_for(choice)
    ids = election.district_ids(include_brief)
    total = election.total_id
    city = ballot.lists.at[total, col] / ballot.valid.at[total] * 100
    share = ballot.lists.loc[ids, col] / ballot.valid.loc[ids].replace(0, np.nan) * 100
    out = election.areas.loc[ids, ["gebietsname"]].copy()
    out["stimmen"] = ballot.lists.loc[ids, col]
    out["anteil"] = share.round(2)
    out["abweichung_pp"] = (share - city).round(2)
    out["index"] = (share / city).round(3)
    return out.sort_values("anteil", ascending=False)


def correlations(election: Election, letter: str | None = None, *, min_share: float = 2.0) -> pd.DataFrame:
    """Correlation of list shares across Urnenbezirke: which electorates live in the same streets?"""
    ballot = election.ballot(letter)
    city = city_totals(election, letter, labelled=False)
    cols = city.index[city.anteil >= min_share]
    shares = districts(election, letter, include_brief=False, labelled=False)[cols]
    return shares.rename(columns=ballot.label).corr().round(2)


def bellwether(election: Election, letter: str | None = None, *, min_share: float = 2.0) -> pd.DataFrame:
    """How closely each district mirrors the city result (mean absolute deviation in pp)."""
    city = city_totals(election, letter, labelled=False)
    cols = city.index[city.anteil >= min_share]
    d = districts(election, letter, include_brief=False, labelled=False)
    dev = (d[cols] - city.loc[cols, "anteil"]).abs()
    out = d[["gebietsname"]].copy()
    out["mittlere_abweichung_pp"] = dev.mean(axis=1).round(2)
    out["max_abweichung_pp"] = dev.max(axis=1).round(2)
    return out.sort_values("mittlere_abweichung_pp")


def swing(old: Election, new: Election, *, old_letter: str | None = None, new_letter: str | None = None,
          key: str = "gebietsname", include_brief: bool = False) -> pd.DataFrame:
    """Change of list shares per district between two elections (in pp).

    Lists are matched by label, districts by ``key`` (``gebietsname`` or
    ``bezirksnummer``). Only lists labelled in both elections are compared;
    districts that were redrawn simply drop out of the join.
    """
    frames = []
    for e, letter in ((old, old_letter), (new, new_letter)):
        d = districts(e, letter, include_brief=include_brief)
        frames.append(d.set_index(key))
    a, b = frames
    lists_a = set(old.ballot(old_letter).labels.values())
    lists_b = set(new.ballot(new_letter).labels.values())
    common = sorted(lists_a & lists_b)
    if not common:
        raise ValueError("no list labelled in both elections – add labels in data/labels/")
    keys = a.index.intersection(b.index)
    out = (b.loc[keys, common] - a.loc[keys, common]).round(2)
    out["beteiligung_urne"] = (b.beteiligung_urne - a.beteiligung_urne).reindex(out.index).round(2)
    return out


# --------------------------------------------------------------------------
# Council elections: seats and candidates


def sainte_lague(votes: dict[str, int] | pd.Series, seats: int) -> pd.DataFrame:
    """Highest-averages allocation with divisors 0.5, 1.5, 2.5 … (Sainte-Laguë/Schepers).

    Used for Bavarian Stadtrats-/Gemeinderatswahlen since 2020 (Art. 35
    GLKrWG). A tie for the last seat is decided by lot – flagged in
    ``los_noetig``. Listenverbindungen are not modelled.
    """
    votes = pd.Series(votes, dtype=float)
    quotients = sorted(
        ((v / (k + 0.5), name) for name, v in votes.items() if v > 0 for k in range(seats)),
        key=lambda t: -t[0],
    )
    won = pd.Series(0, index=votes.index, dtype=int)
    for _, name in quotients[:seats]:
        won[name] += 1
    tie = len(quotients) > seats and np.isclose(quotients[seats - 1][0], quotients[seats][0])
    out = pd.DataFrame({"stimmen": votes.astype(int), "sitze": won})
    out["anteil"] = (votes / votes.sum() * 100).round(2)
    out["sitzanteil"] = (won / seats * 100).round(2)
    out.attrs["los_noetig"] = bool(tie)
    return out.sort_values(["sitze", "stimmen"], ascending=False)


def seat_allocation(election: Election, letter: str | None = None) -> pd.DataFrame:
    if not election.seats:
        raise ValueError(f"{election.id}: number of seats unknown – set `seats` in elections.toml")
    ballot = election.ballot(letter)
    out = sainte_lague(ballot.lists.loc[election.total_id], election.seats)
    out.insert(0, "liste", out.index.map(ballot.label))
    return out


def _candidate_meta(ballot: Ballot) -> pd.DataFrame:
    cols = ballot.candidates.columns
    meta = pd.DataFrame(index=cols)
    meta.index.name = "spalte"
    meta["liste_spalte"] = [c.split("_")[0] for c in cols]
    meta["liste"] = meta.liste_spalte.map(ballot.label)
    meta["listenplatz"] = [int(c.split("_")[1]) for c in cols]
    meta["name"] = [ballot.labels.get(c, c) for c in cols]
    return meta


def candidates(election: Election, letter: str | None = None) -> pd.DataFrame:
    """One row per candidate with city-wide votes, list rank and election outcome.

    * ``rang_in_liste`` – rank by personal votes within the list
    * ``plaetze_gewonnen`` – list position minus rank (positive = "hochgewählt")
    * ``gewaehlt`` – elected given the seat allocation; ties go to the better
      list position (Art. 37 GLKrWG). Others are ``Listennachfolger``.
    """
    ballot = election.ballot(letter)
    if not ballot.has_candidates:
        raise ValueError(f"{election.id}: no candidate columns (D<list>_<position>) in this file")
    total = election.total_id
    meta = _candidate_meta(ballot)
    meta["stimmen"] = ballot.candidates.loc[total]
    list_votes = ballot.lists.loc[total]
    meta["anteil_an_liste"] = (meta.stimmen / meta.liste_spalte.map(list_votes) * 100).round(2)
    meta["anteil_gesamt"] = (meta.stimmen / ballot.valid.loc[total] * 100).round(3)
    meta = meta.sort_values(["liste_spalte", "stimmen", "listenplatz"], ascending=[True, False, True])
    meta["rang_in_liste"] = meta.groupby("liste_spalte").cumcount() + 1
    meta["plaetze_gewonnen"] = meta.listenplatz - meta.rang_in_liste
    meta["rang_gesamt"] = meta.stimmen.rank(ascending=False, method="min").astype(int)
    if election.seats:
        seats = sainte_lague(list_votes, election.seats).sitze
        meta["sitze_liste"] = meta.liste_spalte.map(seats).fillna(0).astype(int)
        meta["gewaehlt"] = meta.rang_in_liste <= meta.sitze_liste
        meta["status"] = np.where(meta.gewaehlt, "gewählt",
                                  "Nachfolger " + (meta.rang_in_liste - meta.sitze_liste).astype(str))
    return meta.sort_values("stimmen", ascending=False)


def candidate_districts(election: Election, candidate: str, letter: str | None = None, *,
                        include_brief: bool = True) -> pd.DataFrame:
    """Where does a candidate collect votes? One row per district.

    ``anteil_an_liste`` = the candidate's share of their own list's votes in the
    district; ``heimvorteil`` = that share relative to the city-wide one
    (2.0 = twice as strong within the list as on average – typical for the
    candidate's home neighbourhood).
    """
    ballot = election.ballot(letter)
    col = ballot.column_for(candidate)
    if col not in ballot.candidates.columns:
        raise KeyError(f"{candidate!r} is a list, not a candidate")
    lst = col.split("_")[0]
    ids = election.district_ids(include_brief)
    total = election.total_id
    votes = ballot.candidates.loc[ids, col]
    list_votes = ballot.lists.loc[ids, lst].replace(0, np.nan)
    city_share = ballot.candidates.at[total, col] / ballot.lists.at[total, lst]
    out = election.areas.loc[ids, ["gebietsart", "gebietsname"]].copy()
    out["stimmen"] = votes
    out["anteil_an_liste"] = (votes / list_votes * 100).round(2)
    out["anteil_gesamt"] = (votes / ballot.valid.loc[ids].replace(0, np.nan) * 100).round(3)
    out["heimvorteil"] = (votes / list_votes / city_share).round(2)
    # Rank of the candidate among all candidates of their list in this district
    same_list = [c for c in ballot.candidates.columns if c.split("_")[0] == lst]
    ranks = ballot.candidates.loc[ids, same_list].rank(axis=1, ascending=False, method="min")
    out["rang_in_liste"] = ranks[col].astype(int)
    out.attrs.update(candidate=ballot.label(col), list=ballot.label(lst), column=col)
    return out.sort_values("heimvorteil", ascending=False)


def candidate_strongholds(election: Election, letter: str | None = None, *, top: int = 3,
                          include_brief: bool = False) -> pd.DataFrame:
    """For every candidate the districts with the largest home advantage."""
    ballot = election.ballot(letter)
    rows = []
    for col in ballot.candidates.columns:
        d = candidate_districts(election, col, letter, include_brief=include_brief)
        d = d[d.stimmen > 0].head(top)
        for gid, r in d.iterrows():
            rows.append({"spalte": col, "name": ballot.label(col), "liste": ballot.label(col.split("_")[0]),
                         "gebietsnummer": gid, "gebietsname": r.gebietsname, "stimmen": r.stimmen,
                         "anteil_an_liste": r.anteil_an_liste, "heimvorteil": r.heimvorteil})
    return pd.DataFrame(rows)


def district_winners(election: Election, letter: str | None = None, *, top: int = 5,
                     include_brief: bool = True) -> pd.DataFrame:
    """The ``top`` candidates (any list) per district."""
    ballot = election.ballot(letter)
    ids = election.district_ids(include_brief)
    rows = []
    for gid in ids:
        best = ballot.candidates.loc[gid].sort_values(ascending=False).head(top)
        for rank, (col, v) in enumerate(best.items(), 1):
            rows.append({"gebietsnummer": gid, "gebietsname": election.areas.at[gid, "gebietsname"],
                         "rang": rank, "name": ballot.label(col), "liste": ballot.label(col.split("_")[0]),
                         "stimmen": v})
    return pd.DataFrame(rows)


def list_voting(election: Election, letter: str | None = None) -> pd.DataFrame:
    """How concentrated are a list's votes on its top candidate(s)?

    ``anteil_spitze`` = share of the list's votes going to its most popular
    candidate; ``effektive_kandidaten`` = inverse Herfindahl index of the
    candidate votes (high = votes spread evenly, e.g. pure list votes).
    """
    ballot = election.ballot(letter)
    total = election.total_id
    meta = _candidate_meta(ballot)
    meta["stimmen"] = ballot.candidates.loc[total]
    rows = []
    for lst, g in meta.groupby("liste_spalte"):
        v = g.stimmen
        s = v / v.sum() if v.sum() else v
        top = g.loc[v.idxmax()] if v.sum() else None
        rows.append({"liste": ballot.label(lst), "kandidaten": len(g), "stimmen": int(v.sum()),
                     "spitze": top["name"] if top is not None else None,
                     "anteil_spitze": round(float(s.max()) * 100, 2) if v.sum() else None,
                     "effektive_kandidaten": round(1 / float((s ** 2).sum()), 1) if v.sum() else None})
    return pd.DataFrame(rows).set_index("liste").sort_values("stimmen", ascending=False)


def candidate_by_wahllokal(election: Election, candidate: str, letter: str | None = None) -> pd.DataFrame:
    """:func:`candidate_districts` aggregated per polling station (for maps)."""
    ballot = election.ballot(letter)
    col = ballot.column_for(candidate)
    lst = col.split("_")[0]
    ids = election.district_ids(include_brief=False)
    names = election.areas.loc[ids, "gebietsname"].map(wahllokal_name)
    votes = ballot.candidates.loc[ids, col].groupby(names).sum()
    list_votes = ballot.lists.loc[ids, lst].groupby(names).sum().replace(0, np.nan)
    total = election.total_id
    city_share = ballot.candidates.at[total, col] / ballot.lists.at[total, lst]
    out = pd.DataFrame({"stimmen": votes, "anteil_an_liste": (votes / list_votes * 100).round(2),
                        "heimvorteil": (votes / list_votes / city_share).round(2)})
    out.index.name = "wahllokal"
    out.attrs.update(candidate=ballot.label(col), list=ballot.label(lst))
    return out
