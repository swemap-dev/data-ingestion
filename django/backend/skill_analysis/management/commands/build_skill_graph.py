from importlib import import_module

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Build a skill graph from a registered dataset CSV and serialize to disk.'

    def add_arguments(self, parser):
        parser.add_argument(
            'dataset',
            type=str,
            help=f'Dataset name (choices: {", ".join(settings.SKILL_DATASETS.keys())})',
        )

    def handle(self, *args, **options):
        name = options['dataset']
        config = settings.SKILL_DATASETS.get(name)
        if config is None:
            raise CommandError(
                f"Unknown dataset '{name}'. "
                f"Available: {', '.join(settings.SKILL_DATASETS.keys())}"
            )

        csv_path = config['csv_path']
        graph_path = config['graph_path']

        # Import the builder class from the dotted path
        module_path, class_name = config['builder'].rsplit('.', 1)
        module = import_module(module_path)
        BuilderClass = getattr(module, class_name)

        self.stdout.write(f"Building '{name}' graph from {csv_path}")
        builder = BuilderClass(csv_path)
        graph = builder.build()

        self.stdout.write(f"Nodes: {graph.number_of_nodes()}")
        self.stdout.write(f"Edges: {graph.number_of_edges()}")

        vec_list = builder.get_vectorization_list()
        self.stdout.write(f"Vectorization list size: {len(vec_list)}")
        self.stdout.write(f"Sample labels: {vec_list[:5]}")

        builder.save(graph_path)
        self.stdout.write(self.style.SUCCESS(f"Graph saved to {graph_path}"))
