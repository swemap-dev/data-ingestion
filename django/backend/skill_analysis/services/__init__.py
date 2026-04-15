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
