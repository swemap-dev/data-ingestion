import os
import sys
# import psycopg2
import psycopg
from dotenv import load_dotenv

# Add parent directory to path to allow imports from src and db_schema
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.github.client import GitHubClient
from src.github.file_contents import FileContentsService
from utils import process_blame_response

load_dotenv()
DB_DSN = os.getenv("DB_DSN")

def get_db_connection():
    return psycopg.connect(DB_DSN)

def find_module_id(cursor, repo_url, file_path):
    """
    Finds the module ID for a given file path and repo URL.
    This is a simplification. In reality, you'd match the repo_id first, then find the module.
    """
    # First find repo
    cursor.execute("SELECT id FROM repos WHERE url LIKE %s", (f"%{repo_url}%",))
    repo_res = cursor.fetchone()
    if not repo_res:
        print(f"Repo not found for URL: {repo_url}")
        return None
    repo_id = repo_res[0]

    # Find module that covers this file path
    # Heuristic: Find a module with a dir_path that is a prefix of the file_path
    # For now, we assume one module per repo or just use a default module if not found?
    # Let's try to match exact module dir_path or simple fallback
    
    # Simple check: Do we have a module for this repo?
    cursor.execute("SELECT id, dir_path FROM modules WHERE repo_id = %s", (repo_id,))
    modules = cursor.fetchall()
    
    # Find longest matching prefix
    best_module_id = None
    max_len = -1
    
    for mod_id, dir_path in modules:
        if file_path.startswith(dir_path) and len(dir_path) > max_len:
            best_module_id = mod_id
            max_len = len(dir_path)
            
    if best_module_id:
        return best_module_id
        
    print(f"No matching module found for file {file_path} in repo {repo_id}")
    return None

def process_file_change(repo_owner, repo_name, commit_hash, file_path):
    """
    Orchestrates the update for a single file.
    """
    print(f"Processing file: {file_path} in {repo_owner}/{repo_name} at {commit_hash}")
    
    # 1. Setup GitHub Client
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN not found in environment.")
        return

    client = GitHubClient(token)
    service = FileContentsService(client)
    
    # 2. Fetch Blame Data
    # Note: range_cutter expects the full JSON structure with ['data']['repository']...
    # FileContentsService.get_blame returns the whole parsed structure if we use the code I saw.
    # I verified that existing get_blame returns `data` (the root json response).
    
    json_data = service.get_raw_blame(repo_owner, repo_name, file_path, ref=commit_hash)
    
    if not json_data or 'errors' in json_data:
        print(f"Failed to fetch blame data for {file_path}")
        return

    # 3. Find Module ID
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # We need the repo URL to find the module. Construct it.
        repo_url = f"github.com/{repo_owner}/{repo_name}"
        module_id = find_module_id(cur, repo_url, file_path)
        
        if not module_id:
            # Fallback or create? For now just skip.
            print(f"Skipping {file_path}: Module not found.")
            return

        # 4. Process Logic (DB Update)
        # range_cutter.process_blame_response handles its own DB connection/transaction
        # passed module_id, data, and file path.
        # Wait, range_cutter.process_blame_response creates its OWN connection. 
        # It takes (module_id, json_data, file_path).
        
        process_blame_response(module_id, json_data, file_path)
        
    except Exception as e:
        print(f"Error in pipeline for {file_path}: {e}")
    finally:
        conn.close()
