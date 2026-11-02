"""Download the current official Korean law PDFs from the National Law Information Center (law.go.kr).

Each law is saved as one PDF with all its articles, plus its attached tables (별표) as separate
PDFs, e.g. the visa (status of stay) tables of the Enforcement Decree.

    python -m kvisa.download
"""
import html
import json
import re
import time
import urllib.parse

import requests

from kvisa.config import LAWS, LAWS_KO

BASE = "https://www.law.go.kr/LSW/"
HEADERS = {"User-Agent": "Mozilla/5.0 (K-Visa-Law-Assistant; educational project)"}


def current_version(session: requests.Session, name: str) -> dict:
    """The law page redirects to the version in force today; read its ids from the frame URL."""
    page = session.get("https://www.law.go.kr/법령/" + urllib.parse.quote(name), timeout=30).text
    match = re.search(r"lsInfoP\.do\?lsiSeq=(\d+)&(?:amp;)?chrClsCd=(\d+).*?efYd=(\d+)", page)
    if not match:
        raise RuntimeError(f"Could not find the current version of {name}")
    return {"lsiSeq": match.group(1), "chrClsCd": match.group(2), "efYd": match.group(3)}


def download_law_pdf(session: requests.Session, version: dict) -> tuple[bytes, str]:
    data = {
        "lsiSeq": version["lsiSeq"], "chrClsCd": version["chrClsCd"], "efYd": version["efYd"],
        "outPutTitleYn": "N", "joAllCheck": "Y", "joEfOutPutYn": "on", "mokChaChk": "N",
        "bylChaChk": "N", "coverDpYn": "1", "lsNmFont": "goThic", "lsJoSize": "10",
        "lsJoFont": "smyoungjo", "spaceCls": "2", "fileType": "pdf", "docClsSelectBox": "pdf",
        "arSeqs": ",", "arIds": "",
    }
    response = session.post(BASE + "lsPdfPrint.do?efGubun=", data=data, timeout=120)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise RuntimeError("law.go.kr did not return a PDF")
    disposition = response.headers.get("Content-Disposition", "")
    filename = urllib.parse.unquote(re.search(r'filename="([^"]+)"', disposition).group(1))
    return response.content, filename


def attached_tables(session: requests.Session, version: dict) -> list[dict]:
    """Attached tables (별표) with their PDF file ids, in document order."""
    body = session.get(
        BASE + "lsInfoR.do",
        params={"lsiSeq": version["lsiSeq"], "efYd": version["efYd"], "efYn": "Y",
                "chrClsCd": version["chrClsCd"], "nwJoYnInfo": "Y", "ancYnChk": "0",
                "netPrivateYn": "N"},
        timeout=60,
    ).text
    titles = [(m.start(), re.sub(r"\s+", " ", html.unescape(m.group(1))).strip())
              for m in re.finditer(r">\s*(\[별표\s*[\d의 ]+\][^<\"]{1,120})", body)]
    tables, seen = [], set()
    for link in re.finditer(r'flDownload\.do\?gubun=&(?:amp;)?flSeq=(\d+)[^"]*"[^>]*>\s*<img[^>]*alt="PDF', body):
        before = [title for pos, title in titles if pos < link.start()]
        if not before or link.group(1) in seen:
            continue
        seen.add(link.group(1))
        tables.append({"title": before[-1], "flSeq": link.group(1)})
    # The same table can appear twice (body and list); keep the first PDF per title.
    unique, titles_seen = [], set()
    for table in tables:
        if table["title"] not in titles_seen:
            titles_seen.add(table["title"])
            unique.append(table)
    return unique


def safe_name(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", text).strip("_")


def main() -> None:
    LAWS_KO.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    manifest = []
    for key, (name_ko, name_en) in LAWS.items():
        version = current_version(session, name_ko)
        pdf, filename = download_law_pdf(session, version)
        (LAWS_KO / f"{key}.pdf").write_bytes(pdf)
        entry = {"key": key, "name_ko": name_ko, "name_en": name_en, "file": f"{key}.pdf",
                 "source_file": filename, "effective": version["efYd"], "lsiSeq": version["lsiSeq"],
                 "url": f"https://www.law.go.kr/법령/{name_ko}", "tables": []}
        for number, table in enumerate(attached_tables(session, version), start=1):
            response = session.get(BASE + "flDownload.do",
                                   params={"gubun": "", "flSeq": table["flSeq"], "bylClsCd": "110201"},
                                   timeout=120)
            if not response.content.startswith(b"%PDF"):
                print(f"  skipped {table['title']} (not a PDF)")
                continue
            table_file = f"{key}__table{number:02d}.pdf"
            (LAWS_KO / table_file).write_bytes(response.content)
            entry["tables"].append({"title": table["title"], "file": table_file})
            time.sleep(0.3)
        manifest.append(entry)
        print(f"{name_ko}: effective {version['efYd']}, {len(pdf) // 1024} KB, "
              f"{len(entry['tables'])} attached tables")
        time.sleep(0.5)
    (LAWS_KO / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                           encoding="utf-8")


if __name__ == "__main__":
    main()
