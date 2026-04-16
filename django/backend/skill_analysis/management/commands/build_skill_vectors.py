import os
from importlib import import_module

# Must be set before any library loads libomp (torch and faiss-cpu both link it on macOS)
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from django.conf import settings  # noqa: E402
from django.core.management.base import BaseCommand, CommandError  # noqa: E402

from skill_analysis.services.cso_vectorizer import CSOVectorizer  # noqa: E402


class Command(BaseCommand):
    help = 'Vectorize a skill graph with GraphCodeBERT and build FAISS index.'

    def add_arguments(self, parser):
        parser.add_argument(
            'dataset',
            type=str,
            help=f'Dataset name (choices: {", ".join(settings.SKILL_DATASETS.keys())})',
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
        name = options['dataset']
        config = settings.SKILL_DATASETS.get(name)
        if config is None:
            raise CommandError(
                f"Unknown dataset '{name}'. "
                f"Available: {', '.join(settings.SKILL_DATASETS.keys())}"
            )

        graph_path = config['graph_path']
        index_path = config['index_path']
        mapping_path = config['mapping_path']
        batch_size = options['batch_size']

        # Load graph using the dataset's builder class
        module_path, class_name = config['builder'].rsplit('.', 1)
        module = import_module(module_path)
        BuilderClass = getattr(module, class_name)

        self.stdout.write(f"Loading '{name}' graph from {graph_path}")
        builder = BuilderClass.load(graph_path)
        labels = builder.get_vectorization_list()
        uris = builder.get_vectorization_uris()
        self.stdout.write(f"Loaded {len(labels)} labels for vectorization")

        vectorizer = CSOVectorizer(labels, uris, batch_size=batch_size)
        index, uris = vectorizer.build()

        CSOVectorizer.save(index, uris, index_path, mapping_path)
        self.stdout.write(f"Dimension: {index.d}")
        self.stdout.write(f"Total vectors: {index.ntotal}")

        if not options['skip_sanity']:
            self.stdout.write("Running sanity checks...")
            CSOVectorizer.sanity_check(index, uris, labels)
            self.stdout.write(self.style.SUCCESS("All sanity checks passed"))

        self.stdout.write(self.style.SUCCESS(f"'{name}' vectorization complete"))
