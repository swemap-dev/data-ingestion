from django.core.management.base import BaseCommand

from performance_profiling.generators.synthetic_repo import (
    SyntheticRepoConfig,
    PRESET_SCALES,
)
from performance_profiling.runners.benchmark_runner import run_benchmark


class Command(BaseCommand):
    help = "Run performance benchmarks on the data ingestion pipeline"

    def add_arguments(self, parser):
        parser.add_argument(
            "--scale",
            type=str,
            choices=["small", "medium", "large", "stress"],
            default=None,
            help="Preset scale: small (500 files), medium (5k), large (20k), stress (50k)",
        )
        parser.add_argument("--files", type=int, default=None, help="Custom file count")
        parser.add_argument("--prs", type=int, default=None, help="Custom PR count")
        parser.add_argument("--engineers", type=int, default=None, help="Custom engineer count")
        parser.add_argument("--modules", type=int, default=None, help="Custom module count")
        parser.add_argument(
            "--mode",
            type=str,
            choices=["full", "phase3-only", "microbenchmark"],
            default="full",
            help="Benchmark mode",
        )
        parser.add_argument(
            "--output",
            type=str,
            choices=["console", "json", "both"],
            default="both",
            help="Output format",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default="profiling_results",
            help="Directory for JSON output",
        )
        parser.add_argument(
            "--repeat",
            type=int,
            default=1,
            help="Number of runs for statistical analysis",
        )

    def handle(self, *args, **options):
        # Build config
        if options["scale"]:
            config = PRESET_SCALES[options["scale"]]
            # Clone so we don't mutate the preset
            config = SyntheticRepoConfig(**config.__dict__)
        else:
            config = SyntheticRepoConfig()

        # Apply custom overrides
        if options["files"]:
            config.file_count = options["files"]
            config.name = f"synthetic-custom-{config.file_count}"
        if options["prs"]:
            config.pr_count = options["prs"]
        if options["engineers"]:
            config.engineer_count = options["engineers"]
        if options["modules"]:
            config.module_count = options["modules"]

        self.stdout.write(self.style.SUCCESS(
            f"Running {options['mode']} benchmark: "
            f"{config.file_count} files, {config.pr_count} PRs, "
            f"{config.engineer_count} engineers, {config.module_count} modules"
        ))

        run_benchmark(
            config=config,
            mode=options["mode"],
            output=options["output"],
            output_dir=options["output_dir"],
            repeat=options["repeat"],
        )

        self.stdout.write(self.style.SUCCESS("Benchmark complete."))
