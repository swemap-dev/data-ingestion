from django.conf import settings
from django.core.management.base import BaseCommand

from skill_analysis.services.cso_graph_builder import CSOGraphBuilder


class Command(BaseCommand):
    help = 'Build the CSO ontology graph from CSV and serialize to disk.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv-path', type=str, default=None,
            help='Path to CSO CSV file (default: settings.CSO_CSV_PATH)',
        )
        parser.add_argument(
            '--output', type=str, default=None,
            help='Output path for serialized graph (default: settings.CSO_GRAPH_ARTIFACT_PATH)',
        )

    def handle(self, *args, **options):
        csv_path = options['csv_path'] or settings.CSO_CSV_PATH
        output = options['output'] or settings.CSO_GRAPH_ARTIFACT_PATH

        builder = CSOGraphBuilder(csv_path)
        graph = builder.build()

        self.stdout.write(f"Nodes: {graph.number_of_nodes()}")
        self.stdout.write(f"Edges: {graph.number_of_edges()}")

        vec_list = builder.get_vectorization_list()
        self.stdout.write(f"Vectorization list size: {len(vec_list)}")
        self.stdout.write(f"Sample labels: {vec_list[:5]}")

        builder.save(output)
        self.stdout.write(self.style.SUCCESS(f"Graph saved to {output}"))
