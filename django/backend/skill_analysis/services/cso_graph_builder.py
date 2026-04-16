import csv
import logging
import pickle
from pathlib import Path
from urllib.parse import unquote

import networkx as nx

from skill_analysis.services.skill_graph_builder import SkillGraphBuilder

logger = logging.getLogger(__name__)

EDGE_PREDICATES = {
    'superTopicOf': 'taxonomy',
    'contributesTo': 'contribution',
}


class CSOGraphBuilder(SkillGraphBuilder):
    """
    Builds an nx.MultiDiGraph from CSO RDF triples (URI-based, with synonyms).

    Extends SkillGraphBuilder with CSO-specific logic:
      - URI parsing (angle brackets, URL encoding)
      - Synonym collapse via relatedEquivalent + preferentialEquivalent
      - rdfs:label extraction
    """

    def __init__(self, csv_path: str | Path):
        super().__init__(csv_path, edge_predicates=EDGE_PREDICATES)
        self._synonym_map: dict[str, str] = {}
        self._labels: dict[str, str] = {}
        self._preferred: dict[str, str] = {}

    def build(self) -> nx.MultiDiGraph:
        triples = self._parse_csv()
        self._build_synonym_map(triples)
        self._inject_nodes(triples)
        self._inject_edges(triples)
        return self.graph

    # ── CSV Parsing (CSO-specific RDF format) ────────────────────

    def _parse_csv(self) -> list[tuple[str, str, str]]:
        triples: list[tuple[str, str, str]] = []
        with open(self._csv_path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) != 3:
                    continue
                raw_sub, raw_pred, raw_obj = row

                pred_suffix = self._extract_predicate_suffix(raw_pred)

                subject = self._extract_uri(raw_sub)

                if pred_suffix == 'label':
                    label = self._extract_label_literal(raw_obj)
                    self._labels[subject] = label
                elif pred_suffix == 'preferentialEquivalent':
                    self._preferred[subject] = self._extract_uri(raw_obj)

                obj = self._extract_uri(raw_obj) if pred_suffix != 'label' else ''
                triples.append((subject, pred_suffix, obj))

        logger.info("Parsed %d triples from %s", len(triples), self._csv_path.name)
        return triples

    @staticmethod
    def _extract_uri(raw: str) -> str:
        s = raw.strip().strip('"').strip('<').rstrip('>')
        return unquote(s)

    @staticmethod
    def _extract_predicate_suffix(raw: str) -> str:
        uri = raw.strip().strip('"').strip('<').rstrip('>')
        for sep in ('#', '/'):
            if sep in uri:
                return uri.rsplit(sep, 1)[-1]
        return uri

    @staticmethod
    def _extract_label_literal(raw: str) -> str:
        s = raw.strip().strip('"')
        if '@' in s:
            s = s[:s.rfind('@')].strip().strip('"')
        return s

    @staticmethod
    def _label_from_uri(uri: str) -> str:
        segment = uri.rsplit('/', 1)[-1]
        return segment.replace('_', ' ')

    # ── Phase A: Canonical Mapping ───────────────────────────────

    def _build_synonym_map(self, triples: list[tuple[str, str, str]]) -> None:
        equiv_graph = nx.Graph()
        for sub, pred, obj in triples:
            if pred == 'relatedEquivalent':
                equiv_graph.add_edge(sub, obj)

        for component in nx.connected_components(equiv_graph):
            canonical = self._pick_canonical(component)
            for uri in component:
                self._synonym_map[uri] = canonical

        logger.info(
            "Synonym map: %d URIs collapsed into %d canonical groups",
            len(self._synonym_map),
            len(set(self._synonym_map.values())),
        )

    def _pick_canonical(self, component: set[str]) -> str:
        for uri in component:
            target = self._preferred.get(uri)
            if target and target in component:
                return target
        return min(component, key=len)

    def _canonicalize(self, uri: str) -> str:
        return self._synonym_map.get(uri, uri)

    # ── Phase B: Node Injection (with synonym resolution) ────────

    def _inject_nodes(self, triples: list[tuple[str, str, str]]) -> None:
        canonical_uris: set[str] = set()
        for sub, pred, obj in triples:
            if pred in self._edge_predicates:
                canonical_uris.add(self._canonicalize(sub))
                canonical_uris.add(self._canonicalize(obj))

        sorted_uris = sorted(canonical_uris)
        for idx, uri in enumerate(sorted_uris):
            label = self._resolve_label(uri)
            self.graph.add_node(uri, label=label, vector_index=idx)

        logger.info("Injected %d nodes", self.graph.number_of_nodes())

    def _resolve_label(self, canonical_uri: str) -> str:
        if canonical_uri in self._labels:
            return self._labels[canonical_uri]
        for uri, canon in self._synonym_map.items():
            if canon == canonical_uri and uri in self._labels:
                return self._labels[uri]
        return self._label_from_uri(canonical_uri)

    # ── Phase C: Edge Injection (with synonym resolution) ────────

    def _inject_edges(self, triples: list[tuple[str, str, str]]) -> None:
        seen: set[tuple[str, str, str]] = set()
        skipped_self_loops = 0
        skipped_duplicates = 0
        for sub, pred, obj in triples:
            rel_type = self._edge_predicates.get(pred)
            if rel_type is None:
                continue
            s = self._canonicalize(sub)
            o = self._canonicalize(obj)
            if s == o:
                skipped_self_loops += 1
                continue
            key = (s, o, rel_type)
            if key in seen:
                skipped_duplicates += 1
                continue
            seen.add(key)
            self.graph.add_edge(s, o, rel_type=rel_type)

        logger.info(
            "Injected %d edges (%d self-loops skipped, %d duplicates skipped)",
            self.graph.number_of_edges(),
            skipped_self_loops,
            skipped_duplicates,
        )

    # ── Persistence ──────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump({'graph': self.graph, 'synonym_map': self._synonym_map}, f, protocol=5)
        logger.info("Graph saved to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> 'CSOGraphBuilder':
        with open(path, 'rb') as f:
            data = pickle.load(f)
        builder = cls.__new__(cls)
        builder.graph = data['graph']
        builder._synonym_map = data.get('synonym_map', {})
        return builder
