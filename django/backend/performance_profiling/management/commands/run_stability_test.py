from django.core.management.base import BaseCommand

from performance_profiling.generators.synthetic_repo import (
    SyntheticRepoConfig,
    PRESET_SCALES,
)
from performance_profiling.runners.stability_analyzer import run_stability_test


class Command(BaseCommand):
    help = "Run stability analysis on the data ingestion pipeline scoring"

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
            "--perturbation-size",
            type=int,
            default=5,
            help="Number of files to modify in perturbation",
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=0.001,
            help="Score delta threshold for stability check",
        )

    def handle(self, *args, **options):
        # Build config
        if options["scale"]:
            config = PRESET_SCALES[options["scale"]]
            config = SyntheticRepoConfig(**config.__dict__)
        else:
            config = SyntheticRepoConfig()

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
            f"Running stability test: "
            f"{config.file_count} files, {config.pr_count} PRs, "
            f"perturbation_size={options['perturbation_size']}, "
            f"threshold={options['threshold']}"
        ))

        report = run_stability_test(
            config=config,
            perturbation_size=options["perturbation_size"],
            threshold=options["threshold"],
        )

        if report.pct_within_threshold >= 99:
            self.stdout.write(self.style.SUCCESS("PASS: Scores are stable."))
        else:
            self.stdout.write(self.style.WARNING(
                f"WARNING: Only {report.pct_within_threshold:.1f}% within threshold."
            ))
