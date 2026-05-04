import json
import logging
import os
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# torch MUST be imported before faiss to avoid libomp segfault on macOS.
# Importing embedding first ensures torch is loaded before faiss.
from skill_analysis.services.embedding import EMBEDDING_DIM, get_encoder

import faiss

# FAISS + torch both link libomp on macOS; multi-threaded FAISS calls can
# deadlock in __kmp_join_barrier after torch initializes its own OMP runtime.
faiss.omp_set_num_threads(1)

logger = logging.getLogger(__name__)

MAX_LENGTH = 64
BATCH_SIZE = 64


class CSOVectorizer:
    """Embeds CSO node labels with GraphCodeBERT and builds a FAISS index."""

    def __init__(self, labels: list[str], uris: list[str], batch_size: int = BATCH_SIZE):
        assert len(labels) == len(uris), "labels and uris must have the same length"
        self._labels = labels
        self._uris = uris
        self._batch_size = batch_size

    def build(self) -> tuple[faiss.Index, list[str]]:
        encoder = get_encoder()
        embeddings = encoder.encode(
            self._labels,
            max_length=MAX_LENGTH,
            batch_size=self._batch_size,
            normalize=True,
        )
        index = faiss.IndexFlatIP(EMBEDDING_DIM)
        index.add(embeddings)
        logger.info("FAISS index built: d=%d, ntotal=%d", index.d, index.ntotal)
        return index, self._uris

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
        encoder = get_encoder()
        vec = encoder.encode_single(query_text, max_length=MAX_LENGTH)
        scores, result_indices = index.search(vec, k)
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

        encoder = get_encoder()

        # Self-consistency: pick 3 labels, each should return itself as top-1
        test_indices = [0, len(labels) // 2, len(labels) - 1]
        for idx in test_indices:
            label = labels[idx]
            vec = encoder.encode_single(label, max_length=MAX_LENGTH)
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
        vec = encoder.encode_single(query_text, max_length=MAX_LENGTH)
        scores, result_indices = index.search(vec, 3)
        logger.info("Query test: '%s' -> top-3 results:", query_text)
        for score, idx in zip(scores[0], result_indices[0]):
            logger.info("  %s (score=%.4f)", uris[idx].split('/')[-1], score)

        logger.info("All sanity checks passed")
