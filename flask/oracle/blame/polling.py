import os
import sys
import json
import time
import schedule
import psycopg2
from urllib.parse import urlparse

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from pipeline import process_file_change, get_db_connection
from src.github.client import GitHubClient

STATE_FILE = "polling_state.json"

def get_monitored_repos(conn):
    cur = conn.cursor()
    cur.execute("SELECT url FROM repos")
    # Return list of URLs. Assume they are valid GitHub URLs.
    # Ex: https://github.com/owner/repo or https://github.com/owner/repo.git
    return [row[0] for row in cur.fetchall() if row[0]]

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def parse_repo_url(url):
    # Handle https://github.com/owner/repo
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    if path.endswith('.git'):
        path = path[:-4]
    parts = path.split('/')
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None

def poll_repos():
    print("Polling repositories...")
    conn = get_db_connection()
    state = load_state()
    
    try:
        repos = get_monitored_repos(conn)
        client = GitHubClient() # picks up env token
        
        for repo_url in repos:
            owner, name = parse_repo_url(repo_url)
            if not owner or not name:
                print(f"Skipping invalid URL: {repo_url}")
                continue
                
            repo_key = f"{owner}/{name}"
            print(f"Checking {repo_key}...")
            
            # 1. Get HEAD commit
            # GET /repos/{owner}/{repo}/git/ref/heads/{default_branch}
            # We assume 'main' or 'master', but we should really check default branch.
            # Client has 'get_repository' which returns metadata including default_branch.
            
            try:
                repo_meta = client.get_repository(owner, name)
                default_branch = repo_meta.default_branch
                
                # Fetch branch ref
                url = f"{client.base_url}/repos/{owner}/{name}/git/ref/heads/{default_branch}"
                res = client.session.get(url)
                if res.status_code != 200:
                    print(f"Failed to get HEAD for {repo_key}: {res.status_code}")
                    continue
                    
                current_sha = res.json()['object']['sha']
                
                last_sha = state.get(repo_key)
                
                if not last_sha:
                    print(f"First run for {repo_key}. Setting baseline to {current_sha}.")
                    state[repo_key] = current_sha
                    continue
                    
                if current_sha == last_sha:
                    print(f"No changes for {repo_key}.")
                    continue
                    
                # 2. Compare if changed
                print(f"Changes detected in {repo_key}: {last_sha[:7]} -> {current_sha[:7]}")
                
                compare_url = f"{client.base_url}/repos/{owner}/{name}/compare/{last_sha}...{current_sha}"
                res = client.session.get(compare_url)
                res.raise_for_status()
                diff_data = res.json()
                
                files = diff_data.get('files', [])
                for f in files:
                    # status: added, modified, removed, renamed
                    # We care about added/modified for now, per plan
                    status = f['status']
                    filename = f['filename']
                    
                    if status in ['added', 'modified', 'renamed']:
                        process_file_change(owner, name, current_sha, filename)
                    else:
                        print(f"Skipping {status} file: {filename}")
                        
                # Update state
                state[repo_key] = current_sha
                save_state(state) # Save incrementally
                
            except Exception as e:
                print(f"Error checking {repo_key}: {e}")
                
    finally:
        conn.close()
        save_state(state)

if __name__ == "__main__":
    # Run once immediately
    poll_repos()
    
    # Schedule
    schedule.every(5).minutes.do(poll_repos)
    
    print("Polling scheduler started.")
    while True:
        schedule.run_pending()
        time.sleep(1)
