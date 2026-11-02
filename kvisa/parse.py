"""Turn the law PDFs into searchable pieces: one per article, and row groups for attached tables.

    python -m kvisa.parse

Writes data/articles.jsonl (Korean, committed) and, when they were downloaded,
data/laws/en/articles_en.jsonl (English article text) and data/guides/guides.jsonl (pieces of the
Ministry of Justice guides); both are git-ignored.
"""
import json
import re
from pathlib import Path

import pymupdf

from kvisa.config import ARTICLES, GUIDES, LAWS_EN, LAWS_KO

MAX_CHARS = 1800          # longer articles are split at paragraph marks (①, ②, ...)
TABLE_CHUNK_CHARS = 1000  # longer table rows are split by line at about this size
TABLE_MIN_CHARS = 200     # shorter table rows are merged with the next row

KO_ARTICLE = re.compile(r"^제(\d+)조(?:의(\d+))?\s*\(([^)]*)\)\s*(.*)$")
KO_DELETED = re.compile(r"^제\d+조(?:의\d+)?\s*삭제")
KO_CHAPTER = re.compile(r"^제\d+(?:장|절|관)(?:의\d+)?\s+\S")
KO_ADDENDA = re.compile(r"^부\s*칙\s*(<|$)")
EN_ARTICLE = re.compile(r"^Article\s+(\d+)(?:-(\d+))?\s*\(([^)]*)\)\s*(.*)$")
EN_DELETED = re.compile(r"^Article\s+\d+(?:-\d+)?\s+Deleted")
EN_CHAPTER = re.compile(r"^(?:CHAPTER\s+[IVXLC]+|SECTION\s+\d+)(?:-\d+)?\b")
EN_ADDENDA = re.compile(r"^ADDENDA\b")
AMENDMENT_NOTES = re.compile(r"<(?:개정|신설|Amended|Added|Newly inserted)[^>]*>|\[(?:전문개정|본조신설|제목개정|"
                             r"종전|This Article|Moved from|Previous)[^\]]*\]")
# Running header and footer of law.go.kr PDFs: "법제처 12 국가법령정보센터" and the law name.
PAGE_FURNITURE = re.compile(r"^(?:법제처\s+\d+(?:\s+국가법령정보센터)?|국가법령정보센터|「[^」]+」)$")
VISA_CODE = re.compile(r"\b([A-H]-\d{1,2}(?:-\d{1,2})?)\b")
VISA_ROW = re.compile(r"(?:^|\n)\d+(?:의\d+)?\.\s*[^\n(]{1,20}\(([A-H]-\d{1,2}(?:-\d{1,2})?)\)")  # row that defines a visa
PARAGRAPH = re.compile(r"(?=[①-⑳])")


def pdf_lines(path: Path, skip_margins: bool) -> list[tuple[int, str]]:
    """(page number, line text) in reading order.

    Spaces are rebuilt from character positions: the attached-table PDFs place every character
    separately and contain no space characters, only gaps.
    """
    lines = []
    with pymupdf.open(path) as doc:
        for page_no, page in enumerate(doc, start=1):
            height = page.rect.height
            for block in page.get_text("rawdict")["blocks"]:
                for line in block.get("lines", []):
                    if skip_margins and not 45 < line["bbox"][1] < height - 45:
                        continue  # running header (law name) and footer (page number)
                    text, previous = "", None
                    for span in line["spans"]:
                        for char in span["chars"]:
                            if previous is not None and char["bbox"][0] - previous["bbox"][2] > span["size"] * 0.25:
                                text += " "
                            text += char["c"]
                            previous = char
                    text = re.sub(r"\s+", " ", text).rstrip()
                    if skip_margins and PAGE_FURNITURE.match(text.strip()):
                        continue
                    if text.strip():
                        lines.append((page_no, text))
    return lines


def join_lines(lines: list[str]) -> str:
    """Join wrapped lines: Korean lines break mid-word, so no space is added between two letters."""
    out = ""
    for line in lines:
        line = line.strip()
        if not out:
            out = line
        elif re.match(r"^([①-⑳]|\d+(?:의\d+)?\.\s|[가-하]\.\s|\(\d+\)|\[)", line):
            out += "\n" + line   # a new paragraph, item or note starts on its own line
        elif (out[-1].isascii() and line[0].isascii()) or out[-1] in ")]」":
            out += " " + line
        else:
            out += line
    return out


