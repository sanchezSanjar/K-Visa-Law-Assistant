"""Download the open models once into models/, so the app then runs offline.

    python -m kvisa.models
"""
from huggingface_hub import HfApi, snapshot_download

from kvisa.config import EMBED_MODEL, LLM_MODEL, MODELS, RERANK_MODEL

SKIP = ["onnx/*", "*.onnx", "imgs/*", "*.png", "*.jpg", "colbert_linear.pt", "sparse_linear.pt"]


def local_path(repo_id: str):
    return MODELS / repo_id.split("/")[-1]


def download(repo_id: str) -> None:
    files = HfApi().list_repo_files(repo_id)
    ignore = list(SKIP)
    if any(name.endswith(".safetensors") for name in files):
        ignore += ["*.bin", "*.pt", "*.pth"]  # one copy of the weights is enough
    snapshot_download(repo_id, local_dir=local_path(repo_id), ignore_patterns=ignore)
    print(f"{repo_id}: ready in {local_path(repo_id)}")


def main() -> None:
    for repo_id in (EMBED_MODEL, RERANK_MODEL, LLM_MODEL):
        download(repo_id)


if __name__ == "__main__":
    main()
