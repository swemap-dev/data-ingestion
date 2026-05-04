import logging
import os
import re
from collections import defaultdict

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np

# torch MUST be imported before faiss to avoid libomp segfault on macOS
import torch  # noqa: F401

import faiss
import tree_sitter_python
from tree_sitter import Language, Node, Parser

# FAISS + torch both link libomp on macOS; running FAISS multi-threaded here
# can deadlock in __kmp_join_barrier. Force single-threaded search.
faiss.omp_set_num_threads(1)

from skill_analysis.services.embedding import get_encoder
from git_blame_ingestion_app.models import FileOwnershipMetric

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tree_sitter_python.language())


class CodeSkillMatcher:
    """
    Parses Python source into AST blocks, linearizes them into augmented
    S-expressions, embeds with GraphCodeBERT, and queries a FAISS index
    for top-K matching skills.
    """

    def __init__(self, index: faiss.Index, mapping: list[str]):
        self._index = index
        self._mapping = mapping

    # ── AST Parsing ─────────────────────────────────────────────

    @staticmethod
    def get_code_blocks(source_code: str) -> list[tuple[Node, str | None]]:
        """
        Extract function-level blocks from source. Classes are decomposed into
        their methods so each method is embedded individually (avoids 512-token
        truncation on large classes).

        Returns a list of (node, parent_class_name) tuples, where
        parent_class_name is None for top-level functions.
        """
        parser = Parser(PY_LANGUAGE)
        tree = parser.parse(source_code.encode("utf-8"))
        root = tree.root_node

        blocks: list[tuple[Node, str | None]] = []
        for child in root.children:
            target = CodeSkillMatcher._unwrap_decorator(child)
            if target is None:
                continue
            if target.type == "function_definition":
                blocks.append((target, None))
            elif target.type == "class_definition":
                class_name = CodeSkillMatcher.get_block_name(target)
                for method in CodeSkillMatcher._extract_class_methods(target):
                    blocks.append((method, class_name))

        return blocks

    @staticmethod
    def _unwrap_decorator(node: Node) -> Node | None:
        """Return the underlying def/class node, unwrapping decorators if present."""
        if node.type in ("function_definition", "class_definition"):
            return node
        if node.type == "decorated_definition":
            for sub in node.children:
                if sub.type in ("function_definition", "class_definition"):
                    return sub
        return None

    @staticmethod
    def _extract_class_methods(class_node: Node) -> list[Node]:
        """Yield function_definition nodes from a class body (handles decorators)."""
        methods: list[Node] = []
        body = class_node.child_by_field_name("body")
        if body is None:
            return methods
        for child in body.children:
            target = CodeSkillMatcher._unwrap_decorator(child)
            if target is not None and target.type == "function_definition":
                methods.append(target)
        return methods

    @staticmethod
    def get_block_name(node: Node) -> str:
        """Extract the name identifier from a function/class definition node."""
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return name_node.text.decode("utf-8")
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8")
        return "<anonymous>"

    # ── Code Extraction ─────────────────────────────────────────

    @staticmethod
    def _find_leading_docstring(node: Node) -> Node | None:
        """Return the leading docstring expression_statement node if present."""
        body = node.child_by_field_name("body")
        if body is None:
            return None
        for child in body.children:
            if not child.is_named:
                continue
            if child.type == "expression_statement" and child.child_count > 0:
                first = child.children[0]
                if first.type == "string":
                    return child
            return None
        return None

    @staticmethod
    def extract_code(node: Node, strip_docstring: bool = True) -> str:
        """Return raw source for node, optionally with its leading docstring removed."""
        text = node.text.decode("utf-8")
        if not strip_docstring:
            return text
        doc = CodeSkillMatcher._find_leading_docstring(node)
        if doc is None:
            return text
        rel_start = doc.start_byte - node.start_byte
        rel_end = doc.end_byte - node.start_byte
        stripped = text[:rel_start] + text[rel_end:]
        # Collapse consecutive blank lines left by docstring removal
        return re.sub(r'\n\s*\n+', '\n', stripped)

    # ── AST Linearization ───────────────────────────────────────

    @staticmethod
    def linearize(node: Node) -> str:
        """
        Convert an AST node into an augmented S-expression.

        Leaf nodes (identifier, string, integer, float) include their text value.
        Non-leaf named nodes include only their type.
        Anonymous nodes (brackets, colons, etc.) are skipped.
        """

        def _walk(n: Node) -> str:
            if not n.is_named:
                return ""

            if n.child_count == 0:
                # Leaf node — include text value
                text = n.text.decode("utf-8")
                return f"({n.type} {text})"

            # Non-leaf — recurse into children
            child_parts = []
            for child in n.children:
                part = _walk(child)
                if part:
                    child_parts.append(part)

            inner = " ".join(child_parts)
            return f"({n.type} {inner})"

        return _walk(node)

    # ── Embedding & Matching ────────────────────────────────────

    def match_file(
        self,
        source_code: str,
        k: int = 5,
        mode: str = "raw",
        strip_docstrings: bool = True,
    ) -> list[dict]:
        """
        Match each function/method block in source_code to top-K skills.

        mode: "raw" (default — embeds raw code) or "sexpr" (linearized AST)
        strip_docstrings: if True and mode="raw", removes leading docstrings

        Returns a list of dicts:
            {"block_name": str, "block_type": "function"|"method",
             "skills": [(uri, score), ...]}
        """
        blocks = self.get_code_blocks(source_code)
        if not blocks:
            logger.warning("No function/method blocks found in source code")
            return []

        if mode == "raw":
            texts = [self.extract_code(node, strip_docstring=strip_docstrings) for node, _ in blocks]
        elif mode == "sexpr":
            texts = [self.linearize(node) for node, _ in blocks]
        else:
            raise ValueError(f"Unknown mode: {mode!r} (expected 'raw' or 'sexpr')")

        encoder = get_encoder()
        embeddings = encoder.encode(texts, max_length=2048, batch_size=8)

        scores_arr, indices_arr = self._index.search(embeddings, k)

        results = []
        for i, (node, parent_class) in enumerate(blocks):
            name = self.get_block_name(node)
            if parent_class is not None:
                block_name = f"{parent_class}.{name}"
                block_type = "method"
            else:
                block_name = name
                block_type = "function"
            skills = [
                (self._mapping[idx], float(score))
                for score, idx in zip(scores_arr[i], indices_arr[i])
                if idx >= 0
            ]
            results.append({
                "block_name": block_name,
                "block_type": block_type,
                "skills": skills,
            })

        logger.info("Matched %d blocks to skills", len(results))
        return results

    @staticmethod
    def aggregate(
        per_block: list[dict],
        k: int = 5,
        pool: str = "max",
    ) -> list[tuple[str, float]]:
        """
        File-level skill summary from per-block results.

        pool: "max" (default) or "mean"
        Returns deduplicated top-K (uri, score) tuples sorted by score desc.
        """
        if not per_block:
            return []

        skill_scores: dict[str, list[float]] = defaultdict(list)
        for block in per_block:
            for uri, score in block["skills"]:
                skill_scores[uri].append(score)

        if pool == "mean":
            aggregated = {uri: float(np.mean(scores)) for uri, scores in skill_scores.items()}
        else:
            aggregated = {uri: max(scores) for uri, scores in skill_scores.items()}

        ranked = sorted(aggregated.items(), key=lambda x: x[1], reverse=True)
        return ranked[:k]

# TODO: Get the files that the input engineer worked on; remove in prod
def get_engineer_files(engineer_id: int = 3414) -> list[str]:
    """Fetches file paths for an engineer in one database query."""
    paths = FileOwnershipMetric.objects.filter(
        engineer_id=engineer_id
    ).values_list('file__file_path', flat=True)
    return list(paths)
