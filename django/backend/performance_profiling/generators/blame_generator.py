import random
import uuid


def generate_blame_ranges(synthetic_repo, file_path):
    """
    Generate blame ranges for a file.

    Returns a list of blame range dicts matching the shape consumed by
    process_blame_response (ingestion.py:30-39):
        {"startingLine": int, "endingLine": int, "commit": {"oid": str, "id": str,
         "author": {"name": str, "email": str}, "reviewers": [...]}}

    Ranges are contiguous, non-overlapping, and cover the full file.
    Engineers are Zipf-distributed.
    """
    total_lines = synthetic_repo.file_lines.get(file_path, 100)
    avg_ranges = synthetic_repo.config.avg_blame_ranges_per_file
    rng = random.Random(hash(file_path))

    # Determine number of ranges
    num_ranges = max(1, int(rng.gauss(avg_ranges, avg_ranges * 0.3)))
    num_ranges = min(num_ranges, total_lines)

    # Generate contiguous, non-overlapping ranges
    if num_ranges >= total_lines:
        # One range per line
        boundaries = list(range(1, total_lines + 1))
    else:
        # Pick split points
        if total_lines > 1:
            split_points = sorted(rng.sample(range(2, total_lines + 1), min(num_ranges - 1, total_lines - 1)))
        else:
            split_points = []
        boundaries = [1] + split_points + [total_lines + 1]

    ranges = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1] - 1

        engineer = synthetic_repo._zipf_pick_engineer()
        commit_oid = uuid.uuid5(uuid.NAMESPACE_DNS, f"{file_path}-{i}").hex[:40]
        commit_id = f"C_{commit_oid[:12]}"

        # Reviewer for ~40% of ranges
        reviewers = []
        if rng.random() < 0.4 and len(synthetic_repo.engineers) > 1:
            reviewer = rng.choice([e for e in synthetic_repo.engineers if e.email != engineer.email][:5])
            reviewers.append({
                "name": reviewer.name,
                "email": reviewer.email,
                "login": reviewer.name.lower().replace(" ", "-"),
                "submittedAt": "2025-01-15T10:00:00Z",
                "state": "APPROVED",
            })

        ranges.append({
            "startingLine": start,
            "endingLine": end,
            "age": rng.randint(1, 365),
            "commit": {
                "oid": commit_oid,
                "id": commit_id,
                "author": {
                    "name": engineer.name,
                    "email": engineer.email,
                    "user": {"login": engineer.name.lower().replace(" ", "-")},
                },
                "reviewers": reviewers,
            },
        })

    return ranges
