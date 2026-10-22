"""Pull the latest results from the city's election portal.

The portal (OK.VOTE presentation, e.g. https://wahlen2026.ansbach.de/kommunal/)
offers the results as "Open Data" CSV files and shows party and candidate
names on its HTML pages. :func:`fetch` crawls the portal, downloads every CSV
it can find to ``data/raw/<election>/`` and then names the CSV columns by
matching the city-wide vote counts in the CSV against the numbers printed on
the HTML pages.

Re-running it is cheap: unchanged files are left alone, so it can be used on
election night to pick up new Schnellmeldungen.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from . import config, okvote

# Pages that typically hold the open data download links
GUESSES = ("opendata.html", "open_data.html", "downloads.html", "download.html", "open_data.json",
           "daten/opendata/open_data.json")
NAV_HINT = re.compile(r"open.?data|download|export|daten|csv", re.IGNORECASE)
RESULT_PAGE = re.compile(r"ergebnis|gewaehlt|gewählt|bewerber|kandidat|liste|index", re.IGNORECASE)
DISTRICT_PAGE = re.compile(r"stimmbezirk|briefwahlbezirk|wahlbezirk_|_bezirk", re.IGNORECASE)
USER_AGENT = "ansbach-votes (+https://github.com/bastian-seifert/ansbach-votes)"


class _Page(HTMLParser):
    """Collects links and table rows (as lists of cell texts)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.rows: list[list[str]] = []
        self._href: str | None = None
        self._link_text: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._href, self._link_text = attrs["href"], []
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._link_text).split())))
            self._href = None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._href is not None:
            self._link_text.append(data)
        if self._cell is not None:
            self._cell.append(data)


