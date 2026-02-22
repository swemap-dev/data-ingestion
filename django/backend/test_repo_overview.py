
import os
import sys
import django
import json

# Setup Django Environment
sys.path.append('/Users/justinchung/Code/SWEMAP/data-ingestion/django/backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from git_blame_ingestion_app.models import Repo
from code_ownership.services.module_analytics import get_repo_overview

def test_overview():
    try:
        # Assuming 'swemap-demo' was initialized. If not, we might need to find any repo.
        repo = Repo.objects.filter(name='swemap-demo').first()
        if not repo:
            print("Repo 'swemap-demo' not found. Using first available repo.")
            repo = Repo.objects.first()
            
        if not repo:
            print("No repositories found in DB.")
            return

        print(f"Testing overview for repo: {repo.name} (ID: {repo.id})")
        overview = get_repo_overview(repo.id)
        print(json.dumps(overview, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_overview()
