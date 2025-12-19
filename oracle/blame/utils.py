import psycopg
import json
import dotenv
import os
from psycopg.types.range import Range as NumericRange

# Database Connection String
dotenv.load_dotenv()
DB_DSN = os.getenv("DB_DSN")

def process_blame_response(module_id, json_data, file_path):
    """
    Ingests the GraphQL response and updates the DB.
    """
    conn = psycopg.connect(DB_DSN)
    cur = conn.cursor()
    
    try:
        # 1. Parse GraphQL Data
        # Navigating the nested structure
        repo_data = json_data['data']['repository']
        target = repo_data['ref']['target']
        
        # Ensure we are looking at a Commit object
        if 'blame' not in target:
            print("Target is not a commit with blame history.")
            return

        blame_ranges = target['blame']['ranges']
        
        # 2. Get or Create File/Engineer mappings
        file_id = get_or_create_file(cur, module_id, file_path)
        
        # 3. Transaction: Update Ownership
        # Strategy: Snapshot Replacement (Git blame is authoritative)
        
        # Clear old cache for this file to prevent overlaps
        cur.execute("DELETE FROM line_ownership WHERE file_id = %s", (file_id,))
        total_lines = 0
        
        for entry in blame_ranges:
            # Extract Engineer Info
            author_name = entry['commit']['author']['name']
            email = entry['commit']['author']['email'] # Assuming available in query
            engineer_id = get_or_create_engineer(cur, author_name, email)
            # Extract Range Info
            start = entry['startingLine']
            end = entry['endingLine'] 
            # Note: GraphQL blame is 1-based inclusive.
            # Postgres int4range is [lower, upper). 
            # So [1, 5] in Git -> [1, 6) in Postgres.
            pg_range = NumericRange(start, end + 1)
            
            # Insert into Line Ownership
            cur.execute("""
                INSERT INTO line_ownership (file_id, engineer_id, line_range, last_updated_commit)
                VALUES (%s, %s, %s, %s)
            """, (file_id, engineer_id, pg_range, entry['commit']['oid']))
            
            # Track max line for total count
            total_lines = max(total_lines, end)

        # 4. Update File Metadata
        cur.execute("UPDATE files SET line_count = %s WHERE id = %s", (total_lines, file_id))

        # 5. Aggregation Pipeline
        # Calculate ownership metrics
        recalculate_metrics(cur, file_id, total_lines)
        
        conn.commit()
        print(f"Successfully processed blame for {file_path}")

    except Exception as e:
        conn.rollback()
        print(f"Error processing pipeline: {e}")
    finally:
        conn.close()

def get_or_create_engineer(cur, name, email):
    """Upserts engineer and returns ID"""
    cur.execute("SELECT id FROM engineers WHERE email = %s", (email,))
    res = cur.fetchone()
    if res:
        return res[0]
    
    cur.execute("""
        INSERT INTO engineers (name, email) VALUES (%s, %s) 
        RETURNING id
    """, (name, email))
    return cur.fetchone()[0]

def get_or_create_file(cur, module_id, path):
    """Upserts file and returns ID"""
    cur.execute("SELECT id FROM files WHERE file_path = %s AND module_id = %s", (path, module_id))
    res = cur.fetchone()
    if res:
        return res[0]
    
    cur.execute("""
        INSERT INTO files (module_id, file_path) VALUES (%s, %s) 
        RETURNING id
    """, (module_id, path))
    return cur.fetchone()[0]    


def recalculate_metrics(cur, file_id, total_lines):
    """
    Sum the lengths of ranges owned by each engineer.
    """
    if total_lines == 0: return

    # Clear old metrics
    cur.execute("DELETE FROM file_ownership_metrics WHERE file_id = %s", (file_id,))
    
    # Aggregate using Postgres Range functions
    # upper(line_range) - lower(line_range) gives the count of lines
    cur.execute("""
        INSERT INTO file_ownership_metrics (file_id, engineer_id, lines_owned, lines_owned_percentage)
        SELECT 
            file_id,
            engineer_id,
            SUM(upper(line_range) - lower(line_range)) as lines_owned,
            (SUM(upper(line_range) - lower(line_range))::FLOAT / %s) * 100 as lines_owned_percentage
        FROM line_ownership
        WHERE file_id = %s
        GROUP BY file_id, engineer_id
    """, (total_lines, file_id))

# if __name__ == "__main__":
#     try:
#         script_dir = os.path.dirname(os.path.abspath(__file__))
#         json_path = os.path.join(script_dir, "blame_data.json")
        
#         with open(json_path, "r") as f:
#             json_data = json.load(f)
#             file_path = json_data['data']['repository']['file_name']
#             process_blame_response(1, json_data, file_path, DB_DSN)
#     except FileNotFoundError:
#         print("Error: The file 'blame_data.json' was not found.")
#     except json.JSONDecodeError as e:
#         print(f"Failed to decode JSON: {e}")