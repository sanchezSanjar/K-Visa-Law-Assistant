"""Hybrid search over the law pieces.

The app uses meaning search (bge-m3 vectors in a local Qdrant collection, works across languages)
and reranks the 20 best pieces with a cross-encoder (bge-reranker-v2-m3) that reads the question and
the article together. Keyword search (BM25 over Korean character pairs) and a hybrid of both are kept
for comparison: on the test questions they were less accurate (see docs/search_metrics.json).

    python -m kvisa.search build                 # embed all pieces into index/
    python -m kvisa.search "D-2 비자로 아르바이트 할 수 있나요?"
"""
import hashlib
import json
import math
import re
import shutil
import sys
from collections import Counter, defaultdict

from kvisa.config import ARTICLES, COLLECTION, EMBED_MODEL, GUIDES, INDEX, LAWS_EN, RERANK_MODEL
from kvisa.models import local_path

RRF_K = 60

def load_records() -> list[dict]:
    records = [json.loads(line) for line in ARTICLES.open(encoding="utf-8")]
    english_path = LAWS_EN / "articles_en.jsonl"
    if english_path.exists():
        english = {}
        for line in english_path.open(encoding="utf-8"):
            item = json.loads(line)
            english[item["id"]] = item
        for record in records:
            match = english.get(record["id"].split("#")[0])
            if match:
                record["text_en"] = match["text"]
    guides_path = GUIDES / "guides.jsonl"
    if guides_path.exists():  # practical guides downloaded to this PC (python -m kvisa.download_guides)
        records += [json.loads(line) for line in guides_path.open(encoding="utf-8")]
    return records


def doc_text(record: dict) -> str:
    text = f"{record['law_ko']} {record['text']}"
    if record.get("text_en"):
        text += f"\n{record['law_en']} {record['text_en']}"
    return text


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = re.findall(r"\b[a-h]-\d{1,2}(?:-\d{1,2})?\b", text)   # visa codes such as d-2, f-5
    tokens += re.findall(r"[a-z]{2,}|\d+", text)
    for run in re.findall(r"[가-힣]+", text):
        tokens += [run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)]
    return tokens


class BM25:
    def __init__(self, texts: list[str], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(text)) for text in texts]
        self.lengths = [sum(doc.values()) for doc in self.docs]
        self.avg_length = sum(self.lengths) / len(self.lengths)
        self.postings = defaultdict(list)
        for index, doc in enumerate(self.docs):
            for token in doc:
                self.postings[token].append(index)
        n = len(self.docs)
        self.idf = {token: math.log(1 + (n - len(ids) + 0.5) / (len(ids) + 0.5))
                    for token, ids in self.postings.items()}

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        scores = defaultdict(float)
        for token, count in Counter(tokenize(query)).items():
            for index in self.postings.get(token, ()):
                tf = self.docs[index][token]
                norm = tf + self.k1 * (1 - self.b + self.b * self.lengths[index] / self.avg_length)
                scores[index] += self.idf[token] * tf * (self.k1 + 1) / norm
        return sorted(scores.items(), key=lambda item: -item[1])[:k]


def rrf(*rankings: list[tuple[int, float]], k: int) -> list[tuple[int, float]]:
    fused = defaultdict(float)
    for ranking in rankings:
        for rank, (index, _) in enumerate(ranking):
            fused[index] += 1 / (RRF_K + rank + 1)
    return sorted(fused.items(), key=lambda item: -item[1])[:k]


def device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_embedder(dev: str | None = None):
    """bge-m3 on the GPU for building the index; the app embeds one short question at a time on the
    CPU (well under a second), which leaves about 1 GB more GPU memory for answering."""
    import torch
    from sentence_transformers import SentenceTransformer
    dev = dev or device()
    kwargs = {"torch_dtype": torch.float16} if dev == "cuda" else {}
    return SentenceTransformer(str(local_path(EMBED_MODEL)), device=dev, model_kwargs=kwargs)


def load_reranker():
    import torch
    from sentence_transformers import CrossEncoder
    dev = device()
    kwargs = {"torch_dtype": torch.float16} if dev == "cuda" else {}
    return CrossEncoder(str(local_path(RERANK_MODEL)), device=dev, max_length=1024, model_kwargs=kwargs)


def fingerprint(records: list[dict]) -> str:
    digest = hashlib.sha1()
    for record in records:
        digest.update(doc_text(record).encode("utf-8"))
    return digest.hexdigest()


