import pytest

from ansbach_votes import analysis, config, okvote

from .conftest import council_csv


def test_real_files_parse():
    btw = config.load("bundestagswahl_2025")
    assert set(btw.ballots) == {"D", "F"}
    assert btw.ballot().letter == "F"
    assert btw.ballots["F"].lists.shape[1] == 17
    total = btw.total_id
    # lists add up to the valid votes in every area
    for b in btw.ballots.values():
        assert (b.lists.sum(axis=1) == b.valid).all()
    assert btw.ballots["F"].invalid.loc[total] == 82
    eu = config.load("europawahl_2024")
    assert list(eu.ballots) == ["D"]
    assert len(eu.district_ids(include_brief=False)) == 31


def test_shares_and_strongholds():
    btw = config.load("bundestagswahl_2025")
    city = analysis.city_totals(btw)
    assert city.loc["CSU", "stimmen"] == 7204
    assert city.anteil.sum() == pytest.approx(100, abs=0.1)
    s = analysis.strongholds(btw, "afd")
    assert s.anteil.is_monotonic_decreasing
    assert not s.gebietsname.str.startswith("Briefwahl").any()


def test_wahllokal_aggregation_sums_districts():
    btw = config.load("bundestagswahl_2025")
    w = analysis.by_wahllokal(btw)
    assert w.loc["Luitpoldschule", "bezirke"] == 5
    assert w.wahlberechtigte.sum() == btw.areas.loc[btw.district_ids(False), "wahlberechtigte"].sum()
    # "Briefwahl 1" must not swallow "Briefwahl 10".."19" (bug of the old notebook)
    d = analysis.districts(btw)
    assert (d.wahllokal == "Briefwahl 1").sum() == 1


def test_swing_between_elections():
    sw = analysis.swing(config.load("europawahl_2024"), config.load("bundestagswahl_2025"))
    assert {"CSU", "AfD", "SPD", "GRÜNE"} <= set(sw.columns)
    assert len(sw) == 31


def test_sainte_lague():
    out = analysis.sainte_lague({"A": 10000, "B": 6000, "C": 1500}, 8)
    assert out.sitze.to_dict() == {"A": 4, "B": 3, "C": 1}
    tie = analysis.sainte_lague({"A": 100, "B": 100}, 1)
    assert tie.attrs["los_noetig"]


def test_council_parsing(council):
    b = council.ballot()
    assert list(b.lists.columns) == ["D1", "D2", "D3"]
    assert b.candidates.shape[1] == 9
    assert b.lists.at[council.total_id, "D1"] == 370


def test_list_totals_derived_from_candidates(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text(council_csv(with_list_columns=False), encoding="utf-8")
    e = okvote.parse(okvote.read_csv(path))
    assert e.ballot().lists.loc[e.total_id].to_dict() == {"D1": 370, "D2": 230, "D3": 60}


def test_seats_and_elected_candidates(council):
    seats = analysis.seat_allocation(council).set_index("liste").sitze
    assert seats.to_dict() == {"CSU": 2, "SPD": 2, "GRÜNE": 0}
    c = analysis.candidates(council).set_index("name")
    assert c.gewaehlt[c.gewaehlt].index.tolist() == ["Anna A", "Dora D", "Emil E", "Clara C"]
    # Clara (list position 3) overtook Bernd thanks to personal votes
    assert c.at["Clara C", "rang_in_liste"] == 2
    assert c.at["Clara C", "plaetze_gewonnen"] == 1
    assert c.at["Bernd B", "status"] == "Nachfolger 1"


def test_candidate_home_advantage(council):
    d = analysis.candidate_districts(council, "clara c")
    assert d.index[0] == "095610000002"
    assert d.iloc[0].anteil_an_liste == pytest.approx(50 / 140 * 100, abs=0.01)
    assert d.iloc[0].heimvorteil == pytest.approx((50 / 140) / (70 / 370), abs=0.01)
    assert d.iloc[0].rang_in_liste == 2


def test_candidate_lookup_errors(council):
    with pytest.raises(KeyError):
        analysis.candidate_districts(council, "CSU")  # a list, not a candidate
    with pytest.raises(KeyError):
        council.ballot().column_for("nobody")


def test_district_winners_and_list_voting(council):
    w = analysis.district_winners(council, top=1)
    assert w.set_index("gebietsname").name.to_dict() == {"1 Eyb": "Anna A", "2 Eyb": "Anna A", "Briefwahl 1": "Anna A"}
    lv = analysis.list_voting(council)
    assert lv.at["CSU", "spitze"] == "Anna A"
    assert lv.at["CSU", "anteil_spitze"] == pytest.approx(240 / 370 * 100, abs=0.01)


def test_import_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LABELS", tmp_path)
    cfg = config.ElectionConfig(id="x", name="x", kind="stadtratswahl")
    monkeypatch.setattr(config.ElectionConfig, "labels_path", property(lambda self: tmp_path / "x.json"))
    src = tmp_path / "k.csv"
    src.write_text("liste,platz,name,wahlvorschlag\n1,1,Anna A,CSU\n1,2,Bernd B,CSU\n", encoding="utf-8")
    assert config.import_candidates(cfg, src) == 2
    assert config.load_labels(cfg) == {"D1": "CSU", "D1_1": "Anna A", "D1_2": "Bernd B"}


def test_report_for_council_election(council, tmp_path):
    from ansbach_votes.report import write_report

    out = write_report(council, tmp_path, log=lambda *_: None)
    names = {p.name for p in out.iterdir()}
    assert {"kandidaten.csv", "sitzverteilung.csv", "kandidaten_hochburgen.csv", "bezirkssieger.csv",
            "listen.csv", "bezirke.csv", "karte_D.html"} <= names


def test_candidate_maps(council):
    import matplotlib

    matplotlib.use("Agg")
    from ansbach_votes import geo

    t = analysis.candidate_by_wahllokal(council, "Clara C")
    assert t.loc["Eyb", "stimmen"] == 60
    geo.plot_candidate(council, "Clara C")
    geo.plot_share(config.load("bundestagswahl_2025"), "CSU")
