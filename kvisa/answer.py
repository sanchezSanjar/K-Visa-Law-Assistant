"""Answer a question from the retrieved law pieces with a local open model (Qwen3-4B, 4-bit on GPU).

The model sees only the numbered law pieces, must cite them as [1], [2], ... and must say so when
the answer is not in them. Answers come in the language of the question.

    python -m kvisa.answer "외국인등록은 언제까지 해야 하나요?"
"""
import json
import re
import sys
import threading
import time
from typing import Iterator

from kvisa.config import DOCS, LLM_MODEL
from kvisa.models import local_path

PIECE_CHARS = 1500        # each piece is cut to this length in the prompt
GUIDE_PIECE_CHARS = 1000  # manual pages are cut shorter, so the prompt fits a 6 GB GPU
NOT_FOUND = {
    "ko": "제공된 법령에서 이 질문에 대한 내용을 찾을 수 없습니다.",
    "en": "I could not find this in the provided laws.",
}

SYSTEM = """당신은 대한민국 출입국·체류·국적 법령을 안내하는 도우미입니다.
규칙:
1. 아래 [자료]에 있는 내용만 근거로 답하세요. 자료에 없는 내용(수수료 금액, 기간, 서류 등)을 지어내지 마세요.
2. 근거로 쓴 자료 번호를 문장 끝에 [1], [2]처럼 표시하세요.
3. 자료에 답이 없으면 "{not_found}"라고만 답하세요.
4. 자료에 금지한다는 내용이 없다고 해서 허용된다고 추론하지 마세요. 허가가 필요한지 자료에 나오지 않으면 그렇다고 말하세요.
5. [자료]에는 법령과 법무부 안내서가 있을 수 있습니다. 법령이 우선이며, 안내서 내용은 "안내서에 따르면"처럼 밝히세요.
6. 질문과 같은 언어로 답하세요. 질문이 영어면 영어로, 한국어면 한국어로 답하세요.
7. 3~6문장으로 짧고 쉽게 설명하세요. 법률 자문이 아니라 정보 안내입니다."""


def question_language(text: str) -> str:
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "ko" if hangul >= latin else "en"


def source_title(piece: dict) -> str:
    if piece.get("kind") == "guide":
        return f"[안내서] {piece['law_ko']} {piece['label']} · {piece['title']}"
    return f"{piece['law_ko']} {piece['label']}({piece['title']})"


def build_context(pieces: list[dict], lang: str) -> str:
    blocks = []
    for number, piece in enumerate(pieces, start=1):
        text = piece["text"][:GUIDE_PIECE_CHARS if piece.get("kind") == "guide" else PIECE_CHARS]
        if lang == "en" and piece.get("text_en"):
            text += f"\n(English translation, for reference) {piece['text_en'][:PIECE_CHARS]}"
        blocks.append(f"[{number}] {source_title(piece)}\n{text}")
    return "\n\n".join(blocks)


def cited_numbers(answer: str, count: int) -> list[int]:
    numbers = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    return sorted(n for n in numbers if 1 <= n <= count)


class Assistant:
    """Search + answer. Loads every model once (about 5 GB of GPU memory)."""

    def __init__(self, searcher=None) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        from kvisa.search import Searcher

        self.searcher = searcher or Searcher()
        path = str(local_path(LLM_MODEL))
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        if torch.cuda.is_available():
            quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                       bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
            self.model = AutoModelForCausalLM.from_pretrained(path, quantization_config=quant, device_map="cuda:0")
        else:
            self.model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.float32)
        self.model.eval()
        self.lock = threading.Lock()  # one generation at a time on the GPU

    def retrieve(self, question: str) -> list[dict]:
        return self.searcher.context(question)  # 4 law pieces + the best relevant guide piece

    def prompt(self, question: str, pieces: list[dict], lang: str) -> str:
        messages = [
            {"role": "system", "content": SYSTEM.format(not_found=NOT_FOUND[lang])},
            {"role": "user", "content": f"[자료]\n{build_context(pieces, lang)}\n\n[질문]\n{question}"},
        ]
        return self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    def stream(self, question: str, pieces: list[dict], max_new_tokens: int = 450) -> Iterator[str]:
        from transformers import TextIteratorStreamer

        lang = question_language(question)
        if not pieces:
            yield NOT_FOUND[lang]
            return
        inputs = self.tokenizer(self.prompt(question, pieces, lang), return_tensors="pt").to(self.model.device)
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        kwargs = dict(**inputs, streamer=streamer, max_new_tokens=max_new_tokens, do_sample=False,
                      repetition_penalty=1.05, pad_token_id=self.tokenizer.eos_token_id)
        with self.lock:
            thread = threading.Thread(target=self.model.generate, kwargs=kwargs, daemon=True)
            thread.start()
            yield from streamer
            thread.join()

    def ask(self, question: str) -> dict:
        started = time.perf_counter()
        pieces = self.retrieve(question)
        answer = "".join(self.stream(question, pieces)).strip()
        cited = cited_numbers(answer, len(pieces))
        return {"question": question, "answer": answer, "sources": pieces, "cited": cited,
                "seconds": round(time.perf_counter() - started, 2)}


