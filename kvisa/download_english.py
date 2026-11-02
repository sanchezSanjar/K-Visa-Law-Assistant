"""Optional: download the English translations of the same laws for your own use.

The translations are made by the Korea Legislation Research Institute (KLRI) and are copyrighted:
personal, non-profit use is allowed, redistribution is not. They are saved to data/laws/en/, which
is git-ignored, and are never part of this repository. The Korean text is the official version;
a translation can be older than the Korean law in force.

    python -m kvisa.download_english
"""
import json
import re
import time
import urllib.parse

import requests

from kvisa.config import LAWS, LAWS_EN
from kvisa.download import BASE, HEADERS


def english_version(session: requests.Session, name_ko: str) -> str | None:
    page = session.get("https://www.law.go.kr/영문법령/" + urllib.parse.quote(name_ko), timeout=30).text
    match = re.search(r"lsInfoP\.do\?lsiSeq=(\d+)[^\"']*engLsInfoR", page)
    return match.group(1) if match else None


def download_english_pdf(session: requests.Session, lsi_seq: str) -> bytes | None:
    data = {
        "lsiSeq": lsi_seq, "chrClsCd": "010203", "outPutTitleYn": "N", "joAllCheck": "Y",
        "joEfOutPutYn": "on", "mokChaChk": "N", "bylChaChk": "N", "coverDpYn": "1",
        "lsNmFont": "goThic", "lsJoSize": "10", "lsJoFont": "smyoungjo", "spaceCls": "2",
        "fileType": "pdf", "docClsSelectBox": "pdf", "arSeqs": ",", "arIds": "",
    }
    response = session.post(BASE + "engLsPdfPrint.do?efGubun=", data=data, timeout=120)
    return response.content if response.content.startswith(b"%PDF") else None


def main() -> None:
    LAWS_EN.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    manifest = []
    for key, (name_ko, name_en) in LAWS.items():
        lsi_seq = english_version(session, name_ko)
        pdf = download_english_pdf(session, lsi_seq) if lsi_seq else None
        if not pdf:
            print(f"{name_en}: no English translation available")
            continue
        (LAWS_EN / f"{key}.pdf").write_bytes(pdf)
        manifest.append({"key": key, "name_en": name_en, "file": f"{key}.pdf", "lsiSeq": lsi_seq})
        print(f"{name_en}: {len(pdf) // 1024} KB")
        time.sleep(0.5)
    (LAWS_EN / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                           encoding="utf-8")


if __name__ == "__main__":
    main()
