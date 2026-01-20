import pytest
import os
import psycopg
import logging
from unittest.mock import MagicMock, patch
import dotenv

# Add parent directory to path to allow imports
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../oracle/blame')))

# Import app components AFTER setting up path
# We need to mock the client and service BEFORE importing webhook if they satisfy import-time logic,
# but here they are instantiated at module level. We will patch the instances.
from oracle.blame.webhook import app, initialize, job_queue, worker

# Constants
dotenv.load_dotenv()
DB_DSN = os.getenv('DB_DSN', "postgresql://postgres:test_password@localhost:5432/test_db")
logger = logging.getLogger(__name__)

@pytest.fixture(scope="module")
def db_conn():
    """Shared DB connection for verifying results."""
    conn = psycopg.connect(DB_DSN)
    conn.autocommit = True
    yield conn
    conn.close()

@pytest.fixture(autouse=True)
def clean_db(db_conn):
    """Clean tables before each test."""
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE line_ownership, file_ownership_metrics, files RESTART IDENTITY CASCADE")
        # Ensure we have a repo for initialization test
        # Repos are usually static, but we can verify against 'Webhook_Test' or insert a dummy one.
        # Let's ensure ID 1 exists for reliability.
        cur.execute("DELETE FROM modules")
        cur.execute("DELETE FROM repos")
        cur.execute("""
            INSERT INTO repos (id, name, url, language, risk_score) 
            VALUES (1, 'Test_Repo', 'https://github.com/owner/Test_Repo.git', 'Python', 0)
        """)
        cur.execute("INSERT INTO modules (id, name, repo_id) VALUES (1, 'Test_Mod', 1)")
    yield

