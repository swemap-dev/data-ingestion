import os
import sys
import json
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from src.github.client import GitHubClient
from src.github.file_contents import FileContentsService

def verify():
    # Ensure token is present
    if not os.environ.get("GITHUB_TOKEN"):
        print("Error: GITHUB_TOKEN env var not set.")
        return False

    client = GitHubClient()
    service = FileContentsService(client)
    
    # Using a public repo known to have PR reviews for verification purposes
    owner = "tiangolo"
    repo = "fastapi"
    file_path = "fastapi/applications.py"
    # owner = "justin-chung-swemap"
    # repo = "Webhook_Test"
    # file_path = "StoreStuff/ask_logo.xcf"
    
    print(f"Fetching blame for {owner}/{repo}/{file_path}...")
    
    # Get default branch
    try:
        repo_meta = client.get_repository(owner, repo)
        ref = repo_meta.default_branch
        print(f"Default branch is: {ref}")
    except Exception as e:
        print(f"Could not fetch repo metadata: {e}")
        ref = "main"

    try:
        data = service.get_raw_blame(owner, repo, file_path, ref=ref)
        
        # Check if we got data
        if not data:
            print("No data returned.")
            return

        # Navigate to ranges
        try:
            if data.get('data') is None:
                print(f"Data is None. Full response: {json.dumps(data, indent=2)}")
                return
                
            repo_data = data['data'].get('repository')
            if repo_data is None:
                print(f"Repository is None. Full response: {json.dumps(data, indent=2)}")
                return
                
            ref_data = repo_data.get('ref')
            if ref_data is None:
                print(f"Ref is None (branch might be wrong). Full response: {json.dumps(data, indent=2)}")
                return

            target = ref_data.get('target')
            if not target:
                print("Target is None.")
                return False
            blame = target.get('blame')
            if not blame:
                print("Blame is None.")
                return False
            ranges = blame.get('ranges', [])
            print(f"Found {len(ranges)} blame ranges.")
            
            found_reviewers = False
            for r in ranges:
                commit = r.get('commit', {})
                c_id = commit.get('id')
                reviewers = commit.get('reviewers')
                
                print(f"Commit: {c_id[:10] if c_id else 'None'} | Reviewers: {reviewers}")
                
                if reviewers:
                    found_reviewers = True
            
            if found_reviewers:
                print("\nSUCCESS: Found reviewers in at least one commit.")
                return True
            else:
                print("\nWARNING: No reviewers found. This might be normal if recent commits have no PRs/reviews, or if the repo is new/private without PRs.")
                return False
                
        except KeyError as e:
            print(f"Structure lookup failed: {e}")
            print(json.dumps(data, indent=2))
            return False

    except Exception as e:
        print(f"Execution failed: {e}")
        return False

if __name__ == "__main__":
    verify()
