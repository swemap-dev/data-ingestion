import gc
import logging
import math
import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# torch MUST be imported before faiss to avoid libomp segfault on macOS
import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

logger = logging.getLogger(__name__)

MODEL_NAME = "jinaai/jina-embeddings-v2-base-code"
EMBEDDING_DIM = 768
MAX_MODEL_LENGTH = 8192


def _normalize_l2(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize rows in-place."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    vectors /= norms
    return vectors


def _mean_pool(last_hidden: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Mean pool token embeddings using the attention mask (Jina v2 convention)."""
    mask = attention_mask.unsqueeze(-1).expand(last_hidden.size()).float()
    summed = torch.sum(last_hidden * mask, dim=1)
    counts = torch.clamp(mask.sum(dim=1), min=1e-9)
    return summed / counts


class CodeEncoder:
    """Lazy-loaded, reusable code embedding encoder (jina-embeddings-v2-base-code)."""

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._device = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info("Loading %s on %s", MODEL_NAME, self._device)
        self._tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
        self._model = AutoModel.from_pretrained(MODEL_NAME, trust_remote_code=True).to(self._device)
        self._model.eval()

    def encode(
        self,
        texts: list[str],
        max_length: int = 2048,
        batch_size: int = 8,
        normalize: bool = True,
    ) -> np.ndarray:
        """Embed a list of texts, return (N, 768) float32 array."""
        self._ensure_loaded()

        n = len(texts)
        embeddings = np.zeros((n, EMBEDDING_DIM), dtype=np.float32)
        total_batches = math.ceil(n / batch_size)

        for i in range(0, n, batch_size):
            batch = texts[i : i + batch_size]
            inputs = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            ).to(self._device)

            with torch.no_grad():
                outputs = self._model(**inputs)
                pooled = _mean_pool(outputs.last_hidden_state, inputs["attention_mask"])
                embeddings[i : i + len(batch)] = pooled.cpu().numpy()

            batch_num = i // batch_size + 1
            if batch_num % 10 == 0 or batch_num == total_batches:
                logger.info("Encoded batch %d/%d", batch_num, total_batches)

        if normalize:
            _normalize_l2(embeddings)

        return embeddings

    def encode_single(self, text: str, max_length: int = 2048) -> np.ndarray:
        """Embed a single text, return L2-normalized (1, 768) float32 array."""
        return self.encode([text], max_length=max_length, batch_size=1)

    def unload(self):
        """Free model memory."""
        del self._model, self._tokenizer
        self._model = None
        self._tokenizer = None
        self._device = None
        gc.collect()


_encoder: CodeEncoder | None = None


def get_encoder() -> CodeEncoder:
    global _encoder
    if _encoder is None:
        _encoder = CodeEncoder()
    return _encoder
