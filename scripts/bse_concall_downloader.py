"""
BSE Concall Transcript Bulk Downloader
--------------------------------------
Downloads last-5-years quarterly earnings-call (concall) transcripts /
management commentary PDFs for a list of companies from BSE India, into
Downloads/ConcallTranscripts/<Company>/.

Data sources (all public BSE endpoints):
  1. PeerSmartSearch  -> resolve company name to BSE scrip code + NSE symbol + ISIN
  2. AnnSubCategoryGetData (paged, category="Company Update")
                        -> corporate announcements
  3. AttachHis/<file>  -> the actual PDF attachment

Robust against the intermittent DNS ("No such host is known") seen in this
environment via a retry wrapper. Writes a manifest.csv summarising everything.
"""
from __future__ import annotations

import csv
import re
import sys
import time
import html
import datetime as dt
from pathlib import Path

import httpx

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
DOWNLOAD_ROOT = Path.home() / "Downloads" / "ConcallTranscripts"
YEARS_BACK = 5
TODAY = dt.date(2026, 7, 11)          # env "today"
FROM_DATE = TODAY.replace(year=TODAY.year - YEARS_BACK)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/json, text/plain, */*",
}

API = "https://api.bseindia.com/BseIndiaAPI/api"
SUGGEST = f"{API}/PeerSmartSearch/w"
ANN = f"{API}/AnnSubCategoryGetData/w"
ATTACH = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{name}"

# Keywords that identify a concall transcript / management commentary document.
KEEP_RE = re.compile(
    r"transcript|con(?:\.|\s)?call|conference\s*call|earnings\s*(?:call|conference)"
    r"|management\s*commentary|analyst.*meet|institutional\s*investor"
    r"|investor\s*(?:meet|call|conference)|q&a",
    re.IGNORECASE,
)
# Documents we explicitly do NOT want (audio, intimations of the call, presentations only)
DROP_RE = re.compile(
    r"audio\s*recording|audio\s*link|intimation|schedul|newspaper|prior\s*intimation",
    re.IGNORECASE,
)

# 28 companies from the user's screenshots.
COMPANIES = [
    "HBL Engineering",
    "Sterlite Technologies",
    "TD Power Systems",
    "INOX India",
    "HLE Glascoat",
    "Centum Electronics",
    "Syrma SGS Technology",
    "Avalon Technologies",
    "Sansera Engineering",
    "Astra Microwave Products",
    "ideaForge Technology",
    "Aarti Pharmalabs",
    "Acutaas Chemicals",
    "Sai Life Sciences",
    "Neogen Chemicals",
    "Rain Industries",
    "Privi Speciality Chemicals",
    "Shivalik Bimetal Controls",
    "SJS Enterprises",
    "HFCL",
    "KRN Heat Exchanger",
    "Sambhv Steel Tubes",
    "E2E Networks",
    "Quality Power Electrical Equipments",
    "Timex Group India",
    "Shadowfax Technologies",
    "Gokaldas Exports",
]

# --------------------------------------------------------------------------- #
# HTTP helpers with retry (handles intermittent DNS + 5xx)
# --------------------------------------------------------------------------- #
def get(client: httpx.Client, url: str, *, tries: int = 6, timeout: int = 40) -> httpx.Response:
    last = None
    for i in range(1, tries + 1):
        try:
            r = client.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = str(e).split("\n")[0]
        time.sleep(2 * i)
    raise RuntimeError(f"GET failed after {tries} tries ({last}): {url}")


def resolve_scrip(client: httpx.Client, name: str):
    """Return (scrip_code, nse_symbol, isin, bse_name) or None."""
    params = httpx.QueryParams({"Type": "SS", "text": name})
    url = f"{SUGGEST}?{params}"
    try:
        r = get(client, url, tries=5)
    except RuntimeError:
        return None
    txt = html.unescape(r.text)
    m = re.search(r"liclick\('(\d+)','([^']+)'\)", txt)
    if not m:
        return None
    scrip, bse_name = m.group(1), m.group(2)
    sym = re.search(r"<span>([^&<]+?)&nbsp;", r.text)
    isin = re.search(r"(INE[0-9A-Z]{9})", txt)
    return scrip, (sym.group(1).strip() if sym else ""), (isin.group(1) if isin else ""), bse_name


def fetch_announcements(client: httpx.Client, scrip: str):
    """Page through all 'Company Update' announcements in the 5y window."""
    rows = []
    pageno = 1
    while True:
        url = (
            f"{ANN}?pageno={pageno}&strCat=Company Update"
            f"&strPrevDate={FROM_DATE:%Y%m%d}&strScrip={scrip}"
            f"&strSearch=P&strToDate={TODAY:%Y%m%d}&strType=C&subcategory=-1"
        )
        r = get(client, url)
        data = r.json()
        table = data.get("Table") or []
        rows.extend(table)
        if len(table) < 50:
            break
        pageno += 1
        if pageno > 60:  # safety
            break
        time.sleep(0.4)
    return rows


def safe(s: str, maxlen: int = 80) -> str:
    s = re.sub(r"[^\w\- ]+", "", s).strip()
    s = re.sub(r"\s+", "_", s)
    return s[:maxlen]


def parse_dt(row) -> str:
    raw = row.get("NEWS_DT") or row.get("News_submission_dt") or ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw) or re.search(r"(\d{2})-(\d{2})-(\d{4})", raw)
    if not m:
        return "0000-00-00"
    g = m.groups()
    return f"{g[0]}-{g[1]}-{g[2]}" if len(g[0]) == 4 else f"{g[2]}-{g[1]}-{g[0]}"


def download_pdf(client: httpx.Client, attach: str, dest: Path) -> tuple[bool, str]:
    url = ATTACH.format(name=attach)
    try:
        r = get(client, url, tries=5, timeout=90)
    except RuntimeError as e:
        return False, str(e)
    ctype = r.headers.get("Content-Type", "")
    if "pdf" not in ctype.lower() and r.content[:4] != b"%PDF":
        return False, f"not-pdf ({ctype})"
    dest.write_bytes(r.content)
    return True, f"{len(r.content)} bytes"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    only = sys.argv[1:] or None  # optional: restrict to given company substrings
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = DOWNLOAD_ROOT / "manifest.csv"
    new_file = not manifest.exists()
    mf = manifest.open("a", newline="", encoding="utf-8")
    writer = csv.writer(mf)
    if new_file:
        writer.writerow(["company", "scrip", "nse", "isin", "date", "subject", "attachment", "saved_as", "status"])

    with httpx.Client() as client:
        for name in COMPANIES:
            if only and not any(o.lower() in name.lower() for o in only):
                continue
            print(f"\n=== {name} ===", flush=True)
            info = resolve_scrip(client, name)
            if not info:
                print("  ! could not resolve scrip code", flush=True)
                writer.writerow([name, "", "", "", "", "", "", "", "SCRIP_NOT_FOUND"])
                mf.flush()
                continue
            scrip, nse, isin, bse_name = info
            print(f"  scrip={scrip} nse={nse} isin={isin} ({bse_name})", flush=True)

            cdir = DOWNLOAD_ROOT / safe(name)
            cdir.mkdir(parents=True, exist_ok=True)

            try:
                anns = fetch_announcements(client, scrip)
            except RuntimeError as e:
                print(f"  ! announcements failed: {e}", flush=True)
                writer.writerow([name, scrip, nse, isin, "", "", "", "", "ANN_FAILED"])
                mf.flush()
                continue

            hits = [
                a for a in anns
                if KEEP_RE.search(a.get("NEWSSUB", "") or "")
                and not DROP_RE.search(a.get("NEWSSUB", "") or "")
                and (a.get("ATTACHMENTNAME") or "").lower().endswith(".pdf")
            ]
            print(f"  {len(anns)} announcements -> {len(hits)} transcript-like PDFs", flush=True)

            seen = set()
            got = 0
            for a in hits:
                attach = a["ATTACHMENTNAME"]
                if attach in seen:
                    continue
                seen.add(attach)
                d = parse_dt(a)
                subj = a.get("NEWSSUB", "")
                fname = f"{d}_{safe(subj, 90)}.pdf"
                dest = cdir / fname
                if dest.exists() and dest.stat().st_size > 1000:
                    writer.writerow([name, scrip, nse, isin, d, subj, attach, fname, "ALREADY"])
                    got += 1
                    continue
                ok, msg = download_pdf(client, attach, dest)
                status = "OK" if ok else f"FAIL:{msg}"
                if ok:
                    got += 1
                print(f"    [{status}] {d}  {subj[:60]}", flush=True)
                writer.writerow([name, scrip, nse, isin, d, subj, attach, fname if ok else "", status])
                mf.flush()
                time.sleep(0.5)

            print(f"  downloaded {got}/{len(hits)}", flush=True)
    mf.close()
    print("\nDONE. Manifest:", manifest, flush=True)


if __name__ == "__main__":
    main()
