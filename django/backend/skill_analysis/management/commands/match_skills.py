import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from django.conf import settings  # noqa: E402
from django.core.management.base import BaseCommand, CommandError  # noqa: E402

from skill_analysis.services.code_skill_matcher import CodeSkillMatcher  # noqa: E402
from skill_analysis.services.cso_vectorizer import CSOVectorizer  # noqa: E402


class Command(BaseCommand):
    help = 'Match Python source code blocks to skills via FAISS vector search.'

    def add_arguments(self, parser):
        parser.add_argument(
            'file',
            type=str,
            help='Path to a Python source file to analyze',
        )
        parser.add_argument(
            '--dataset',
            type=str,
            default='conda',
            help=f'Dataset to match against (choices: {", ".join(settings.SKILL_DATASETS.keys())})',
        )
        parser.add_argument(
            '--k',
            type=int,
            default=5,
            help='Number of top-K skills to return per block (default: 5)',
        )
        parser.add_argument(
            '--show-linearized',
            action='store_true',
            help='Print the embedded text (raw code or S-expression) for each block',
        )
        parser.add_argument(
            '--mode',
            type=str,
            default='raw',
            choices=['raw', 'sexpr'],
            help='Embedding input: "raw" source code (default) or "sexpr" linearized AST',
        )
        parser.add_argument(
            '--keep-docstrings',
            action='store_true',
            help='Keep docstrings when mode=raw (default: strip them to save tokens)',
        )
        parser.add_argument(
            '--export-blocks',
            type=str,
            default=None,
            help='Export extracted blocks to a JSON file at the specified path',
        )

    def handle(self, *args, **options):
        file_path = options['file']
        dataset = options['dataset']
        k = options['k']

        config = settings.SKILL_DATASETS.get(dataset)
        if config is None:
            raise CommandError(
                f"Unknown dataset '{dataset}'. "
                f"Available: {', '.join(settings.SKILL_DATASETS.keys())}"
            )

        # Read source file
        try:
            with open(file_path, encoding='utf-8') as f:
                source_code = f.read()
        except FileNotFoundError:
            raise CommandError(f"File not found: {file_path}")

        # Load FAISS index
        index_path = config['index_path']
        mapping_path = config['mapping_path']
        self.stdout.write(f"Loading '{dataset}' vector index from {index_path}")
        index, mapping = CSOVectorizer.load(index_path, mapping_path)
        self.stdout.write(f"Index loaded: d={index.d}, ntotal={index.ntotal}")

        matcher = CodeSkillMatcher(index, mapping)

        # Extract and show blocks
        blocks = matcher.get_code_blocks(source_code)
        self.stdout.write(f"\nFound {len(blocks)} code blocks in {file_path}")

        export_path = options.get('export_blocks')
        if export_path:
            import json
            blocks_data = []
            for node, parent_class in blocks:
                name = matcher.get_block_name(node)
                display_name = f"{parent_class}.{name}" if parent_class else name
                block_type = "method" if parent_class else "function"
                blocks_data.append({
                    "name": display_name,
                    "type": block_type,
                    "code": node.text.decode('utf-8') if node.text else "",
                    "linearized": matcher.linearize(node)
                })
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(blocks_data, f, indent=2)
            self.stdout.write(self.style.SUCCESS(f"Exported blocks to {export_path}"))

        mode = options['mode']
        strip_docstrings = not options['keep_docstrings']

        # Probe actual token counts so we can tell if we're hitting the 512 cap
        from skill_analysis.services.embedding import get_encoder
        tokenizer = get_encoder()
        tokenizer._ensure_loaded()
        tok = tokenizer._tokenizer
        self.stdout.write("\n--- Token counts (cap=512) ---")
        for node, parent_class in blocks:
            name = matcher.get_block_name(node)
            display_name = f"{parent_class}.{name}" if parent_class else name
            if mode == "raw":
                t = matcher.extract_code(node, strip_docstring=strip_docstrings)
            else:
                t = matcher.linearize(node)
            n_tokens = len(tok(t, truncation=False)['input_ids'])
            flag = " [TRUNCATED]" if n_tokens > 512 else ""
            self.stdout.write(f"  {display_name}: {n_tokens} tokens{flag}")

        if options['show_linearized']:
            header = "Raw code" if mode == "raw" else "Linearized S-expressions"
            self.stdout.write(f"\n--- {header} ---")
            for node, parent_class in blocks:
                name = matcher.get_block_name(node)
                display_name = f"{parent_class}.{name}" if parent_class else name
                block_type = "method" if parent_class else "function"
                if mode == "raw":
                    text = matcher.extract_code(node, strip_docstring=strip_docstrings)
                else:
                    text = matcher.linearize(node)
                self.stdout.write(f"\n[{block_type}] {display_name} ({len(text)} chars):")
                self.stdout.write(text)

        # Per-block matching
        self.stdout.write(f"\n--- Per-block skill matches (top-{k}, mode={mode}) ---")
        results = matcher.match_file(
            source_code, k=k, mode=mode, strip_docstrings=strip_docstrings
        )
        for result in results:
            self.stdout.write(
                f"\n[{result['block_type']}] {result['block_name']}:"
            )
            for uri, score in result['skills']:
                label = uri.rsplit('/', 1)[-1] if '/' in uri else uri
                self.stdout.write(f"  {label:40s} (score={score:.4f})")

        # Aggregate file-level skills (reuse per-block results)
        self.stdout.write(f"\n--- File-level aggregate skills (top-{k}) ---")
        aggregate = CodeSkillMatcher.aggregate(results, k=k)
        for uri, score in aggregate:
            label = uri.rsplit('/', 1)[-1] if '/' in uri else uri
            self.stdout.write(f"  {label:40s} (score={score:.4f})")

        self.stdout.write(self.style.SUCCESS("\nDone."))
