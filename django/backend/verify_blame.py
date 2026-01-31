import os
import sys
import pprint
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


# Setup Django environment manually to avoid loading all apps/dependencies
from django.conf import settings
if not settings.configured:
    settings.configure(DEBUG=True, SECRET_KEY='test-key', TIME_ZONE='UTC')

# Add backend directory to sys.path so we can import the app
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    from git_blame_ingestion_app.services.client import GitHubClient
    from git_blame_ingestion_app.services.file_contents import FileContentsService
except ImportError as e:
    print(f"Import Error: {e}")
    print("Ensure you are running this script from the correct directory or python path.")
    sys.exit(1)

def verify():
    # Use a known public repo and file
    # octocat/Hello-World is a classic test repo
    owner = "justin-chung-swemap"
    repo = "Webhook_Test"
    file_path = "api/build.gradle" # Note: In octocat/Hello-World it is just "README"
    
    print(f"Initializing GitHubClient...")
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        print("WARNING: GITHUB_TOKEN is not set in environment or .env file.")
        print("         Requests will likely fail (401/403) for GraphQL.")
        print("         Please run: export GITHUB_TOKEN=your_token_here")
    
    client = GitHubClient(token=token)
    service = FileContentsService(client)
    
    print(f"Fetching raw blame for {owner}/{repo}/{file_path}...")
    try:
        # We need to make sure we are asking for a file that actually exists
        # and has some history.
        data = service.get_raw_blame(owner, repo, file_path)
        print(data)
        return
        if not data:
             print("Result is empty.")
             return

        print("\n--- Result Summary ---")
        if 'data' in data and 'repository' in data['data']:
             repo_data = data['data']['repository']
             print(f"Repo: {repo_data.get('repo_name')}")
             print(f"File: {repo_data.get('file_name')}")
             
             ref_data = repo_data.get('ref', {})
             if ref_data:
                 target = ref_data.get('target', {})
                 blame = target.get('blame', {})
                 ranges = blame.get('ranges', [])
                 print(f"Blame Ranges Found: {len(ranges)}")
                 
                 for i, r in enumerate(ranges[:3]): # Show first 3 ranges
                     commit = r.get('commit', {})
                     print(f"  Range {i+1}: Lines {r.get('startingLine')}-{r.get('endingLine')} | Commit: {commit.get('oid')[:7]} | Author: {commit.get('author', {}).get('name')}")
                     if 'reviewers' in commit:
                         print(f"    Reviewers: {commit['reviewers']}")
                 
                 if len(ranges) > 3:
                     print(f"  ... and {len(ranges)-3} more ranges.")
             else:
                 print("No ref data found (branch might not exist or empty).")
        else:
             print("Unexpected data structure or GraphQL error:")
             pprint.pprint(data)

    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify()
