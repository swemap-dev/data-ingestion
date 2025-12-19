import os
import threading
import queue
import time
from flask import Flask, request, jsonify
from pipeline import process_file_change

from src.github import GitHubClient, FileContentsService
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
                print(f"======Blame data:\n {blame_data}======")
                with open('blame_data.json', 'w') as f:
                    json.dump(blame_data, f, indent=2)
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