@pytest.fixture
def mock_github():
    """Patches the global client and service objects in webhook.py"""
    with patch('oracle.blame.webhook.client') as mock_client, \
         patch('oracle.blame.webhook.service') as mock_service:
        
        # Mock Repository Metadata
        mock_repo = MagicMock()
        mock_repo.default_branch = "main"
        mock_client.get_repository.return_value = mock_repo
        
        # Mock Tree/Commit SHA
        mock_service._get_tree_sha.return_value = ("commit_sha_123", "tree_sha_abc", {})
        
        # Mock File List
        mock_service.get_all_file_paths.return_value = ["test_file.py"]
        
        # Mock Blame Data for Initialization
        mock_service.get_raw_blame.return_value = {
            "data": {
                "repository": {
                    "ref": {
                        "target": {
                            "blame": {
                                "ranges": [
                                    {
                                        "startingLine": 1,
                                        "endingLine": 10,
                                        "age": 1,
                                        "commit": {
                                            "oid": "commit_sha_123",
                                            "author": {"name": "Test User", "email": "test@example.com"}
                                        }
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
        
        yield mock_client, mock_service

@pytest.fixture
def flask_client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_initialization_flow(mock_github, db_conn):
    """Test that initialize() fetches files and populates DB."""
    mock_client, mock_service = mock_github
    
    # 1. Run Initialize directly
    # Note: initialization puts jobs in queue. Worker processes them.
    # We might need to start the worker or process queue manually.
    # The real webhook.py starts a worker thread. We can use that or drain queue manually.
    
    # Let's clear the queue first just in case
    # Let's clear the queue first just in case
    while not job_queue.empty(): job_queue.get()
    
    initialize()
    
    # 2. Verify job was enqueued
    assert job_queue.qsize() == 1
    item = job_queue.get()
    assert item == ('owner', 'Test_Repo', 'commit_sha_123', 'test_file.py')
    
    # 3. Process the job manually to verify DB effect
    # (Avoiding race conditions with background threads)
    repo_owner, repo_name, commit_hash, file_path = item
    
    # The worker logic essentially calls:
    # blame_data = service.get_raw_blame(...)
    # process_blame_response(1, blame_data, file_path)
    
    # Let's import the processing logic to call it directly for verification convenience,
    # or we can trust the worker function if we want to test that too.
    # Let's run the logic of the worker:
    blame_data = mock_service.get_raw_blame(repo_owner, repo_name, file_path, 'main')
    from oracle.blame.utils import process_blame_response
    process_blame_response(1, blame_data, file_path)
    
    # 4. Verify DB
    with db_conn.cursor() as cur:
        # Check File
        cur.execute("SELECT id, file_path, line_count FROM files WHERE file_path = %s", ('test_file.py',))
        file_row = cur.fetchone()
        assert file_row is not None
        file_id = file_row[0]
        assert file_row[1] == 'test_file.py'
        assert file_row[2] == 10 # 1 to 10 is 10 lines
        
        # Check Engineer
        cur.execute("SELECT id, name, email FROM engineers WHERE email = %s", ('test@example.com',))
        eng_row = cur.fetchone()
        assert eng_row is not None
        eng_id = eng_row[0]
        assert eng_row[1] == 'Test User'
        
        # Check Ownership
        cur.execute("SELECT lines_owned FROM file_ownership_metrics WHERE file_id = %s AND engineer_id = %s", (file_id, eng_id))
        metrics = cur.fetchone()
        assert metrics is not None
        assert metrics[0] == 10

def test_webhook_push_flow(mock_github, flask_client, db_conn):
    """Test full webhook push event flow."""
    mock_client, mock_service = mock_github
    
    # Setup mock for the push event file processing
    mock_service.get_raw_blame.return_value = {
        "data": {
            "repository": {
                "ref": {
                    "target": {
                        "blame": {
                            "ranges": [
                                {
                                    "startingLine": 1,
                                    "endingLine": 5,
                                    "age": 0,
                                    "commit": {
                                        # New commit
                                        "oid": "new_commit_456",
                                        "author": {"name": "New User", "email": "new@example.com"}
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }
    }

    payload = {
        "repository": {"full_name": "owner/Test_Repo"},
        "commits": [
            {
                "id": "new_commit_456",
                "modified": ["modified_file.py"],
                "added": []
            }
        ]
    }
    
    # 1. Send Webhook
    res = flask_client.post('/webhook', 
                            headers={'X-GitHub-Event': 'push'},
                            json=payload)
    assert res.status_code == 200
    assert res.json['status'] == 'processing'
    assert res.json['jobs_enqueued'] == 1
    
    # 2. Process Job
    item = job_queue.get(timeout=2)
    assert item == ('owner', 'Test_Repo', 'new_commit_456', 'modified_file.py')
    
    # Manually process
    repo_owner, repo_name, commit_hash, file_path = item
    blame_data = mock_service.get_raw_blame(repo_owner, repo_name, file_path, 'main')
    from oracle.blame.utils import process_blame_response
    process_blame_response(1, blame_data, file_path)
    
    # 3. Verify DB
    with db_conn.cursor() as cur:
         # Check File
        cur.execute("SELECT id, line_count FROM files WHERE file_path = %s", ('modified_file.py',))
        file_row = cur.fetchone()
        assert file_row is not None
        assert file_row[1] == 5
        
         # Check Engineer
        cur.execute("SELECT id FROM engineers WHERE email = %s", ('new@example.com',))
        assert cur.fetchone() is not None

def test_ownership_percentage(db_conn):
    """Test get_review_percentage_of_file with sequential commits."""
    file_path = "ownership_test_file.py"
    
    # Import necessary functions
    from oracle.blame.utils import process_blame_response, get_or_create_engineer
    from oracle.ownership.analytics import get_review_percentage_of_file # Updated name

    # Setup Engineers
    with db_conn.cursor() as cur:
        # We need known IDs for easier assertion, or we fetch them after creation
        pass 

    # --- Commit 1 ---
    # Eng 1 wrote [1, 50], Reviewed by Eng 2
    # Eng 2 wrote [51, 100], Reviewed by Eng 1
    # Note: GraphQL blame ranges are inclusive 1-based.
    
    blame_data_1 = {
        "data": {
            "repository": {
                "ref": {
                    "target": {
                        "blame": {
                            "ranges": [
                                {
                                    "startingLine": 1,
                                    "endingLine": 50,
                                    "commit": {
                                        "oid": "commit_1",
                                        "author": {"name": "Eng 1", "email": "eng1@test.com"},
                                        "reviewers": [{"name": "Eng 2", "email": "eng2@test.com", "submittedAt": "2023-01-01T10:00:00Z"}]
                                    }
                                },
                                {
                                    "startingLine": 51,
                                    "endingLine": 100,
                                    "commit": {
                                        "oid": "commit_1",
                                        "author": {"name": "Eng 2", "email": "eng2@test.com"},
                                        "reviewers": [{"name": "Eng 1", "email": "eng1@test.com", "submittedAt": "2023-01-01T10:00:00Z"}]
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }
    }
    
    # Process Commit 1
    print("Processing Commit 1")
    process_blame_response(1, blame_data_1, file_path)
    
    # Verify Commit 1 Metrics
    # We need file_id to call analytics
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM files WHERE file_path = %s", (file_path,))
        file_id = cur.fetchone()[0]
        
    results_1 = get_review_percentage_of_file(file_id)
    # Expected: 50% for Eng 1, 50% for Eng 2
    # Convert to dictionary for easier checking
    res_dict_1 = {name: pct for name, pct in results_1}
    
    assert len(res_dict_1) == 2
    assert res_dict_1.get("Eng 1") == pytest.approx(50.0)
    assert res_dict_1.get("Eng 2") == pytest.approx(50.0)
    
    # --- Commit 2 ---
    # Eng 2 overwrote [26, 50], Reviewed by Eng 1
    # This splits the first range.
    # New state:
    # [1, 25]: Eng 1 (Rev: Eng 2) (From Commit 1)
    # [26, 50]: Eng 2 (Rev: Eng 1) (From Commit 2)
    # [51, 100]: Eng 2 (Rev: Eng 1) (From Commit 1)
    
    blame_data_2 = {
        "data": {
            "repository": {
                "ref": {
                    "target": {
                        "blame": {
                            "ranges": [
                                {
                                    "startingLine": 1,
                                    "endingLine": 25,
                                    "commit": {
                                        "oid": "commit_1", # Old commit
                                        "author": {"name": "Eng 1", "email": "eng1@test.com"},
                                        "reviewers": [{"name": "Eng 2", "email": "eng2@test.com", "submittedAt": "2023-01-01T10:00:00Z"}]
                                    }
                                },
                                {
                                    "startingLine": 26, # Overwritten
                                    "endingLine": 50,
                                    "commit": {
                                        "oid": "commit_2", # New commit
                                        "author": {"name": "Eng 2", "email": "eng2@test.com"},
                                        "reviewers": [{"name": "Eng 1", "email": "eng1@test.com", "submittedAt": "2023-01-02T10:00:00Z"}]
                                    }
                                },
                                {
                                    "startingLine": 51,
                                    "endingLine": 100,
                                    "commit": {
                                        "oid": "commit_1", # Old commit
                                        "author": {"name": "Eng 2", "email": "eng2@test.com"},
                                        "reviewers": [{"name": "Eng 1", "email": "eng1@test.com", "submittedAt": "2023-01-01T10:00:00Z"}]
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }
    }

    # Process Commit 2
    print("Processing Commit 2")
    process_blame_response(1, blame_data_2, file_path)
    
    results_2 = get_review_percentage_of_file(file_id)
    # Expected: 
    # Eng 1 Reviews: [26, 50] (25 lines) + [51, 100] (50 lines) = 75 lines -> 75%
    # Eng 2 Reviews: [1, 25] (25 lines) -> 25%
    
    res_dict_2 = {name: pct for name, pct in results_2}

    assert res_dict_2.get("Eng 1") == pytest.approx(75.0)
    assert res_dict_2.get("Eng 2") == pytest.approx(25.0)
    assert len(res_dict_2) == 2
