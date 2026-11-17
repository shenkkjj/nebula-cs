"""chromadb imports for the campus vector index.

This module is imported only when a vector is stored or queried. Importing
chromadb maps onnxruntime and grpc. The lexical campus path, and LITE_MODE,
do not import it.

The default ONNX MiniLM embedder is not constructed. Callers pass vectors
from the remote embedding API. Do not turn that local model on for a 2 GiB host.
"""
from __future__ import annotations

import logging
import os

# Chroma reads this while importing its telemetry client.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.config import Settings
from chromadb.errors import NotFoundError
from chromadb.utils.embedding_functions import register_embedding_function

logging.getLogger("chromadb").setLevel(logging.WARNING)

__all__ = ["NotFoundError", "RemoteOnlyEmbedding", "Settings", "chromadb"]


@register_embedding_function
class RemoteOnlyEmbedding(EmbeddingFunction[Documents]):
    """Marker so Chroma does not attach its built-in ONNX embedder.

    ``__call__`` is never used. ``kb_retrieve`` computes vectors remotely
    and passes them in.
    """

    def __init__(self) -> None:
        return

    def __call__(self, input: Documents) -> Embeddings:
        raise RuntimeError("向量由远程接口计算后写入，不在本机跑嵌入模型。")

    @staticmethod
    def name() -> str:
        return "nebula_remote_only"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "RemoteOnlyEmbedding":
        return RemoteOnlyEmbedding()

    def default_space(self) -> str:
        return "cosine"

    @staticmethod
    def validate_config(config: dict) -> None:
        return
