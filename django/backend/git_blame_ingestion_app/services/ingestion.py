import logging
from urllib.parse import urlparse
from django.db import transaction
from django.db.models import Sum, F, Func, Value, FloatField, IntegerField, ExpressionWrapper
from django.db.models.functions import Coalesce
from psycopg.types.range import Range as NumericRange

from ..models import (
    File, Engineer, LineOwnership, FileOwnershipMetric, 
    Repo, Module, InteractionType
)

logger = logging.getLogger(__name__)

class Upper(Func):
    function = 'upper'
    output_field = IntegerField()

class Lower(Func):
    function = 'lower'
    output_field = IntegerField()

@transaction.atomic
def process_blame_response(module_id: int, json_data: dict, file_path: str):
    """
    Ingests the GraphQL response and updates the DB.
    """
    try:
        # 1. Parse GraphQL Data
        repo_data = json_data.get('data', {}).get('repository', {})
        ref_data = repo_data.get('ref', {})
        target = ref_data.get('target', {})
        
        # Ensure we are looking at a Commit object
        if 'blame' not in target:
            logger.warning("Target is not a commit with blame history.")
            return

        blame_ranges = target['blame']['ranges']
        
        # 2. Get or Create File
        # Assuming module_id is valid.
        file_obj, created = File.objects.get_or_create(
            module_id=module_id, 
            file_path=file_path, 
            defaults={'line_count': 0}
        )
        file_id = file_obj.id

        # 3. Update Ownership
        # Strategy: Snapshot Replacement (Git blame is authoritative)
        
        # Clear old cache for this file to prevent overlaps
        LineOwnership.objects.filter(file_id=file_id).delete()
        
        total_lines = 0
        
        # Bulk create list
        line_ownerships = []

        for entry in blame_ranges:
            # Extract Engineer Info
            author = entry.get('commit', {}).get('author', {})
            author_name = author.get('name', 'Unknown')
            email = author.get('email', 'unknown@example.com')
            
            engineer_obj = get_or_create_engineer(author_name, email)
            engineer_id = engineer_obj.id

            # Extract Reviewer Info
            reviewers = entry.get('commit', {}).get('reviewers', [])
            reviewer_obj = None
            review_timestamp = None
            
            if reviewers:
                # Find the latest review by submittedAt
                valid_reviewers = [r for r in reviewers if r.get('submittedAt')]
                if valid_reviewers:
                    latest_reviewer = max(valid_reviewers, key=lambda x: x['submittedAt'])
                    
                    r_name = latest_reviewer.get('name') or latest_reviewer.get('login')
                    r_email = latest_reviewer.get('email')
                    
                    if not r_email and latest_reviewer.get('login'):
                        r_email = f"{latest_reviewer['login']}@users.noreply.github.com"
                    
                    if r_email:
                        reviewer_obj = get_or_create_engineer(r_name, r_email)
                        review_timestamp = latest_reviewer['submittedAt']

            # Extract Range Info
            start = entry['startingLine']
            end = entry['endingLine'] 
            # Postgres int4range is [lower, upper). 
            pg_range = NumericRange(start, end + 1)
            
            # Create LineOwnership object (to be bulk created)
            lo = LineOwnership(
                file_id=file_id,
                engineer_id=engineer_id,
                reviewer=reviewer_obj,
                timestamp=review_timestamp,
                line_range=pg_range,
                last_updated_commit=entry.get('commit', {}).get('oid')
            )
            line_ownerships.append(lo)
            
            # Track max line for total count
            total_lines = max(total_lines, end)

        # Bulk Insert
        if line_ownerships:
            LineOwnership.objects.bulk_create(line_ownerships)

        # 4. Update File Metadata
        File.objects.filter(id=file_id).update(line_count=total_lines)

        # 5. Aggregation Pipeline
        recalculate_metrics(file_id, total_lines)
        
        logger.info(f"Successfully processed blame for {file_path}: file_id {file_id}")

    except Exception as e:
        logger.error(f"Error processing blame response for {file_path} in module {module_id}: {e}", exc_info=True)
        # Transaction will be rolled back by @transaction.atomic

def get_or_create_engineer(name: str, email: str) -> Engineer:
    """Upserts engineer and returns object"""
    # Check by email first (unique constraint)
    # Using update_or_create in case name changed, though email is primary identifier
    engineer, created = Engineer.objects.update_or_create(
        email=email,
        defaults={'name': name}
    )
    return engineer

