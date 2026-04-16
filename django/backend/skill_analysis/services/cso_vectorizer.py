import gc
import json
import logging
import math
import os
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# torch MUST be imported before faiss to avoid libomp segfault on macOS
import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

import faiss

logger = logging.getLogger(__name__)

MODEL_NAME = "microsoft/graphcodebert-base"
MAX_LENGTH = 64
BATCH_SIZE = 64
EMBEDDING_DIM = 768


def _normalize_l2(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize rows in-place using numpy (avoids faiss.normalize_L2 crash on some platforms)."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    vectors /= norms
    return vectors


class CSOVectorizer:
    """Embeds CSO node labels with GraphCodeBERT and builds a FAISS index."""

    def __init__(self, labels: list[str], uris: list[str], batch_size: int = BATCH_SIZE):
        assert len(labels) == len(uris), "labels and uris must have the same length"
        self._labels = labels
        self._uris = uris
        self._batch_size = batch_size

    def build(self) -> tuple[faiss.Index, list[str]]:
        embeddings = self._embed_all()
        _normalize_l2(embeddings)
        index = faiss.IndexFlatIP(EMBEDDING_DIM)
        index.add(embeddings)
        logger.info("FAISS index built: d=%d, ntotal=%d", index.d, index.ntotal)
        return index, self._uris

    def _embed_all(self) -> np.ndarray:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info("Loading model %s on %s", MODEL_NAME, device)

        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModel.from_pretrained(MODEL_NAME).to(device)
        model.eval()

        n = len(self._labels)
        embeddings = np.zeros((n, EMBEDDING_DIM), dtype=np.float32)
        total_batches = math.ceil(n / self._batch_size)

        for i in range(0, n, self._batch_size):
            batch = self._labels[i : i + self._batch_size]
            inputs = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            ).to(device)

            with torch.no_grad():
                outputs = model(**inputs)
                cls_embeddings = outputs.last_hidden_state[:, 0, :].cpu().numpy()
                embeddings[i : i + len(batch)] = cls_embeddings

            batch_num = i // self._batch_size + 1
            if batch_num % 10 == 0 or batch_num == total_batches:
                logger.info("Embedded batch %d/%d", batch_num, total_batches)

        # Free model memory before building FAISS index
        del model, tokenizer
        gc.collect()

        return embeddings

    @staticmethod
    def save(
        index: faiss.Index,
        uris: list[str],
        index_path: str | Path,
        mapping_path: str | Path,
    ) -> None:
        index_path = Path(index_path)
        mapping_path = Path(mapping_path)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(index_path))
        with open(mapping_path, 'w') as f:
            json.dump(uris, f)
        logger.info("Saved FAISS index to %s and mapping to %s", index_path, mapping_path)

    @staticmethod
    def load(
        index_path: str | Path,
        mapping_path: str | Path,
    ) -> tuple[faiss.Index, list[str]]:
        index = faiss.read_index(str(index_path))
        with open(mapping_path) as f:
            uris = json.load(f)
        return index, uris

    @staticmethod
    def query(
        query_text: str,
        index: faiss.Index,
        uris: list[str],
        k: int = 3,
    ) -> list[tuple[str, float]]:
        """Query the FAISS index with arbitrary text. Returns list of (uri, score) tuples."""
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModel.from_pretrained(MODEL_NAME)
        model.eval()

        inputs = tokenizer(
            [query_text],
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )
        with torch.no_grad():
            vec = model(**inputs).last_hidden_state[:, 0, :].numpy().astype(np.float32)
        _normalize_l2(vec)

        scores, result_indices = index.search(vec, k)

        del model, tokenizer
        gc.collect()

        return [(uris[idx], float(score)) for score, idx in zip(scores[0], result_indices[0])]

    @staticmethod
    def sanity_check(
        index: faiss.Index,
        uris: list[str],
        labels: list[str],
    ) -> None:
        assert index.d == EMBEDDING_DIM, f"Expected d={EMBEDDING_DIM}, got d={index.d}"
        assert index.ntotal == len(uris), (
            f"index.ntotal={index.ntotal} != len(uris)={len(uris)}"
        )

        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModel.from_pretrained(MODEL_NAME)
        model.eval()

        # Self-consistency: pick 3 labels, each should return itself as top-1
        test_indices = [0, len(labels) // 2, len(labels) - 1]
        for idx in test_indices:
            label = labels[idx]
            inputs = tokenizer(
                [label],
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            )
            with torch.no_grad():
                vec = model(**inputs).last_hidden_state[:, 0, :].numpy().astype(np.float32)
            _normalize_l2(vec)
            scores, result_indices = index.search(vec, 1)
            top_score = scores[0][0]
            top_idx = result_indices[0][0]
            top_uri = uris[top_idx]
            expected_uri = uris[idx]
            logger.info(
                "Self-check: '%s' -> top-1=%s, score=%.4f, match=%s",
                label,
                top_uri.split('/')[-1],
                top_score,
                top_uri == expected_uri,
            )
            assert top_uri == expected_uri, (
                f"Self-query failed for '{label}': expected {expected_uri}, got {top_uri}"
            )
            assert top_score > 0.99, (
                f"Self-query score too low for '{label}': {top_score}"
            )

        # Query test: find top-3 closest topics to "asyncio"
        query_text = "asyncio"
        inputs = tokenizer(
            [query_text],
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )
        with torch.no_grad():
            vec = model(**inputs).last_hidden_state[:, 0, :].numpy().astype(np.float32)
        _normalize_l2(vec)
        scores, result_indices = index.search(vec, 3)
        logger.info("Query test: '%s' -> top-3 results:", query_text)
        for score, idx in zip(scores[0], result_indices[0]):
            logger.info("  %s (score=%.4f)", uris[idx].split('/')[-1], score)

        del model, tokenizer
        gc.collect()
        logger.info("All sanity checks passed")
