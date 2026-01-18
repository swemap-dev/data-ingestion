import os
import threading
import queue
import time
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from flask import Flask, request, jsonify
from utils import process_blame_response, get_monitored_repos, parse_repo_url, DB_DSN, get_or_create_module, get_module_id
import psycopg

from src.github.client import GitHubClient
from src.github.file_contents import FileContentsService
import json

client = GitHubClient()
service = FileContentsService(client)

app = Flask(__name__)

# Queue for background processing
# Item format: (repo_owner, repo_name, commit_hash, file_path)
job_queue = queue.Queue()

def worker():
    """
    Background worker that consumes jobs from the queue.
    Hardcoded module ID and Branch for now.
    """
    print("Worker thread started...")
    while True:
        try:
            # Block for 1 second, then check loop again (to allow graceful shutdown if needed)
            item = job_queue.get(timeout=1)
            repo_owner, repo_name, commit_hash, file_path = item
            print(repo_owner, repo_name, commit_hash, file_path)
            
            try:
                print(f"Worker picked up: {file_path} @ {commit_hash}")
                blame_data = service.get_raw_blame(repo_owner, repo_name, file_path, 'main')
                
                # Determine Module ID
                # Extract directory from file path to find module
                dir_path = os.path.dirname(file_path)
                
                module_id = 1 # Default fallback
                try:
                    with psycopg.connect(DB_DSN) as conn:
                        with conn.cursor() as cur:
                            # Using repo_id=1 hardcoded as requested
                            # Use get_or_create_module to ensure it exists even if new
                            # Using directory path as the name
                            module_id = get_or_create_module(cur, 1, dir_path, dir_path)
                            conn.commit()
                except Exception as e:
                    print(f"Error getting/creating module_id: {e}")

                process_blame_response(module_id, blame_data, file_path)
            except Exception as e:
                print(f"Error processing job {item}: {e}")
            finally:
                job_queue.task_done()
                
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Worker exception: {e}")

# Start worker thread
threading.Thread(target=worker, daemon=True).start()

def initialize():
    """
    Initializes the database by fetching blame data for all files in monitored repositories.
    """
    print("Initialization started...")
    # Give some time for DB and network to be ready if needed
    time.sleep(2) 
    
    try:
        repos = get_monitored_repos(DB_DSN)
        for repo_url in repos:
            owner, name = parse_repo_url(repo_url)
            if not owner or not name:
                print(f"Skipping invalid repo URL: {repo_url}")
                continue
                
            print(f"Initializing repository: {owner}/{name}")
            
            # Get default branch head
            try:
                repo_meta = client.get_repository(owner, name)
                ref = repo_meta.default_branch
                
                # We need the commit hash to associate with the blame data
                # Using _get_tree_sha to get the commit SHA efficiently
                commit_sha, _, _ = service._get_tree_sha(owner, name, ref)
                
                file_paths = service.get_all_file_paths(owner, name, ref)
                print(f"Enqueuing {len(file_paths)} initialization jobs for {owner}/{name} at {commit_sha}")
                
                # Pre-populate Modules Table
                unique_dirs = set(os.path.dirname(f) for f in file_paths)
                print(f"Found {len(unique_dirs)} unique directories/modules to initialize.")
                
                try:
                    with psycopg.connect(DB_DSN) as conn:
                        with conn.cursor() as cur:
                            for d in unique_dirs:
                                # Hardcoded repo_id=1 as requested
                                # Using directory path as the name
                                get_or_create_module(cur, 1, d, d) 
                        conn.commit()
                except Exception as e:
                    print(f"Error populating modules for {owner}/{name}: {e}")

                for fpath in file_paths:
                    if fpath.startswith("addons/base/"):
                        job_queue.put((owner, name, commit_sha, fpath))
                    
            except Exception as e:
                print(f"Error initializing {owner}/{name}: {e}")
                
    except Exception as e:
        print(f"Initialization failed: {e}")

# Start initialization thread
threading.Thread(target=initialize, daemon=True).start()

@app.route('/webhook', methods=['POST'])
def webhook():
    event = request.headers.get('X-GitHub-Event', 'ping')
    
    if event == 'ping':
        return jsonify({'status': 'pong'}), 200
        
    if event == 'push':
        payload = request.json
        if not payload:
            return jsonify({'error': 'No payload'}), 400
            
        # Extract repo info
        repo_data = payload.get('repository', {})
        repo_full_name = repo_data.get('full_name') # "owner/repo"
        if not repo_full_name:
             return jsonify({'error': 'Missing repository info'}), 400
             
        owner, name = repo_full_name.split('/')
        
        # Extract commits
        commits = payload.get('commits', [])
        
        enqueued_count = 0
        
        for commit in commits:
            commit_hash = commit.get('id')
            
            # Combine added and modified
            changed_files = commit.get('added', []) + commit.get('modified', [])
            
            for fpath in changed_files:
                job_queue.put((owner, name, commit_hash, fpath))
                enqueued_count += 1
                
        return jsonify({'status': 'processing', 'jobs_enqueued': enqueued_count}), 200
        
    return jsonify({'status': 'ignored'}), 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5001))    # 5000 taken by AirPlay on MacOS
    app.run(host='0.0.0.0', port=port)
