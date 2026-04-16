import networkx as nx
from django.conf import settings

from skill_analysis.services.cso_graph_builder import CSOGraphBuilder

_builder: CSOGraphBuilder | None = None


def get_cso_builder() -> CSOGraphBuilder:
    global _builder
    if _builder is None:
        _builder = CSOGraphBuilder.load(settings.CSO_GRAPH_ARTIFACT_PATH)
    return _builder


def get_cso_graph() -> nx.MultiDiGraph:
    return get_cso_builder().graph


_vector_index = None
_vector_mapping: list[str] | None = None


def get_cso_vector_index():
    global _vector_index, _vector_mapping
    if _vector_index is None:
        import faiss  # noqa: F811 — deferred to avoid hard dependency at import time

        from skill_analysis.services.cso_vectorizer import CSOVectorizer
        _vector_index, _vector_mapping = CSOVectorizer.load(
            settings.CSO_VECTOR_INDEX_PATH,
            settings.CSO_VECTOR_MAPPING_PATH,
        )
    return _vector_index, _vector_mapping
