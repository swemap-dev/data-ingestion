import hashlib
import os
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from git_blame_ingestion_app.services.module_resolver import ModuleResolver


@dataclass
class SyntheticRepoConfig:
    name: str = "synthetic-repo"
    owner: str = "perf-test"
    file_count: int = 1000
    module_count: int = 10
    engineer_count: int = 20
    pr_count: int = 500
    avg_lines_per_file: int = 200
    avg_blame_ranges_per_file: int = 15
    avg_files_per_pr: int = 5
    lookback_days: int = 180
    pct_files_deep_nesting: float = 0.1
    pct_brain_files: float = 0.08
    language_weights: Dict[str, float] = field(default_factory=lambda: {
        ".py": 0.4, ".js": 0.3, ".ts": 0.15, ".java": 0.1, ".go": 0.05,
    })

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "owner": self.owner,
            "file_count": self.file_count,
            "module_count": self.module_count,
            "engineer_count": self.engineer_count,
            "pr_count": self.pr_count,
            "avg_lines_per_file": self.avg_lines_per_file,
            "avg_blame_ranges_per_file": self.avg_blame_ranges_per_file,
            "avg_files_per_pr": self.avg_files_per_pr,
            "lookback_days": self.lookback_days,
        }


# Preset scales
PRESET_SCALES = {
    "small": SyntheticRepoConfig(
        name="synthetic-small", file_count=500, pr_count=200,
        engineer_count=10, module_count=5,
    ),
    "medium": SyntheticRepoConfig(
        name="synthetic-medium", file_count=5000, pr_count=2000,
        engineer_count=30, module_count=20,
    ),
    "large": SyntheticRepoConfig(
        name="synthetic-large", file_count=20000, pr_count=10000,
        engineer_count=50, module_count=50,
    ),
    "stress": SyntheticRepoConfig(
        name="synthetic-stress", file_count=50000, pr_count=100000,
        engineer_count=100, module_count=100,
    ),
}


@dataclass
class SyntheticEngineer:
    name: str
    email: str


@dataclass
class SyntheticPR:
    number: int
    title: str
    merged_at: datetime
    author_login: str
    is_revert: bool
    is_bot: bool
    file_paths: List[str]


