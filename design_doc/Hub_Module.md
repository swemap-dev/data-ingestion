# Structural Risk Metrics Specification
## Overview
This specification defines the heuristics and algorithms needed to identify complex, high-risk files within a repository based on their import topology.

These metrics shift away from identifying a single "Brain" file and instead classify high-risk files based on their structural role: Global, Boundary, and Local.

## 1. Global Hubs (Foundational Risk)
Definition: Files or modules that provide shared models, state, configurations, or utilities used across the entire repository.
- Risk Type: High structural risk. Changing these files has a massive blast radius, often requiring repo-wide refactoring.
- Examples in conda:
```conda/base/context.py, conda/models/match_spec.py, conda/exceptions.py```.

### Implementation Algorithm
1. Extract AST/Imports: Parse all files in the repository to build a global directed graph of file dependencies ($G_{global}$).
2. Calculate In-Degree Centrality: For each file $F$, count the number of distinct files $N_F$ anywhere in the repository that import $F$.
3. Determine Threshold:
    - Absolute Threshold: $N_F \ge 30$ incoming dependencies.
    - Relative Threshold: $F$ is imported by $\ge 15%$ of all files in the repository.
4. Classification: If $F$ exceeds either threshold, flag as a Global Hub.

## 2. Boundary Hubs (Facade / Integration Risk)
Definition: Files that serve as the public entry point or API facade for a specific internal module. They are rarely imported by their siblings but are heavily imported by external modules.

- Risk Type: Interface contract risk. Changes to these files break integration between major subsystems, but not the internal implementations.
- Examples in conda: conda/core/solve.py, conda/api.py.

### Implementation Algorithm
1. Module Scoping: Group files by their parent directory (e.g., all files in conda/core/ belong to module $M_{core}$).
2. Calculate External vs. Internal In-Degree: For a file $F$ in module $M$:
    - Let $E_F$ be the number of importing files outside module $M$.
    - Let $I_F$ be the number of importing files inside module $M$.
3. Determine Threshold:
    - $E_F \ge 5$ (Must have sufficient external usage to matter).
    - Ratio of External to Internal imports: $E_F / (I_F + E_F) \ge 0.80$ (80% or more of its incoming dependencies come from the outside).
4. Classification: If $F$ meets these thresholds, flag as a Boundary Hub.

## 3. Local Hubs (Subsystem Risk)
Definition: Files that drive the internal logic, state, or data structures within a highly encapsulated module, but are rarely exposed to the outside world.

- Risk Type: Localized subsystem risk. Complex to modify, but the blast radius is strictly contained to the parent directory.
- Examples in conda: conda/core/prefix_data.py, conda/core/package_cache_data.py.

### Implementation Algorithm
1. Module Scoping: Group files by their parent directory (module $M$).
2. Calculate Intra-Module Dependency: For a file $F$ in module $M$:
    - Let $I_F$ be the number of importing files inside module $M$.
    - Let $S_M$ be the total number of files in module $M$ (excluding $F$).
3. Determine Threshold:
$S_M \ge 3$ (Ignore trivial modules with 1-2 files).
    - Relative Threshold: $I_F / S_M \ge 0.70$ (File is imported by $\ge 70%$ of its sibling files).
    - Ratio Constraint: $I_F / (I_F + E_F) \ge 0.50$ (At least half of its usage is internal, ensuring it's not actually a Boundary Node).
4. Classification: If $F$ meets these thresholds, flag as a Local Hub.

## Data Pipeline Summary
To implement this efficiently in an ingestion pipeline:

1. Generate the Global Dependency Graph.
2. Identify Global Hubs first (and remove them from subsequent domain-specific calculations, as they will skew local module metrics).
3. Compute the $I_F$ (Internal) and $E_F$ (External) counts for all remaining files.
4. Classify the remainder as Boundary Hubs or Local Hubs using the defined ratios.