def is_refusal(answer: str) -> bool:
    """The model said the laws do not contain the answer (in the fixed sentence or its own words)."""
    first = re.split(r"(?<=[.!?。])\s", answer.strip(), maxsplit=1)[0]
    return ("찾을 수 없" in answer or "could not find" in answer.lower()
            or ("제공된 법령" in first and "없" in first)
            or ("provided laws" in first.lower() and re.search(r"\b(not|no)\b", first.lower()) is not None))


def summarize_answers(rows: list[dict]) -> dict:
    law = [r for r in rows if r["type"] != "out_of_scope"]
    out = [r for r in rows if r["type"] == "out_of_scope"]
    summary = {
        "answerable_questions": len(law),
        "expected_article_in_context": round(sum(r["retrieved_expected"] for r in law) / len(law), 3),
        "answer_cites_expected_article": round(sum(r["cites_expected"] for r in law) / len(law), 3),
        "answered_with_a_citation": round(sum(bool(r["cited"]) for r in law) / len(law), 3),
        "wrongly_refused": round(sum(r["refused"] for r in law) / len(law), 3),
        "same_language_as_question": round(sum(r["language_ok"] for r in rows) / len(rows), 3),
        "median_seconds": sorted(r["seconds"] for r in rows)[len(rows) // 2],
    }
    if out:
        summary["out_of_scope_questions"] = len(out)
        summary["out_of_scope_refused"] = round(sum(r["refused"] for r in out) / len(out), 3)
    return summary


def evaluate_answers() -> dict:
    from kvisa.evaluate import QUESTION_SETS, is_expected, load_questions

    assistant = Assistant()
    report = {}
    for set_name in QUESTION_SETS:
        rows = []
        for q in load_questions(set_name):
            result = assistant.ask(q["question"])
            cited_ids = [result["sources"][n - 1]["id"] for n in result["cited"]]
            rows.append({
                "id": q["id"], "type": q["type"], "lang": q["lang"], "question": q["question"],
                "answer": result["answer"], "sources": [p["id"] for p in result["sources"]],
                "top_score": result["sources"][0]["score"] if result["sources"] else 0.0, "cited": cited_ids,
                "cites_expected": any(is_expected(c, q["expected"]) for c in cited_ids),
                "retrieved_expected": any(is_expected(p["id"], q["expected"]) for p in result["sources"]),
                "refused": is_refusal(result["answer"]),
                "language_ok": question_language(result["answer"]) == q["lang"], "seconds": result["seconds"],
            })
            print(f"{set_name} {q['id']}  {result['seconds']:5.1f}s  cites expected: {rows[-1]['cites_expected']}  "
                  f"refused: {rows[-1]['refused']}", flush=True)
        report[set_name] = {"summary": summarize_answers(rows), "answers": rows}
        print(set_name, json.dumps(report[set_name]["summary"], indent=2), flush=True)
    DOCS.mkdir(exist_ok=True)
    (DOCS / "answer_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    assistant = Assistant()
    result = assistant.ask(" ".join(sys.argv[1:]))
    print(result["answer"])
    print()
    for number, piece in enumerate(result["sources"], start=1):
        mark = "*" if number in result["cited"] else " "
        print(f"{mark}[{number}] {source_title(piece)}  (score {piece['score']:.2f}, PDF p.{piece['page']})")
    print(f"\n{result['seconds']}s")


if __name__ == "__main__":
    main()
