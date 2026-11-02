"""Paths and settings shared by every step."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LAWS_KO = DATA / "laws" / "ko"          # official Korean PDFs (public domain, committed)
LAWS_EN = DATA / "laws" / "en"          # KLRI English PDFs (personal use only, git-ignored)
ARTICLES = DATA / "articles.jsonl"      # one searchable piece per article / attached table
INDEX = ROOT / "index"                  # Qdrant collection + keyword index (rebuilt by script)
MODELS = ROOT / "models"                # downloaded model weights (git-ignored)
EVAL = ROOT / "eval"
DOCS = ROOT / "docs"

# The laws a foreign resident in Korea is most likely to need.
# key: (Korean name, English name)
LAWS = {
    "immigration_act": ("출입국관리법", "Immigration Act"),
    "immigration_decree": ("출입국관리법 시행령", "Enforcement Decree of the Immigration Act"),
    "immigration_rules": ("출입국관리법 시행규칙", "Enforcement Rules of the Immigration Act"),
    "nationality_act": ("국적법", "Nationality Act"),
    "nationality_decree": ("국적법 시행령", "Enforcement Decree of the Nationality Act"),
    "foreign_workers_act": ("외국인근로자의 고용 등에 관한 법률", "Act on the Employment of Foreign Workers"),
    "foreigners_framework_act": ("재한외국인 처우 기본법", "Framework Act on Treatment of Foreigners Residing in Korea"),
    "overseas_koreans_act": ("재외동포의 출입국과 법적 지위에 관한 법률", "Act on the Immigration and Legal Status of Overseas Koreans"),
    "refugee_act": ("난민법", "Refugee Act"),
}

EMBED_MODEL = "BAAI/bge-m3"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
LLM_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
COLLECTION = "articles"
