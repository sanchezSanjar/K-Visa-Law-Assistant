# K-Visa Law Assistant

Ask questions about Korean immigration, visa and nationality law in Korean or English, and get a
short answer that cites the exact law article it comes from. Retrieval-augmented generation (RAG)
over the official law PDFs, running fully on your own PC with open models on the GPU.

![Chat with cited articles](docs/chat.png)

## Highlights

- **Official sources**: the current Korean text of 9 laws and 18 attached tables (visa types,
  maximum stay, required documents, fines), downloaded as PDFs from the National Law Information
  Center (law.go.kr).
- **Every answer cites its articles**, e.g. `출입국관리법 제31조(외국인등록)`, with a link that opens
  the official PDF on the right page. When the laws do not answer a question, it says so.
- **Measured honestly** on 114 test questions, including 30 harder held-out questions written after
  all tuning was done (results below).
- **Private and offline**: no API key, nothing leaves the PC after setup.
- Web chat UI (FastAPI) and a double-click **`KVisaLaw.exe`**.

## How it works

```text
law.go.kr PDFs ─► parse ─► 870 pieces ─► bge-m3 vectors (local Qdrant)
                 (one per article,                    │
                  one per visa-table row)             ▼
question ──────────────────────────────► meaning search, top 20
                                                      │
                                         bge-reranker-v2-m3, top 4
                                                      │
                                                      ▼
                         Qwen3-4B-Instruct (4-bit, GPU): short answer with [1] [2] citations
```

| Step | File | What it does |
|---|---|---|
| Download | `kvisa/download.py` | Finds the version of each law in force today on law.go.kr and saves the law PDF and its attached-table PDFs |
| Parse | `kvisa/parse.py` | Reads the PDFs with PyMuPDF: one piece per article (long articles split at ①, ②), one per table row; rebuilds the spaces that the table PDFs leave out; drops amendment notes and addenda |
| Search | `kvisa/search.py` | bge-m3 embeddings in a local Qdrant collection, then a cross-encoder reranker. A BM25 keyword search over Korean character pairs is kept as a baseline |
| Answer | `kvisa/answer.py` | Qwen3-4B-Instruct-2507 in 4-bit reads the 4 best pieces, answers in the question's language and cites them |
| Evaluate | `kvisa/evaluate.py` | Search and answer metrics on the test questions in `eval/` |
| App | `kvisa/server.py`, `app/` | FastAPI backend with streaming answers and a chat page with source cards |

## Results

Two question sets in `eval/`, each question labelled with the article(s) that answer it:

- **Main**: 80 questions in plain language (72 Korean, 8 English) covering all 9 laws, plus 4
  questions the laws cannot answer (office address, online booking, exact part-time hours, card
  waiting time).
