import pytest
import os
import sys
from typing import List, Dict, Any

# Add parent directory to path to allow imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from src.github.client import GitHubClient
from src.github.file_contents import FileContentsService

@pytest.mark.skipif(not os.getenv("GITHUB_TOKEN"), reason="GITHUB_TOKEN not set")
def test_fetch_reviewers_live_integration():
    """
    Live integration test against a public repository to verify reviewer fetching.
    This test hits the real GitHub API.
    """
    client = GitHubClient()
    service = FileContentsService(client)
    
    # Using a public repo known to have PR reviews for verification purposes
    # tiangolo/fastapi is a good candidate due to high activity
    owner = "tiangolo"
    repo = "fastapi"
    file_path = "fastapi/applications.py"
    # owner = "justin-chung-swemap"
    # repo = "Webhook_Test"
    # file_path = "StoreStuff/ask_logo.xcf"
    
    # Dynamically fetch default branch to be robust
    try:
        repo_meta = client.get_repository(owner, repo)
        ref = repo_meta.default_branch
    except Exception as e:
        pytest.fail(f"Failed to fetch repository metadata: {e}")

    print(f"Fetching blame for {owner}/{repo}/{file_path} on {ref}...")
    
    try:
        data = service.get_raw_blame(owner, repo, file_path, ref)
        
        # Verify structure
        assert data is not None, "No data returned from get_raw_blame"
        assert "data" in data, "GraphQL response missing 'data'"
        
        repo_data = data["data"].get("repository")
        assert repo_data is not None, "Repository data not found"
        
        target = repo_data.get("ref", {}).get("target", {})
        assert target, "Ref/Target not found"
        
        blame = target.get("blame")
        assert blame, "Blame data not found"
        
        ranges = blame.get("ranges", [])
        assert len(ranges) > 0, "No blame ranges found"
        
        # Verify Reviewers
        found_reviewers = False
        sample_reviewer = None
        
        for r in ranges:
            commit = r.get("commit", {})
            reviewers = commit.get("reviewers", [])
            
            if reviewers:
                found_reviewers = True
                sample_reviewer = reviewers[0]
                
                # Check structure of a reviewer
                assert "login" in sample_reviewer, "Reviewer missing login"
                assert "name" in sample_reviewer, "Reviewer missing name"
                # Email is optional, so we don't assert it
                
                # Check if the returned reviewer is correct
                assert sample_reviewer["name"] == "Sebastián Ramírez", "Reviewer name does not match"
                
                # Once we find one, we know the logic works
                break
        
        if not found_reviewers:
            # This is technically possible if we picked a file/state with NO reviews,
            # but highly unlikely for fastapi/applications.py.
            # We warn but maybe don't fail if we want to be very loose, 
            # BUT for a test we want to know if it works.
            pytest.fail("No reviewers found in any commit. Logic might be broken or test target changed.")
            
        print(f"\nSUCCESS: Found reviewers. Sample: {sample_reviewer}")

    except Exception as e:
        pytest.fail(f"Test failed with exception: {e}")