class SyntheticRepo:
    """Generates in-memory repository state from a SyntheticRepoConfig."""

    # Module markers from ModuleResolver
    MODULE_MARKERS = list(ModuleResolver.MODULE_MARKERS)

    def __init__(self, config: SyntheticRepoConfig):
        self.config = config
        self.rng = random.Random(42)  # deterministic

        self.engineers: List[SyntheticEngineer] = []
        self.file_paths: List[str] = []
        self.module_dirs: List[str] = []
        self.file_to_module: Dict[str, str] = {}
        self.file_lines: Dict[str, int] = {}
        self.prs: List[SyntheticPR] = []

        self._generate()

    def _generate(self):
        self._generate_engineers()
        self._generate_file_tree()
        self._generate_prs()

    def _generate_engineers(self):
        for i in range(self.config.engineer_count):
            self.engineers.append(SyntheticEngineer(
                name=f"Engineer {i}",
                email=f"eng{i}@example.com",
            ))

    def _zipf_pick_engineer(self) -> SyntheticEngineer:
        """Pick engineer with Zipf distribution (few own most code)."""
        n = len(self.engineers)
        # Zipf: P(rank k) ~ 1/k
        weights = [1.0 / (i + 1) for i in range(n)]
        return self.rng.choices(self.engineers, weights=weights, k=1)[0]

    def _generate_file_tree(self):
        """Generate realistic directory structure with module markers."""
        extensions = []
        for ext, weight in self.config.language_weights.items():
            extensions.extend([ext] * int(weight * 100))

        # Generate module directories
        top_level_dirs = [
            "src", "lib", "core", "api", "services", "utils", "models",
            "tests", "config", "scripts", "tools", "pkg", "internal",
            "app", "modules", "components", "handlers", "middleware",
        ]
        self.rng.shuffle(top_level_dirs)

        self.module_dirs = [""]  # root module
        for i in range(min(self.config.module_count, len(top_level_dirs))):
            self.module_dirs.append(top_level_dirs[i])

        # If we need more modules, create nested ones
        while len(self.module_dirs) < self.config.module_count + 1:
            parent = self.rng.choice(self.module_dirs[1:]) if len(self.module_dirs) > 1 else "src"
            sub_names = ["sub", "internal", "core", "util", "common", "shared"]
            sub = self.rng.choice(sub_names)
            new_dir = f"{parent}/{sub}_{len(self.module_dirs)}"
            self.module_dirs.append(new_dir)

        # Add module marker files
        for d in self.module_dirs[1:]:  # skip root
            marker = self.rng.choice(self.MODULE_MARKERS)
            marker_path = f"{d}/{marker}" if d else marker
            self.file_paths.append(marker_path)
            self.file_to_module[marker_path] = d
            self.file_lines[marker_path] = 10

        # Generate source files distributed across modules
        file_names = [
            "main", "app", "index", "server", "handler", "service",
            "controller", "model", "schema", "config", "utils", "helpers",
            "constants", "types", "middleware", "router", "client",
            "manager", "factory", "builder", "adapter", "proxy",
            "observer", "strategy", "validator", "parser", "formatter",
        ]

        files_generated = len(self.file_paths)
        target = self.config.file_count

        while files_generated < target:
            # Pick a module (weighted toward non-root)
            if len(self.module_dirs) > 1:
                weights = [0.05] + [1.0] * (len(self.module_dirs) - 1)
                module_dir = self.rng.choices(self.module_dirs, weights=weights, k=1)[0]
            else:
                module_dir = ""

            # Determine sub-directory depth (10% get deep nesting)
            depth = 0
            if self.rng.random() < self.config.pct_files_deep_nesting:
                depth = self.rng.randint(2, 5)
            else:
                depth = self.rng.randint(0, 2)

            sub_path = module_dir
            for _ in range(depth):
                sub_names = ["sub", "internal", "v2", "legacy", "impl", "detail"]
                sub_path = f"{sub_path}/{self.rng.choice(sub_names)}" if sub_path else self.rng.choice(sub_names)

            base_name = self.rng.choice(file_names)
            ext = self.rng.choice(extensions)
            suffix = f"_{files_generated}" if files_generated > len(file_names) else ""
            file_name = f"{base_name}{suffix}{ext}"
            file_path = f"{sub_path}/{file_name}" if sub_path else file_name

            if file_path not in self.file_to_module:
                self.file_paths.append(file_path)
                self.file_to_module[file_path] = module_dir
                # Line count varies: most are avg, some are large (brain file candidates)
                if self.rng.random() < self.config.pct_brain_files:
                    lines = self.rng.randint(300, 1000)
                else:
                    lines = max(10, int(self.rng.gauss(
                        self.config.avg_lines_per_file,
                        self.config.avg_lines_per_file * 0.5
                    )))
                self.file_lines[file_path] = lines
                files_generated += 1

    def _generate_prs(self):
        """Generate PR data with exponential decay timestamps."""
        now = datetime.now(timezone.utc)
        source_files = [p for p in self.file_paths if not any(
            p.endswith(m) for m in self.MODULE_MARKERS
        )]

        for i in range(self.config.pr_count):
            # Exponential decay: more recent PRs more frequent
            days_ago = self.rng.expovariate(1.0 / 30)  # mean 30 days ago
            days_ago = min(days_ago, self.config.lookback_days)
            merged_at = now - timedelta(days=days_ago)

            # Power-law file count (most touch 1-5, some touch 50+)
            file_count = max(1, int(self.rng.paretovariate(1.5)))
            file_count = min(file_count, len(source_files), 100)

            pr_files = self.rng.sample(source_files, min(file_count, len(source_files)))

            # ~5% revert, ~3% bot
            is_revert = self.rng.random() < 0.05
            is_bot = self.rng.random() < 0.03
            engineer = self._zipf_pick_engineer()

            title_prefix = "Revert " if is_revert else ""
            author = f"{engineer.name.lower().replace(' ', '-')}[bot]" if is_bot else engineer.name.lower().replace(' ', '-')

            self.prs.append(SyntheticPR(
                number=i + 1,
                title=f"{title_prefix}Update {', '.join(os.path.basename(f) for f in pr_files[:3])}",
                merged_at=merged_at,
                author_login=author,
                is_revert=is_revert,
                is_bot=is_bot,
                file_paths=pr_files,
            ))

    def get_tree_entries_for_dir(self, dir_path: str) -> List[dict]:
        """Return tree entries (blobs + subdirs) for a given directory."""
        entries = []
        seen_dirs = set()

        prefix = f"{dir_path}/" if dir_path else ""

        for fp in self.file_paths:
            if not fp.startswith(prefix):
                continue

            remainder = fp[len(prefix):]
            parts = remainder.split("/")

            if len(parts) == 1:
                # Direct child file
                entries.append({
                    "name": parts[0],
                    "type": "blob",
                    "oid": hashlib.sha1(fp.encode()).hexdigest(),
                })
            else:
                # Subdirectory
                subdir = parts[0]
                if subdir not in seen_dirs:
                    seen_dirs.add(subdir)
                    entries.append({
                        "name": subdir,
                        "type": "tree",
                        "oid": hashlib.sha1(f"{prefix}{subdir}".encode()).hexdigest(),
                    })

        return entries

    def get_source_code_for_file(self, file_path: str) -> bytes:
        """Generate synthetic source code with realistic AST features."""
        lines = self.file_lines.get(file_path, 100)
        ext = os.path.splitext(file_path)[1]

        # Pick some files from the same module as import targets
        module = self.file_to_module.get(file_path, "")
        same_module_files = [
            f for f in self.file_paths
            if self.file_to_module.get(f) == module
            and f != file_path
            and not any(f.endswith(m) for m in self.MODULE_MARKERS)
        ]

        rng = random.Random(hash(file_path))
        num_imports = rng.randint(2, min(12, max(2, len(same_module_files))))
        import_targets = rng.sample(same_module_files, min(num_imports, len(same_module_files)))

        if ext == ".py":
            return self._gen_python(file_path, lines, import_targets, rng)
        elif ext in (".js", ".jsx", ".ts", ".tsx"):
            return self._gen_javascript(file_path, lines, import_targets, rng)
        else:
            return self._gen_generic(file_path, lines, rng)

    def _gen_python(self, file_path, total_lines, imports, rng) -> bytes:
        code_lines = []

        # Imports
        for imp in imports:
            mod_path = os.path.splitext(imp)[0].replace("/", ".")
            code_lines.append(f"import {mod_path}")

        code_lines.append("")

        # Classes
        num_classes = rng.randint(0, 3)
        class_names = []
        for c in range(num_classes):
            cname = f"Class{c}_{os.path.basename(file_path).split('.')[0].title()}"
            bases = [rng.choice(class_names)] if class_names and rng.random() < 0.3 else []
            base_str = f"({', '.join(bases)})" if bases else ""
            code_lines.append(f"class {cname}{base_str}:")
            class_names.append(cname)

            # Add nesting for some files
            nesting = rng.randint(1, 6) if rng.random() < 0.15 else rng.randint(1, 3)
            indent = "    "
            code_lines.append(f"{indent}def method(self):")
            for d in range(nesting):
                code_lines.append(f"{indent * (d + 2)}if True:")
            code_lines.append(f"{indent * (nesting + 2)}pass")
            code_lines.append("")

        # Fill remaining lines
        while len(code_lines) < total_lines:
            code_lines.append(f"x_{len(code_lines)} = {len(code_lines)}")

        return "\n".join(code_lines[:total_lines]).encode("utf-8")

    def _gen_javascript(self, file_path, total_lines, imports, rng) -> bytes:
        code_lines = []

        for imp in imports:
            mod_path = "./" + os.path.splitext(imp)[0]
            code_lines.append(f"import {{ default as mod }} from '{mod_path}';")

        code_lines.append("")

        num_classes = rng.randint(0, 2)
        class_names = []
        for c in range(num_classes):
            cname = f"Class{c}"
            extends = f" extends {rng.choice(class_names)}" if class_names and rng.random() < 0.3 else ""
            code_lines.append(f"class {cname}{extends} {{")
            class_names.append(cname)

            nesting = rng.randint(1, 5) if rng.random() < 0.15 else rng.randint(1, 2)
            code_lines.append("  method() {")
            for d in range(nesting):
                code_lines.append(f"{'  ' * (d + 2)}if (true) {{")
            code_lines.append(f"{'  ' * (nesting + 2)}return;")
            for d in range(nesting):
                code_lines.append(f"{'  ' * (nesting + 1 - d)}}}")
            code_lines.append("  }")
            code_lines.append("}")
            code_lines.append("")

        while len(code_lines) < total_lines:
            code_lines.append(f"const x_{len(code_lines)} = {len(code_lines)};")

        return "\n".join(code_lines[:total_lines]).encode("utf-8")

    def _gen_generic(self, file_path, total_lines, rng) -> bytes:
        code_lines = []
        while len(code_lines) < total_lines:
            code_lines.append(f"line {len(code_lines) + 1}")
        return "\n".join(code_lines).encode("utf-8")