def recalculate_metrics(file_id: int, total_lines: int):
    """
    Sum the lengths of ranges owned by each engineer.
    """
    if total_lines == 0:
        return

    # Clear old metrics
    FileOwnershipMetric.objects.filter(file_id=file_id).delete()
    
    # 1. Calculate 'WROTE' metrics
    wrote_metrics = (
        LineOwnership.objects.filter(file_id=file_id)
        .values('engineer_id')
        .annotate(
            lines_owned=Sum(
                ExpressionWrapper(
                    Upper(F('line_range')) - Lower(F('line_range')),
                    output_field=IntegerField()
                )
            )
        )
    )

    metrics_to_create = []

    for m in wrote_metrics:
        lines_owned = m['lines_owned'] or 0
        percentage = (float(lines_owned) / total_lines) * 100
        metrics_to_create.append(
            FileOwnershipMetric(
                file_id=file_id,
                engineer_id=m['engineer_id'],
                lines_owned=lines_owned,
                lines_owned_percentage=percentage,
                type=InteractionType.WROTE
            )
        )

    # 2. Calculate 'REVIEWED' metrics
    reviewed_metrics = (
        LineOwnership.objects.filter(file_id=file_id, reviewer__isnull=False)
        .values('reviewer_id')
        .annotate(
            lines_owned=Sum(
                 ExpressionWrapper(
                    Upper(F('line_range')) - Lower(F('line_range')),
                    output_field=IntegerField()
                )
            )
        )
    )

    for m in reviewed_metrics:
        lines_owned = m['lines_owned'] or 0
        percentage = (float(lines_owned) / total_lines) * 100
        metrics_to_create.append(
            FileOwnershipMetric(
                file_id=file_id,
                engineer_id=m['reviewer_id'],
                lines_owned=lines_owned,
                lines_owned_percentage=percentage,
                type=InteractionType.REVIEWED
            )
        )
    
    if metrics_to_create:
        FileOwnershipMetric.objects.bulk_create(metrics_to_create)

def get_or_create_module(repo_id: int, name: str, dir_path: str) -> Module:
    """Upserts module and returns Object"""
    module, created = Module.objects.get_or_create(
        repo_id=repo_id,
        name=name,
        defaults={'dir_path': dir_path}
    )
    return module

def get_module_id(repo_id: int, dir_path: str) -> int:
    """Returns module ID for a directory path, or None if not found"""
    # Using dir_path as the name as per requirements
    try:
        module = Module.objects.get(repo_id=repo_id, name=dir_path)
        return module.id
    except Module.DoesNotExist:
        return None

def parse_repo_url(url: str) -> tuple[str, str]:
    """
    Parses owner and repo name from a GitHub URL.
    """
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    if path.endswith('.git'):
        path = path[:-4]
    parts = path.split('/')
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None

def resolve_module_from_db(repo_id: int, file_path: str) -> int:
    """
    Finds the correct module ID for a file path by looking for the longest matching
    directory path in the database.
    This assumes modules have already been populated.
    """
    import os
    current_dir = os.path.dirname(file_path)
    if current_dir == "":
        start_dir = "" # Start at root
    else:
        start_dir = current_dir

    # Bottom-up search in DB
    # We could optimize this by querying all modules for the repo and doing in-memory match
    # if the number of modules is small. But let's stick to spec logic.
    
    # Optimization: Get all module paths for this repo
    # This avoids repeated DB hits in a loop
    all_modules = Module.objects.filter(repo_id=repo_id).values_list('dir_path', 'id')
    module_map = {m[0]: m[1] for m in all_modules} # dir_path -> id
    
    search_dir = start_dir
    while True:
        if search_dir in module_map:
            return module_map[search_dir]
            
        if search_dir == "":
            break
            
        parent = os.path.dirname(search_dir)
        if parent == search_dir: # Should not happen with os.path.dirname but safely break
             break
        search_dir = parent
        
    # Fallback to finding "ROOT" explicitly if it exists in map as "" or "/"?
    # Spec says "Root_Module". We should have ensured a root module exists.
    # If our pre-scan adds "" as a module, it will be found above.
    
    # If not found, check if a root module exists with empty path
    if "" in module_map:
        return module_map[""]
        
    return None
