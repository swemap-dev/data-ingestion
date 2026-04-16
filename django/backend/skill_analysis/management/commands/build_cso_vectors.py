import os

# Must be set before any library loads libomp (torch and faiss-cpu both link it on macOS)
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from django.conf import settings  # noqa: E402
from django.core.management.base import BaseCommand  # noqa: E402

from skill_analysis.services.cso_graph_builder import CSOGraphBuilder  # noqa: E402
from skill_analysis.services.cso_vectorizer import CSOVectorizer  # noqa: E402


class Command(BaseCommand):
    help = 'Vectorize CSO graph labels with GraphCodeBERT and build FAISS index.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--graph-path', type=str, default=None,
            help='Path to serialized CSO graph (default: settings.CSO_GRAPH_ARTIFACT_PATH)',
        )
        parser.add_argument(
            '--output-dir', type=str, default=None,
            help='Directory for output artifacts (default: settings.CSO_VECTOR_ARTIFACT_DIR)',
        )
        parser.add_argument(
            '--batch-size', type=int, default=64,
            help='Batch size for GraphCodeBERT inference (default: 64)',
        )
        parser.add_argument(
            '--skip-sanity', action='store_true',
            help='Skip sanity checks after building the index',
        )

    def handle(self, *args, **options):
        graph_path = options['graph_path'] or settings.CSO_GRAPH_ARTIFACT_PATH
        output_dir = options['output_dir'] or settings.CSO_VECTOR_ARTIFACT_DIR
        batch_size = options['batch_size']

        self.stdout.write(f"Loading CSO graph from {graph_path}")
        builder = CSOGraphBuilder.load(graph_path)
        labels = builder.get_vectorization_list()
        uris = builder.get_vectorization_uris()
        self.stdout.write(f"Loaded {len(labels)} labels for vectorization")

        vectorizer = CSOVectorizer(labels, uris, batch_size=batch_size)
        index, uris = vectorizer.build()

        index_path = settings.CSO_VECTOR_INDEX_PATH
        mapping_path = settings.CSO_VECTOR_MAPPING_PATH

        CSOVectorizer.save(index, uris, index_path, mapping_path)
        self.stdout.write(f"Dimension: {index.d}")
        self.stdout.write(f"Total vectors: {index.ntotal}")

        if not options['skip_sanity']:
            self.stdout.write("Running sanity checks...")
            CSOVectorizer.sanity_check(index, uris, labels)
            self.stdout.write(self.style.SUCCESS("All sanity checks passed"))

            query = 'copmutation with CUDA and GPU acceleration'
            self.stdout.write(f"\nQuery test: top-5 closest topics to '{query}':")
            results = CSOVectorizer.query(query, index, uris, k=5)
            for uri, score in results:
                self.stdout.write(f"  {uri.split('/')[-1]} (score={score:.4f})")

        self.stdout.write(self.style.SUCCESS("Vectorization complete"))
