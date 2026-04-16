import csv
import logging
import pickle
from pathlib import Path

import networkx as nx

logger = logging.getLogger(__name__)

# Maps predicate names to edge rel_type values
DEFAULT_EDGE_PREDICATES = {
    'superTopicOf': 'taxonomy',
    'contributesTo': 'contribution',
}


class SkillGraphBuilder:
    """
    Builds an nx.MultiDiGraph from a CSV of (source, relationship, target) triples.

    Handles the general case where node IDs are plain-text labels.
    For RDF/URI-based datasets (e.g., CSO), use CSOGraphBuilder instead.
    """

    def __init__(
        self,
        csv_path: str | Path,
        edge_predicates: dict[str, str] | None = None,
    ):
        self._csv_path = Path(csv_path)
        self._edge_predicates = edge_predicates or DEFAULT_EDGE_PREDICATES
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()

    def build(self) -> nx.MultiDiGraph:
        triples = self._parse_csv()
        self._inject_nodes(triples)
        self._inject_edges(triples)
        return self.graph

    # ── CSV Parsing ──────────────────────────────────────────────

    def _parse_csv(self) -> list[tuple[str, str, str]]:
        triples: list[tuple[str, str, str]] = []
        with open(self._csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                source = row['source'].strip()
                relationship = row['relationship'].strip()
                target = row['target'].strip()
                triples.append((source, relationship, target))

        logger.info("Parsed %d triples from %s", len(triples), self._csv_path.name)
        return triples

    # ── Node Injection ───────────────────────────────────────────

    def _inject_nodes(self, triples: list[tuple[str, str, str]]) -> None:
        node_ids: set[str] = set()
        for source, rel, target in triples:
            if rel in self._edge_predicates:
                node_ids.add(source)
                node_ids.add(target)

        for idx, node_id in enumerate(sorted(node_ids)):
            self.graph.add_node(node_id, label=node_id, vector_index=idx)

        logger.info("Injected %d nodes", self.graph.number_of_nodes())

    # ── Edge Injection ───────────────────────────────────────────

    def _inject_edges(self, triples: list[tuple[str, str, str]]) -> None:
        seen: set[tuple[str, str, str]] = set()
        for source, rel, target in triples:
            rel_type = self._edge_predicates.get(rel)
            if rel_type is None:
                continue
            if source == target:
                continue
            key = (source, target, rel_type)
            if key in seen:
                continue
            seen.add(key)
            self.graph.add_edge(source, target, rel_type=rel_type)

        logger.info("Injected %d edges", self.graph.number_of_edges())

    # ── Public API ───────────────────────────────────────────────

    def get_vectorization_list(self) -> list[str]:
        nodes = sorted(self.graph.nodes(data=True), key=lambda x: x[1]['vector_index'])
        return [data['label'] for _, data in nodes]

    def get_vectorization_uris(self) -> list[str]:
        nodes = sorted(self.graph.nodes(data=True), key=lambda x: x[1]['vector_index'])
        return [node_id for node_id, _data in nodes]

    # ── Persistence ──────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump({'graph': self.graph}, f, protocol=5)
        logger.info("Graph saved to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> 'SkillGraphBuilder':
        with open(path, 'rb') as f:
            data = pickle.load(f)
        builder = cls.__new__(cls)
        builder.graph = data['graph']
        return builder
