import io

import pandas as pd
import pytest

from ansbach_votes import okvote

HEADER = ("Gemeinde;Gemeindename;Wahlkreisnummer;Gebietsnummer;Gebietsart;Gebietsname;Bezirksnummer;"
          "Ausgezaehlt abweichend Gebiet;Ausgezaehlt abweichend AGS;Ausbleibend;Wahlberechtigte gesamt (A);"
          "Wahlberechtigte ohne Wahlschein (A1);Wahlberechtigte mit Wahlschein (A2);"
          "Wahlberechtigte nicht im WVZ (A3);Waehler gesamt (B);Waehler ohne Wahlschein;Waehler mit Wahlschein;"
          "Urnenwaehler mit Wahlschein in Urnenwahllokal;Briefwaehler mit Wahlschein in Urnenwahllokal;"
          "Stimmen ungueltige (C);Stimmen gueltige (D)")

# Synthetic council election: 3 lists x 3 candidates, 4 seats.
# district -> {candidate column: votes}
COUNCIL = {
    ("095610000001", "STIMMBEZIRK", "1 Eyb", "1"): {
        "D1_1": 100, "D1_2": 20, "D1_3": 10, "D2_1": 50, "D2_2": 60, "D2_3": 5, "D3_1": 10, "D3_2": 5, "D3_3": 0},
    ("095610000002", "STIMMBEZIRK", "2 Eyb", "2"): {
        "D1_1": 80, "D1_2": 10, "D1_3": 50, "D2_1": 40, "D2_2": 20, "D2_3": 5, "D3_1": 20, "D3_2": 10, "D3_3": 5},
    ("095610000041", "BRIEFWAHLBEZIRK", "Briefwahl 1", "41"): {
        "D1_1": 60, "D1_2": 30, "D1_3": 10, "D2_1": 30, "D2_2": 10, "D2_3": 10, "D3_1": 5, "D3_2": 5, "D3_3": 0},
}


def council_csv(with_list_columns: bool = True) -> str:
    cand_cols = list(next(iter(COUNCIL.values())))
    list_cols = ["D1", "D2", "D3"]
    cols = []
    for lst in list_cols:
        if with_list_columns:
            cols.append(lst)
        cols += [c for c in cand_cols if c.startswith(lst + "_")]
    lines = [HEADER + ";" + ";".join(cols) + ";"]
    rows = []
    for (gid, art, name, nr), votes in COUNCIL.items():
        lists = {lst: sum(v for c, v in votes.items() if c.startswith(lst + "_")) for lst in list_cols}
        valid = sum(votes.values())
        wb = 0 if art == "BRIEFWAHLBEZIRK" else 100
        rows.append((gid, art, name, nr, wb, 40, valid, votes, lists))
    tot_votes = {c: sum(r[7][c] for r in rows) for c in cand_cols}
    tot_lists = {lst: sum(r[8][lst] for r in rows) for lst in list_cols}
    rows.insert(0, ("09561000", "GEMEINDE", "Stadt Ansbach", "", 200, 120, sum(tot_votes.values()), tot_votes, tot_lists))
    for gid, art, name, nr, wb, waehler, valid, votes, lists in rows:
        values = {**votes, **lists}
        meta = ["09561000", "Stadt Ansbach", "561", gid, art, name, nr, "", "", "N", wb, wb - 10, 10, 0,
                waehler, waehler - 10, 10, 0, 0, 1, valid]
        lines.append(";".join(map(str, meta + [values[c] for c in cols])) + ";")
    return "\n".join(lines) + "\n"


LABELS = {"D1": "CSU", "D2": "SPD", "D3": "GRÜNE",
          "D1_1": "Anna A", "D1_2": "Bernd B", "D1_3": "Clara C",
          "D2_1": "Dora D", "D2_2": "Emil E", "D2_3": "Frida F",
          "D3_1": "Gerd G", "D3_2": "Hanna H", "D3_3": "Ida I"}


@pytest.fixture
def council_path(tmp_path):
    path = tmp_path / "Open-Data-Stadtratswahl.csv"
    path.write_text(council_csv(), encoding="utf-8")
    return path


@pytest.fixture
def council(council_path):
    df = okvote.read_csv(council_path)
    return okvote.parse(df, election_id="test", name="Test-Stadtratswahl", kind="stadtratswahl",
                        seats=4, labels=LABELS)


@pytest.fixture
def council_df():
    return pd.read_csv(io.StringIO(council_csv()), sep=";", dtype=str, keep_default_na=False)
