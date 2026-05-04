import csv
import logging
from pathlib import Path

import networkx as nx

from skill_analysis.services.skill_graph_builder import SkillGraphBuilder

logger = logging.getLogger(__name__)

NODE_KIND_DOMAIN = 'domain'
NODE_KIND_CONCEPT = 'concept'
NODE_KIND_LIBRARY = 'library'


class SWEAnchorGraphBuilder(SkillGraphBuilder):
    """
    Builds a 3-level skill graph from the SWE concept anchor CSV:
        domain --taxonomy--> concept --taxonomy--> library

    Concept nodes carry a `description` attribute, and get_vectorization_list()
    emits '{label}: {description}' for concepts so the embedder gets richer
    semantic signal than a bare label. Domain and library nodes keep bare labels.
    """

    def __init__(self, csv_path: str | Path):
        self._csv_path = Path(csv_path)
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()

    def build(self) -> nx.MultiDiGraph:
        rows = self._parse_csv()
        self._inject(rows)
        return self.graph

    def _parse_csv(self) -> list[dict]:
        rows: list[dict] = []
        with open(self._csv_path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                libs = [lib.strip() for lib in row['anchor_libraries'].split(';') if lib.strip()]
                rows.append({
                    'domain': row['domain'].strip(),
                    'concept': row['concept'].strip(),
                    'description': row['description'].strip(),
                    'libraries': libs,
                })
        logger.info("Parsed %d anchor rows from %s", len(rows), self._csv_path.name)
        return rows

    def _inject(self, rows: list[dict]) -> None:
        domains: set[str] = set()
        concept_descriptions: dict[str, str] = {}
        libraries: set[str] = set()

        for row in rows:
            domains.add(row['domain'])
            concept_descriptions[row['concept']] = row['description']
            libraries.update(row['libraries'])

        ordered: list[tuple[str, dict]] = []
        for d in sorted(domains):
            ordered.append((d, {'label': d, 'kind': NODE_KIND_DOMAIN}))
        for c in sorted(concept_descriptions):
            ordered.append((c, {
                'label': c,
                'kind': NODE_KIND_CONCEPT,
                'description': concept_descriptions[c],
            }))
        for lib in sorted(libraries):
            ordered.append((lib, {'label': lib, 'kind': NODE_KIND_LIBRARY}))

        for idx, (node_id, attrs) in enumerate(ordered):
            self.graph.add_node(node_id, vector_index=idx, **attrs)

        seen: set[tuple[str, str]] = set()
        for row in rows:
            d, c = row['domain'], row['concept']
            if (d, c) not in seen:
                self.graph.add_edge(d, c, rel_type='taxonomy')
                seen.add((d, c))
            for lib in row['libraries']:
                if (c, lib) not in seen:
                    self.graph.add_edge(c, lib, rel_type='taxonomy')
                    seen.add((c, lib))

        logger.info(
            "Injected %d nodes (%d domains, %d concepts, %d libraries), %d edges",
            self.graph.number_of_nodes(),
            len(domains),
            len(concept_descriptions),
            len(libraries),
            self.graph.number_of_edges(),
        )

    def get_vectorization_list(self) -> list[str]:
        nodes = sorted(self.graph.nodes(data=True), key=lambda x: x[1]['vector_index'])
        texts: list[str] = []
        for _, data in nodes:
            if data.get('kind') == NODE_KIND_CONCEPT and data.get('description'):
                texts.append(f"{data['label']}: {data['description']}")
            else:
                texts.append(data['label'])
        return texts
