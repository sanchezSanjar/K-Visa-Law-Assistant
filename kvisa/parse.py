"""Turn the law PDFs into searchable pieces: one per article, and row groups for attached tables.

    python -m kvisa.parse

Writes data/articles.jsonl (Korean, committed) and, when the English PDFs were downloaded,
data/laws/en/articles_en.jsonl (git-ignored) with the matching English article text.
"""
import json
import re
from pathlib import Path

import pymupdf

from kvisa.config import ARTICLES, LAWS_EN, LAWS_KO

MAX_CHARS = 1800          # longer articles are split at paragraph marks (①, ②, ...)
TABLE_CHUNK_CHARS = 1000  # attached tables are packed into pieces of about this size

KO_ARTICLE = re.compile(r"^제(\d+)조(?:의(\d+))?\s*\(([^)]*)\)\s*(.*)$")
KO_DELETED = re.compile(r"^제\d+조(?:의\d+)?\s*삭제")
KO_CHAPTER = re.compile(r"^제\d+장(?:의\d+)?\s+\S")
KO_ADDENDA = re.compile(r"^부\s*칙\s*(<|$)")
EN_ARTICLE = re.compile(r"^Article\s+(\d+)(?:-(\d+))?\s*\(([^)]*)\)\s*(.*)$")
EN_DELETED = re.compile(r"^Article\s+\d+(?:-\d+)?\s+Deleted")
EN_CHAPTER = re.compile(r"^CHAPTER\s+[IVXLC]+(?:-\d+)?\b")
EN_ADDENDA = re.compile(r"^ADDENDA\b")
AMENDMENT_NOTES = re.compile(r"<(?:개정|신설|Amended|Newly inserted)[^>]*>|\[(?:전문개정|본조신설|제목개정|"
                             r"종전|This Article|Moved from|Previous)[^\]]*\]")
VISA_CODE = re.compile(r"\b([A-H]-\d{1,2}(?:-\d{1,2})?)\b")
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
    """Group table rows (lines that start a numbered item) into pieces of about TABLE_CHUNK_CHARS."""
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
    pieces, piece = [], []
    for row in rows:
        size = sum(len(text) for _, text in piece)
        if piece and size + sum(len(text) for _, text in row) > TABLE_CHUNK_CHARS:
            pieces.append(piece)
            piece = []
        piece.extend(row)
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


if __name__ == "__main__":
    main()