def parse_page(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    return page


@dataclass
class CrawlResult:
    csv_urls: list[str] = field(default_factory=list)
    pages: dict[str, _Page] = field(default_factory=dict)
    start_error: str | None = None


def _session():
    import requests

    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def crawl(start_url: str, session=None, *, max_pages: int = 60) -> CrawlResult:
    """Breadth-first crawl below ``start_url`` collecting CSV links and city-level result pages."""
    session = session or _session()
    base = start_url if start_url.endswith("/") or start_url.endswith(".html") else start_url + "/"
    base_dir = base.rsplit("/", 1)[0] + "/"
    host = urlparse(base).netloc
    queue = [base] + [urljoin(base_dir, g) for g in GUESSES]
    seen: set[str] = set()
    result = CrawlResult()
    csvs: dict[str, None] = {}
    while queue and len(seen) < max_pages:
        url = queue.pop(0).split("#")[0]
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = session.get(url, timeout=30)
        except Exception as exc:  # network errors on guessed URLs are expected
            if url == base:
                result.start_error = f"{type(exc).__name__}: {exc}"
            continue
        if resp.status_code != 200:
            if url == base:
                result.start_error = f"HTTP {resp.status_code}"
            continue
        ctype = resp.headers.get("content-type", "")
        if url.endswith(".json") or "json" in ctype:
            for link in _json_links(resp.text):
                full = urljoin(url, link)
                if _is_csv(full):
                    csvs[full] = None
            continue
        if "html" not in ctype and not url.endswith((".html", "/")):
            continue
        resp.encoding = resp.encoding or resp.apparent_encoding
        page = parse_page(resp.text)
        result.pages[url] = page
        for href, text in page.links:
            full = urljoin(url, href).split("#")[0]
            if _is_csv(full):
                csvs[full] = None
                continue
            if urlparse(full).netloc != host or not full.startswith(base_dir) or full in seen:
                continue
            if DISTRICT_PAGE.search(full):
                continue  # district pages hold district numbers, not city totals
            if NAV_HINT.search(full) or NAV_HINT.search(text):
                queue.insert(0, full)  # download pages first
            elif RESULT_PAGE.search(full) or full.endswith("/"):
                queue.append(full)
    result.csv_urls = list(csvs)
    return result


def _is_csv(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".csv")


def _json_links(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    links: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and ".csv" in o.lower():
            links.append(o)

    walk(data)
    return links


def download(urls: list[str], target: Path, session=None) -> list[tuple[Path, str]]:
    """Download ``urls`` into ``target``; returns ``(path, status)`` with status new/updated/unchanged."""
    session = session or _session()
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    out = []
    for url in urls:
        resp = session.get(url, timeout=60)
        resp.raise_for_status()
        name = Path(urlparse(url).path).name
        path = target / name
        digest = hashlib.sha256(resp.content).hexdigest()
        old = manifest.get(name, {}).get("sha256")
        status = "unchanged" if old == digest and path.exists() else ("updated" if path.exists() else "new")
        if status != "unchanged":
            path.write_bytes(resp.content)
        manifest[name] = {"url": url, "sha256": digest,
                          "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        out.append((path, status))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return out


# --------------------------------------------------------------------------
# Naming the columns


NUMBER = re.compile(r"^\d{1,3}(?:\.\d{3})+$|^\d+$")
LEADING_NO = re.compile(r"^\(?\d{1,4}[).:]?\s+")


def table_numbers(pages: list[_Page]) -> dict[int, set[str]]:
    """Map every integer printed in a table row to the row's label(s)."""
    found: dict[int, set[str]] = defaultdict(set)
    for page in pages:
        for row in page.rows:
            label = next((c for c in row if re.search(r"[A-Za-zÄÖÜäöüß]{2,}", c)), None)
            if not label:
                continue
            label = LEADING_NO.sub("", label).strip()
            for cell in row:
                if NUMBER.match(cell):
                    found[int(cell.replace(".", ""))].add(label)
    return found


def match_labels(election: okvote.Election, numbers: dict[int, set[str]]) -> dict[str, str]:
    """Assign a name to every column whose city-wide total appears with exactly one label."""
    total = election.total_id
    labels: dict[str, str] = {}
    for ballot in election.ballots.values():
        for frame in (ballot.lists, ballot.candidates):
            for col in frame.columns:
                value = int(frame.at[total, col])
                names = numbers.get(value, set())
                if value > 0 and len(names) == 1:
                    labels[col] = next(iter(names))
    return labels


def fetch(election_id: str, url: str | None = None, *, session=None, label: bool = True,
          log=print) -> list[Path]:
    cfg = config.get(election_id)
    url = url or cfg.source_url
    if not url:
        raise ValueError(f"{election_id}: no source_url in {config.REGISTRY.name} – pass --url")
    session = session or _session()
    log(f"crawling {url} …")
    crawled = crawl(url, session)
    log(f"  {len(crawled.pages)} pages, {len(crawled.csv_urls)} CSV files")
    if not crawled.csv_urls and crawled.start_error and not crawled.pages:
        raise RuntimeError(f"could not reach {url}: {crawled.start_error}")
    if not crawled.csv_urls:
        raise RuntimeError("no CSV downloads found – look for an 'Open Data' link on the portal and pass it via --url")
    files = download(crawled.csv_urls, cfg.raw_dir, session)
    for path, status in files:
        log(f"  {status:9} {path.relative_to(config.ROOT)}")
    if label:
        try:
            election = config.load(election_id)
        except (FileNotFoundError, ValueError) as exc:
            log(f"  not labelling: {exc}")
        else:
            labels = match_labels(election, table_numbers(list(crawled.pages.values())))
            if labels:
                path = config.save_auto_labels(cfg, labels, url)
                n_cols = sum(b.lists.shape[1] + b.candidates.shape[1] for b in election.ballots.values())
                log(f"  named {len(labels)}/{n_cols} columns -> {path.relative_to(config.ROOT)}")
            else:
                log("  could not name any columns automatically – edit data/labels/ by hand")
    return [p for p, _ in files]