def clean(text: str) -> str:
    text = AMENDMENT_NOTES.sub("", text)
    text = re.sub(r"\s*법제처\s+\d+\s+국가법령정보센터\s*(?:「[^」]+」)?\s*", " ", text)  # footer merged into a line
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def split_long(text: str, header: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    parts, current = [], ""
    for piece in PARAGRAPH.split(text):
        if current and len(current) + len(piece) > MAX_CHARS:
            parts.append(current)
            current = header + " " + piece.strip()
        else:
            current += piece
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def parse_articles(path: Path, lang: str) -> list[dict]:
    article_re, deleted_re, chapter_re, addenda_re = (
        (KO_ARTICLE, KO_DELETED, KO_CHAPTER, KO_ADDENDA) if lang == "ko"
        else (EN_ARTICLE, EN_DELETED, EN_CHAPTER, EN_ADDENDA))
    articles, current, chapter = [], None, ""
    for page, line in pdf_lines(path, skip_margins=True):
        stripped = line.strip()
        if addenda_re.match(stripped):
            break
        if chapter_re.match(stripped):
            chapter = AMENDMENT_NOTES.sub("", stripped).strip()
            current = None
            continue
        if deleted_re.match(stripped):
            current = None
            continue
        match = article_re.match(stripped)
        if match:
            number, sub, title, _ = match.groups()
            current = {"number": int(number), "sub": int(sub) if sub else 0, "title": title.strip(),
                       "page": page, "chapter": chapter, "lines": [stripped]}
            articles.append(current)
        elif current is not None:
            current["lines"].append(line)
    return articles


def table_pieces(path: Path, title: str) -> list[dict]:
    """Split a table into rows (lines that start a numbered item)."""
    rows, current = [], []
    for page, line in pdf_lines(path, skip_margins=False):
        if re.match(r"^\d+(?:의\d+)?\.\s", line.strip()) and current:
            rows.append(current)
            current = []
        current.append((page, line))
    if current:
        rows.append(current)
    # Some tables (required documents, fines) have few numbered rows; break very long rows by line.
    split_rows = []
    for row in rows:
        chunk = []
        for item in row:
            if chunk and sum(len(text) for _, text in chunk) + len(item[1]) > TABLE_CHUNK_CHARS:
                split_rows.append(chunk)
                chunk = []
            chunk.append(item)
        split_rows.append(chunk)
    rows = split_rows
    # One piece per row (e.g. one visa type), so a question about one visa finds that row;
    # short rows are merged with the next one.
    pieces, piece = [], []
    for row in rows:
        piece.extend(row)
        if sum(len(text) for _, text in piece) >= TABLE_MIN_CHARS:
            pieces.append(piece)
            piece = []
    if piece:
        pieces.append(piece)
    return [{"page": lines[0][0], "text": clean(join_lines([text for _, text in lines]))} for lines in pieces]


def article_label(number: int, sub: int, lang: str) -> str:
    if lang == "ko":
        return f"제{number}조" + (f"의{sub}" if sub else "")
    return f"Article {number}" + (f"-{sub}" if sub else "")


def build_korean() -> list[dict]:
    manifest = json.loads((LAWS_KO / "manifest.json").read_text(encoding="utf-8"))
    records = []
    for law in manifest:
        common = {"law": law["key"], "law_ko": law["name_ko"], "law_en": law["name_en"],
                  "effective": law["effective"], "url": law["url"]}
        for article in parse_articles(LAWS_KO / law["file"], "ko"):
            label = article_label(article["number"], article["sub"], "ko")
            header = f"{label}({article['title']})"
            text = clean(join_lines(article["lines"]))
            parts = split_long(text, header)
            for index, part in enumerate(parts, start=1):
                suffix = f"#{index}" if len(parts) > 1 else ""
                records.append({
                    "id": f"{law['key']}:{article['number']}" + (f"-{article['sub']}" if article["sub"] else "") + suffix,
                    "kind": "article", **common, "label": label, "title": article["title"],
                    "chapter": article["chapter"], "file": law["file"], "page": article["page"], "text": part,
                })
        for table_no, table in enumerate(law["tables"], start=1):
            label = re.match(r"\[(별표[^\]]*)\]", table["title"]).group(1)
            table_title = table["title"].split("]", 1)[1].strip()
            pieces = table_pieces(LAWS_KO / table["file"], table["title"])
            for index, piece in enumerate(pieces, start=1):
                records.append({
                    "id": f"{law['key']}:table{table_no:02d}#{index}", "kind": "table", **common,
                    "label": label, "title": table_title, "chapter": "", "file": table["file"],
                    "page": piece["page"], "codes": sorted(set(VISA_CODE.findall(piece["text"]))),
                    "defines": sorted(set(VISA_ROW.findall(piece["text"]))),
                    "text": f"[{label}] {table_title}\n{piece['text']}",
                })
    return records


def build_english() -> list[dict]:
    manifest_path = LAWS_EN / "manifest.json"
    if not manifest_path.exists():
        return []
    records = []
    for law in json.loads(manifest_path.read_text(encoding="utf-8")):
        for article in parse_articles(LAWS_EN / law["file"], "en"):
            records.append({
                "id": f"{law['key']}:{article['number']}" + (f"-{article['sub']}" if article["sub"] else ""),
                "label": article_label(article["number"], article["sub"], "en"), "title": article["title"],
                "text": clean(join_lines(article["lines"])),
            })
    return records


GUIDE_CHUNK_CHARS = 900
GUIDE_NOISE = re.compile(r"^(?:\d{1,3}|PART|PART\s*\d+.*|\d{2}|비자\s*내비게이터.*|Visa|Navigator)$")
GUIDE_ITEM = re.compile(r"^(?:[●▪❶❷❸❹❺❻❼❽❾❿※*-]|\d+\.\s|Q\d*[.)]?\s)")


def guide_page_text(page) -> str:
    """Join the lines of a guide page; a line ending in a space wrapped at a word boundary."""
    out, wrapped_at_space = "", False
    for raw in page.get_text().split("\n"):
        line = raw.replace("‌", "").replace("\t", " ")
        stripped = line.strip()
        if not stripped or GUIDE_NOISE.match(stripped):
            continue
        if not out:
            out = stripped
        elif GUIDE_ITEM.match(stripped):
            out += "\n" + stripped
        else:
            out += (" " if wrapped_at_space else "") + stripped
        wrapped_at_space = line.endswith(" ")
    out = re.sub(r"^\d{1,3}\s*비자\s*내비게이터\s*", "", out)  # running header: page number + guide name
    return re.sub(r" {2,}", " ", out).strip()


def guide_pieces(path: Path, sections: list) -> list[dict]:
    pieces = []
    with pymupdf.open(path) as doc:
        for page_no, page in enumerate(doc, start=1):
            text = guide_page_text(page)
            if len(text) < 80:      # cover, divider and empty pages
                continue
            section = ""
            for start, title in sections:
                if page_no >= start:
                    section = title
            # split long pages at items (●, ❶, ...) into pieces of about GUIDE_CHUNK_CHARS
            chunk = ""
            for item in re.split(r"\n(?=[●❶❷❸❹❺❻❼❽❾❿])", text):
                if chunk and len(chunk) + len(item) > GUIDE_CHUNK_CHARS:
                    pieces.append({"page": page_no, "section": section, "text": chunk.strip()})
                    chunk = ""
                chunk += ("\n" if chunk else "") + item
            if chunk.strip():
                pieces.append({"page": page_no, "section": section, "text": chunk.strip()})
    return pieces


def build_guides() -> list[dict]:
    """Pieces of the guides in data/guides/: the downloaded ones (manifest) and any PDF added by hand."""
    if not GUIDES.exists():
        return []
    manifest_path = GUIDES / "manifest.json"
    known = {g["file"]: g for g in json.loads(manifest_path.read_text(encoding="utf-8"))} if manifest_path.exists() else {}
    records = []
    for path in sorted(GUIDES.glob("*.pdf")):
        guide = known.get(path.name, {"key": re.sub(r"\W+", "_", path.stem).strip("_").lower(),
                                        "title_ko": path.stem, "title_en": path.stem, "version": "",
                                        "page_url": "", "sections": []})
        counts = {}
        for piece in guide_pieces(path, guide["sections"]):
            counts[piece["page"]] = counts.get(piece["page"], 0) + 1
            records.append({
                "id": f"guide:{guide['key']}:p{piece['page']}#{counts[piece['page']]}", "kind": "guide",
                "law": guide["key"], "law_ko": guide["title_ko"], "law_en": guide["title_en"],
                "label": f"p.{piece['page']}", "title": piece["section"] or guide["title_ko"], "chapter": "",
                "file": path.name, "page": piece["page"], "effective": guide["version"], "url": guide["page_url"],
                "text": (f"[{piece['section']}] " if piece["section"] else "") + piece["text"],
            })
    return records


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    korean = build_korean()
    write_jsonl(ARTICLES, korean)
    articles = sum(1 for r in korean if r["kind"] == "article")
    print(f"Korean: {len(korean)} pieces ({articles} article pieces, {len(korean) - articles} table pieces)")
    english = build_english()
    if english:
        write_jsonl(LAWS_EN / "articles_en.jsonl", english)
        print(f"English: {len(english)} articles")
    guides = build_guides()
    if guides:
        write_jsonl(GUIDES / "guides.jsonl", guides)
        print(f"Guides: {len(guides)} pieces from {len({g['file'] for g in guides})} PDF(s)")


if __name__ == "__main__":
    main()