def build_index() -> None:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    records = load_records()
    embedder = load_embedder()
    vectors = embedder.encode([doc_text(r) for r in records], batch_size=8, normalize_embeddings=True,
                              show_progress_bar=True)
    INDEX.mkdir(exist_ok=True)
    # Start from an empty folder: in local mode a deleted and re-created collection kept the old
    # points beyond the new count when the index got smaller.
    shutil.rmtree(INDEX / "qdrant", ignore_errors=True)
    client = QdrantClient(path=str(INDEX / "qdrant"))
    client.create_collection(COLLECTION, vectors_config=VectorParams(size=vectors.shape[1], distance=Distance.COSINE))
    client.upsert(COLLECTION, points=[PointStruct(id=i, vector=v.tolist(), payload={"id": r["id"]})
                                      for i, (r, v) in enumerate(zip(records, vectors))])
    client.close()
    (INDEX / "fingerprint.txt").write_text(fingerprint(records), encoding="utf-8")
    english = sum(1 for r in records if r.get("text_en"))
    print(f"Indexed {len(records)} pieces ({english} with English text) in {INDEX}")


class Searcher:
    """Loads the models once; `search` returns the best law pieces for a question."""

    def __init__(self, dense: bool = True, rerank: bool = True) -> None:
        self.records = load_records()
        self.bm25 = BM25([doc_text(r) for r in self.records])
        self.embedder = self.client = self.reranker = None
        if dense:
            from qdrant_client import QdrantClient
            stamp = INDEX / "fingerprint.txt"
            if not stamp.exists() or stamp.read_text(encoding="utf-8") != fingerprint(self.records):
                raise RuntimeError("The search index is missing or out of date: run python -m kvisa.search build")
            self.embedder = load_embedder("cpu")
            self.client = QdrantClient(path=str(INDEX / "qdrant"))
        if rerank:
            self.reranker = load_reranker()

    def keyword(self, query: str, k: int = 50) -> list[tuple[int, float]]:
        return self.bm25.search(query, k)

    def dense(self, query: str, k: int = 50) -> list[tuple[int, float]]:
        vector = self.embedder.encode(query, normalize_embeddings=True)
        hits = self.client.query_points(COLLECTION, query=vector.tolist(), limit=k).points
        return [(hit.id, hit.score) for hit in hits]

    def candidates(self, query: str, mode: str, k: int = 50) -> list[tuple[int, float]]:
        if mode == "keyword":
            return self.keyword(query, k)
        if mode == "dense":
            return self.dense(query, k)
        return rrf(self.keyword(query, k), self.dense(query, k), k=k)

    def rerank(self, query: str, pool: list[int]) -> list[tuple[int, float]]:
        scores = self.reranker.predict([(query, doc_text(self.records[i])) for i in pool], batch_size=8)
        return sorted(zip(pool, (float(s) for s in scores)), key=lambda item: -item[1])

    def search(self, query: str, top_k: int = 5, mode: str = "dense", rerank_depth: int = 20) -> list[dict]:
        ranked = self.candidates(query, mode)
        if self.reranker is not None and rerank_depth:
            ranked = self.rerank(query, [index for index, _ in ranked[:rerank_depth]])
        return [{**self.records[index], "score": round(score, 4)} for index, score in ranked[:top_k]]

    def context(self, query: str, laws: int = 4, guides: int = 1, depth: int = 20,
                min_guide_score: float = 0.1) -> list[dict]:
        """The pieces the answer model reads: the best law pieces plus the best guide piece.

        Laws and guides are ranked in separate pools, so the guide adds practical detail without
        pushing law articles out (measured: law results stay as they were without the guide).
        A guide piece is only added when the reranker finds it relevant: an unrelated page (score
        near 0) misled the model more than no guide at all.
        """
        ranked = self.candidates(query, "dense", k=200)
        law_pool = [i for i, _ in ranked if self.records[i]["kind"] != "guide"][:depth]
        guide_pool = [i for i, _ in ranked if self.records[i]["kind"] == "guide"][:depth]
        law_hits = self.rerank(query, law_pool)[:laws]
        guide_hits = [hit for hit in self.rerank(query, guide_pool)[:guides] if hit[1] >= min_guide_score] \
            if guide_pool else []
        chosen = sorted(law_hits + guide_hits, key=lambda item: -item[1])
        return [{**self.records[index], "score": round(score, 4)} for index, score in chosen]

    def close(self) -> None:
        if self.client is not None:
            self.client.close()


def main() -> None:
    if sys.argv[1:] == ["build"]:
        build_index()
        return
    searcher = Searcher()
    for hit in searcher.search(" ".join(sys.argv[1:])):
        print(f"{hit['score']:.3f}  {hit['law_ko']} {hit['label']}({hit['title']})  p.{hit['page']}")
    searcher.close()


if __name__ == "__main__":
    main()