- **Held-out**: 30 harder questions with more indirect wording ("Can I work at a convenience store
  as a student?"), written after all choices below were made and never used to tune anything.

### Search: is the right article found?

"In context" means the right article is among the 4 pieces the answer model reads.

| Method | Main: 1st | Main: in context | Held-out: 1st | Held-out: in context | Time |
|---|---|---|---|---|---|
| Keyword (BM25) | 45% | 74% | 17% | 33% | 0.00 s |
| Meaning (bge-m3) | 85% | 95% | 40% | 73% | 0.03 s |
| Hybrid (keyword + meaning) | 57% | 95% | 33% | 60% | 0.02 s |
| **Meaning + reranker (used)** | 80% | 95% | **60%** | **80%** | 0.65 s |
| Hybrid + reranker | 80% | 96% | 47% | 70% | 0.65 s |

What the numbers showed:

- **Keyword search fails on everyday wording**, and mixing it in (hybrid) made results worse, not
  better. The laws use formal terms (체류자격 외 활동) that questions rarely contain.
- On the main set the reranker looked useless (80% vs 85% first), but **on the held-out questions it
  was clearly better** (60% vs 40% first, 80% vs 73% in context), so the app uses it. The main set
  turned out to be too close to the article titles; without the held-out set the results would have
  looked better than they are.
- A small glossary of everyday words (아르바이트 → 체류자격 외 활동허가) fixed the misses of the main
  set but did nothing on the held-out set, so it was dropped.
- Splitting the visa tables into one piece per visa type made questions like "What visa does the
  foreign spouse of a Korean get?" findable.

### Answers

| | Main (80 + 4) | Held-out (30) |
|---|---|---|
| Answer cites the right article | **94%** | **77%** |
| Answer has at least one citation | 98% | 97% |
| Wrongly said "not found" | 2.5% | 6.7% |
| Out-of-scope questions answered with "not found" | **4 / 4** | – |
| Answered in the language of the question | 100% | 100% |
| Median time per answer (RTX 3060 Laptop) | 13.5 s | 12.9 s |

In the app the first words appear after 1 to 2 seconds (streaming). A first version refused to
answer when the reranker score of the best piece was below 0.05; it blocked 8 real questions and
only 2 out-of-scope ones, while the model refused every out-of-scope question by itself, so the
threshold was removed. All answers are saved in `docs/answer_metrics.json`.

Checked by hand: in a random sample of 8 answers, 7 were correct and 1 incomplete (detention: it
gave the 48-hour temporary hold but not the 10-day rule). A typical failure: asked whether a student
may work at a convenience store, the model found no article forbidding it and answered "no problem";
in fact a student needs permission for activities outside the status of stay (Article 20).

## Setup (Windows)

1. Install Python 3.11+ (64-bit). An NVIDIA GPU with 6 GB or more is recommended
   (tested on an RTX 3060 Laptop GPU); without one, answers are slow.
2. Double-click `INSTALL_WINDOWS.bat`. It installs the packages, downloads the open models
   (about 12 GB), optionally the English translations, and builds the search index.
3. Double-click **`KVisaLaw.exe`**. The chat opens in your browser; it runs only on your PC.
   Use **종료** (Stop) in the top bar to close it.

Windows SmartScreen may warn once because the exe is not code-signed: **More info → Run anyway**.

Command line:

```bat
.venv\Scripts\python.exe -m kvisa.download              & rem official Korean law PDFs (already in data/)
.venv\Scripts\python.exe -m kvisa.download_english      & rem optional English translations, personal use
.venv\Scripts\python.exe -m kvisa.parse                 & rem PDFs -> data\articles.jsonl
.venv\Scripts\python.exe -m kvisa.search build          & rem search index
.venv\Scripts\python.exe -m kvisa.answer "외국인등록은 언제까지 해야 하나요?"
.venv\Scripts\python.exe -m kvisa.evaluate search       & rem compare search methods
.venv\Scripts\python.exe -m kvisa.evaluate answers      & rem answer all test questions
.venv\Scripts\python.exe -m unittest discover -s tests -t .
.venv\Scripts\python.exe -m kvisa.server --port 8000
```

## Project structure

```text
K-Visa-Law-Assistant/
├── KVisaLaw.exe                # Double-click launcher
├── kvisa/
│   ├── download.py             # Official Korean law PDFs from law.go.kr
│   ├── download_english.py     # Optional KLRI English translations (git-ignored)
│   ├── parse.py                # PDFs -> articles and table rows
│   ├── search.py               # Meaning search + reranker (and keyword baseline)
│   ├── answer.py               # Answers with citations from a local model
│   ├── evaluate.py             # Search and answer metrics
│   ├── server.py               # FastAPI backend
│   ├── models.py               # Downloads the open models
│   └── config.py
├── app/                        # Chat page (HTML, CSS, JavaScript)
├── data/laws/ko/               # Official law PDFs + manifest
├── data/articles.jsonl         # 870 searchable pieces
├── eval/                       # Test questions (main and held-out)
├── docs/                       # Metrics and screenshots
├── tests/
└── launcher/                   # Exe source, icon and build script
```

## Limitations

- **Information, not legal advice.** The Korean law text is the official version. For your own case,
  ask the Immigration Contact Center (☎ 1345) or an expert.
- **Only what the laws say.** Practical details such as office hours, online booking or the exact
  part-time work hours for D-2 students are in Ministry of Justice guidelines, not in these laws.
- **Everyday wording is the hardest part.** A question like "Can a student work at a convenience
  store?" must be matched to "activities outside the status of stay" (Article 20); search still misses
  some of these (see the held-out results).
- Some spaces between Korean words are missing where a line wraps in the PDF; search is not affected.
- The laws change: run `python -m kvisa.download` and rebuild to update. The data in this repository
  is the version in force on 2 Nov 2026.

## Credits and licenses

- Code: MIT (see `LICENSE`).
- Laws: official Korean texts from the [National Law Information Center](https://www.law.go.kr/)
  (Ministry of Government Legislation). Korean statutes are not protected by copyright
  (Copyright Act, Article 7).
- English translations: [Korea Legislation Research Institute](https://elaw.klri.re.kr/), copyrighted;
  downloaded only to your own PC for personal use and never included in this repository.
- Models: [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) (MIT),
  [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) (Apache-2.0),
  [Qwen/Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) (Apache-2.0).
- Vector database: [Qdrant](https://qdrant.tech/) (local mode).
