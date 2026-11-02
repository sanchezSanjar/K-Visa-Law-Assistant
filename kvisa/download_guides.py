"""Download the Ministry of Justice guidebook(s) to this PC (practical rules the laws do not contain).

The guides are under KOGL Type 4 (attribution, non-commercial, no changes): they may be used here
but are not redistributed, so data/guides/ is git-ignored and the repository holds only this script.

You can also put other guide PDFs into data/guides/ yourself, for example the HiKorea manuals
(사증민원/체류민원 자격별 안내 매뉴얼) saved as PDF from the Hancom viewer; they are picked up by
python -m kvisa.parse.

    python -m kvisa.download_guides
"""
import json

import requests

from kvisa.config import GUIDES
from kvisa.download import HEADERS

VISA_NAVIGATOR = {
    "key": "visa_navigator",
    "file": "visa_navigator_2022.pdf",
    "title_ko": "비자 내비게이터 (법무부 안내서, 2022.12)",
    "title_en": "Visa Navigator (Ministry of Justice guide, Dec 2022)",
    "version": "20221216",
    "page_url": "https://immigration.go.kr/bbs/immigration/47/566047/artclView.do",
    "download_url": "https://immigration.go.kr/bbs/immigration/47/448373/download.do",
    "license": "KOGL Type 4 (attribution, non-commercial, no changes)",
    # (first page, section) from the table of contents
    "sections": [
        [4, "비자의 개요"], [9, "유학, 연수 (D-2, D-4)"], [14, "주재, 투자, 경영 (D-7, D-8, D-9)"],
        [18, "구직 (D-10)"], [23, "취업(전문인력) (C-4, E-1~E-7)"], [26, "취업(비전문인력) (E-8~E-10)"],
        [28, "기타 (D-1, D-5, D-6)"], [31, "방문동거, 동반 (F-1, F-3)"], [32, "거주 (F-2)"],
        [38, "결혼이민 (F-6)"], [40, "영주 (F-5)"], [42, "출입국 민원 신청 방법"], [47, "자주 묻는 질문"],
        [51, "주요 상담 사례 (외국인종합안내센터)"], [55, "신고 의무사항 및 주요 법 위반 사례"],
    ],
}


def main() -> None:
    GUIDES.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    guide = VISA_NAVIGATOR
    session.get(guide["page_url"], timeout=30)
    response = session.get(guide["download_url"], headers={"Referer": guide["page_url"]}, timeout=300)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise RuntimeError("The guide download did not return a PDF")
    (GUIDES / guide["file"]).write_bytes(response.content)
    (GUIDES / "manifest.json").write_text(json.dumps([guide], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{guide['title_ko']}: {len(response.content) // 1024} KB")


if __name__ == "__main__":
    main()
