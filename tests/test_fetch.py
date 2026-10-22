from ansbach_votes import config, fetch, okvote

from .conftest import council_csv


class FakeResponse:
    def __init__(self, body: str, ctype: str, status: int = 200):
        self.text = body
        self.content = body.encode("utf-8")
        self.status_code = status
        self.headers = {"content-type": ctype}
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(self.status_code)


BASE = "https://wahlen.example.org/kommunal/"
SITE = {
    BASE: ("<a href='opendata.html'>Open Data</a> <a href='ergebnisse_listen.html'>Listen</a>"
           "<a href='ergebnisse_stimmbezirk_095610000001.html'>Bezirk 1</a>", "text/html"),
    BASE + "opendata.html": ("<a href='Open-Data-Stadtratswahl.csv?ts=1'>CSV</a>", "text/html"),
    BASE + "ergebnisse_listen.html": (
        "<table><tr><th>Wahlvorschlag</th><th>Stimmen</th></tr>"
        "<tr><td>1 CSU</td><td>370</td><td>56,1 %</td></tr>"
        "<tr><td>2 SPD</td><td>230</td></tr><tr><td>3 GRÜNE</td><td>60</td></tr></table>"
        "<table><tr><td>101</td><td>A, Anna</td><td>240</td></tr>"
        "<tr><td>102</td><td>B, Bernd</td><td>60</td></tr>"  # 60 collides with GRÜNE -> ambiguous
        "<tr><td>103</td><td>C, Clara</td><td>70</td></tr></table>", "text/html"),
    BASE + "Open-Data-Stadtratswahl.csv?ts=1": (council_csv(), "text/csv"),
}


class FakeSession:
    def __init__(self):
        self.requested = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        body, ctype = SITE.get(url, ("not found", "text/html"))
        return FakeResponse(body, ctype, 200 if url in SITE else 404)


def test_crawl_finds_csv_and_skips_district_pages():
    s = FakeSession()
    result = fetch.crawl(BASE, s)
    assert result.csv_urls == [BASE + "Open-Data-Stadtratswahl.csv?ts=1"]
    assert not any("stimmbezirk" in u for u in s.requested)


def test_fetch_downloads_and_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW", tmp_path / "raw")
    monkeypatch.setattr(config, "LABELS", tmp_path / "labels")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    cfg = config.ElectionConfig(id="srw", name="Stadtratswahl", kind="stadtratswahl", seats=4, source_url=BASE)
    monkeypatch.setattr(config, "registry", lambda path=None: {"srw": cfg})
    monkeypatch.setattr(config.ElectionConfig, "raw_dir", property(lambda self: tmp_path / "raw" / self.id))
    monkeypatch.setattr(config.ElectionConfig, "labels_path", property(lambda self: tmp_path / "labels" / f"{self.id}.json"))

    logs = []
    files = fetch.fetch("srw", session=FakeSession(), log=logs.append)
    assert [f.name for f in files] == ["Open-Data-Stadtratswahl.csv"]
    labels = config.load_labels(cfg)
    assert labels["D1"] == "CSU" and labels["D2"] == "SPD"
    assert labels["D1_1"] == "A, Anna" and labels["D1_3"] == "C, Clara"
    assert "D1_2" not in labels and "D3" not in labels  # ambiguous totals stay unnamed

    # second run: nothing changed
    fetch.fetch("srw", session=FakeSession(), log=logs.append)
    assert any("unchanged" in line for line in logs)
    assert isinstance(config.load("srw"), okvote.Election)


def test_table_numbers_handles_thousands_separator():
    page = fetch.parse_page("<table><tr><td>Deffner, Thomas</td><td>11.613</td><td>3,1 %</td></tr></table>")
    assert fetch.table_numbers([page]) == {11613: {"Deffner, Thomas"}}
