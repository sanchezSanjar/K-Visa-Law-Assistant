"""Measure how often search finds the right article, and how good the answers are.

    python -m kvisa.evaluate search     # compare search methods (writes docs/search_metrics.json)
    python -m kvisa.evaluate answers    # answer every question (writes docs/answer_metrics.json)

A question counts as found when any of its expected articles is retrieved. An expected id matches
every piece of that article; "law:tableNN=D-2" matches the table row that defines visa D-2.
"""
import json
import sys
import time

from kvisa.config import ARTICLES, DOCS, EVAL, GUIDES

METHODS = [
    ("Keyword (BM25)", "keyword", False),
    ("Meaning (bge-m3)", "dense", False),
    ("Hybrid (keyword + meaning)", "hybrid", False),
    ("Meaning + reranker", "dense", True),
    ("Hybrid + reranker", "hybrid", True),
]


# "main": 84 questions written while reading the laws (80 + 4 the laws cannot answer).
# "held-out": 30 harder, more indirect questions written after the search method was chosen.
# "guide": 15 practical questions answered by the Ministry of Justice guide (only when it was downloaded).
QUESTION_SETS = {"main": "questions.jsonl", "held-out": "questions_holdout.jsonl"}
if (GUIDES / "guides.jsonl").exists():
    QUESTION_SETS["guide"] = "questions_guide.jsonl"


def load_questions(name: str = "main") -> list[dict]:
    return [json.loads(line) for line in (EVAL / QUESTION_SETS[name]).open(encoding="utf-8")]


_DEFINES: dict[str, set] = {}


def visa_rows(piece_id: str) -> set:
    """Visa codes whose definition row is in this table piece."""
    if not _DEFINES:
        for line in ARTICLES.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            _DEFINES[record["id"]] = set(record.get("defines", []))
    return _DEFINES.get(piece_id, set())


def is_expected(piece_id: str, expected: list[str]) -> bool:
    for e in expected:
        if "=" in e:  # "law:tableNN=D-2": the table row that defines visa D-2
            table, code = e.split("=")
            if piece_id.split("#")[0] == table and code in visa_rows(piece_id):
                return True
        elif piece_id == e or piece_id.split("#")[0] == e:
            return True
    return False


def first_hit_rank(ids: list[str], expected: list[str]) -> int | None:
    for rank, piece_id in enumerate(ids, start=1):
        if is_expected(piece_id, expected):
            return rank
    return None


def summarize(ranks: list[int | None]) -> dict:
    """hit@4 = the right article is among the 4 pieces the answer model reads."""
    n = len(ranks)
    return {
        "questions": n,
        "hit@1": round(sum(1 for r in ranks if r == 1) / n, 3),
        "hit@4": round(sum(1 for r in ranks if r and r <= 4) / n, 3),
        "hit@10": round(sum(1 for r in ranks if r and r <= 10) / n, 3),
        "mrr@10": round(sum(1 / r for r in ranks if r and r <= 10) / n, 3),
    }


def evaluate_search() -> dict:
    from kvisa.search import Searcher

    searcher = Searcher(dense=True, rerank=True)
    results = {}
    for set_name in QUESTION_SETS:
        questions = [q for q in load_questions(set_name) if q["type"] != "out_of_scope"]
        results[set_name] = {}
        print(f"{set_name} questions ({len(questions)})")
        for name, mode, rerank in METHODS:
            ranks, by_lang, misses = [], {"ko": [], "en": []}, []
            started = time.perf_counter()
            for q in questions:
                if rerank:
                    ids = [hit["id"] for hit in searcher.search(q["question"], top_k=10, mode=mode)]
                else:
                    ids = [searcher.records[i]["id"] for i, _ in searcher.candidates(q["question"], mode, k=10)]
                rank = first_hit_rank(ids, q["expected"])
                ranks.append(rank)
                by_lang[q["lang"]].append(rank)
                if not rank or rank > 4:
                    misses.append({"id": q["id"], "question": q["question"], "expected": q["expected"],
                                   "got": ids[:3]})
            seconds = (time.perf_counter() - started) / len(questions)
            result = {"all": summarize(ranks), "korean": summarize(by_lang["ko"]),
                      "english": summarize(by_lang["en"]), "seconds_per_question": round(seconds, 3),
                      "misses_top4": misses}
            results[set_name][name] = result
            line = result["all"]
            print(f"  {name:28s} hit@1 {line['hit@1']:.2f}  hit@4 {line['hit@4']:.2f}  MRR {line['mrr@10']:.2f}  "
                  f"({seconds:.2f}s per question)")
        # What the app really gives the model: 4 law pieces + 1 guide piece, ranked in separate pools.
        ranks = [first_hit_rank([p["id"] for p in searcher.context(q["question"])], q["expected"]) for q in questions]
        in_context = round(sum(1 for r in ranks if r) / len(ranks), 3)
        results[set_name]["App context (4 law + 1 guide pieces)"] = {"in_context": in_context}
        print(f"  {'App context (4 law + 1 guide)':28s} in context {in_context:.2f}")
    searcher.close()
    english = sum(1 for r in searcher.records if r.get("text_en"))
    results["_setup"] = {"pieces": len(searcher.records), "pieces_with_english": english}
    DOCS.mkdir(exist_ok=True)
    (DOCS / "search_metrics.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "search"
    if target == "search":
        evaluate_search()
    elif target == "answers":
        from kvisa.answer import evaluate_answers
        evaluate_answers()
    else:
        raise SystemExit("usage: python -m kvisa.evaluate [search|answers]")


if __name__ == "__main__":
    main()
