"""Web app: FastAPI backend + a single-page chat UI, all on this PC.

    python -m kvisa.server --port 8000

The models load in the background after start (about 30 s); /api/health reports when ready.
"""
import argparse
import json
import os
import threading
import time

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kvisa.config import GUIDES, LAWS_KO, ROOT

STATIC = ROOT / "app"
app = FastAPI(title="K-Visa Law Assistant")
state = {"assistant": None, "error": None}
PDF_FILES = {path.name: path for folder in (LAWS_KO, GUIDES) for path in folder.glob("*.pdf")}


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=500)


def load_models() -> None:
    try:
        from kvisa.answer import Assistant
        state["assistant"] = Assistant()
    except Exception as error:  # shown in the UI instead of a silent failure
        state["error"] = f"{type(error).__name__}: {error}"


def public_source(piece: dict) -> dict:
    keys = ("id", "kind", "law_ko", "law_en", "label", "title", "page", "file", "url", "effective", "text",
            "text_en", "score")
    return {key: piece.get(key) for key in keys}


@app.get("/api/health")
def health() -> dict:
    return {"ready": state["assistant"] is not None, "error": state["error"]}


@app.post("/api/ask")
def ask(body: Question):
    from kvisa.answer import cited_numbers

    assistant = state["assistant"]
    if assistant is None:
        raise HTTPException(503, state["error"] or "Models are still loading")

    def events():
        started = time.perf_counter()
        pieces = assistant.retrieve(body.question)
        yield json.dumps({"type": "sources", "sources": [public_source(p) for p in pieces]}, ensure_ascii=False) + "\n"
        answer = ""
        for token in assistant.stream(body.question, pieces):
            answer += token
            yield json.dumps({"type": "token", "text": token}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "done", "cited": cited_numbers(answer, len(pieces)),
                          "seconds": round(time.perf_counter() - started, 1)}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/pdf/{name}")
def pdf(name: str):
    if name not in PDF_FILES:  # only the downloaded law and guide PDFs, never other paths
        raise HTTPException(404)
    return FileResponse(PDF_FILES[name], media_type="application/pdf")


@app.post("/api/quit")
def quit_app():
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return JSONResponse({"ok": True})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    threading.Thread(target=load_models, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
