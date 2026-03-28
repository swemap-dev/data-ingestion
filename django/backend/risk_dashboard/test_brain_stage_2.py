"""
Brain File E2E — Stage 2: Webhook Add File That Imports Utils
==============================================================
Branch: test/stage-2 (SHA: 3e217db)

Repo state (adds to stage-1):
    src/e.py added — imports utils

Expected:
    - utils.py inbound_coupling increases from 4 → 5
    - utils.py remains a brain file (density still >= 0.8)

Usage:
    pytest test_brain_stage2.py -v

Prerequisites:
    - Stage 1 tests should have passed first
    - Django server running:  python manage.py runserver
    - Celery worker running:  celery -A backend worker -l info
    - Redis running
"""

import os
import time
import pytest
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "swemap-dev")
REPO_NAME = os.getenv("REPO_NAME", "brain-test-file-repo")
REPO_FULL_NAME = f"{GITHUB_OWNER}/{REPO_NAME}"
CELERY_WAIT = int(os.getenv("CELERY_WAIT", "15"))

STAGE_BRANCH = "test/stage-1"  # init from stage-1 (clean base state)
SHA_ADD_E = "test/stage-2"  # branch name, not short SHA       # commit SHA where e.py was added


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api(path):
    return f"{BASE_URL}{path}"

def wait_for_celery(seconds=CELERY_WAIT):
    print(f"\n  [waiting {seconds}s for Celery...]")
    time.sleep(seconds)

def recalculate_brain_files(module_id):
    resp = requests.post(api(f"/api/risk/modules/{module_id}/recalculate-brain-files"))
    assert resp.status_code == 200, f"recalculate endpoint failed: {resp.text}"
    return resp.json()

def send_webhook(added=None, modified=None, commit_id="test-commit"):
    payload = {
        "repository": {"full_name": REPO_FULL_NAME},
        "commits": [{
            "id": commit_id,
            "added": added or [],
            "modified": modified or []
        }]
    }
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "push"
    }
    resp = requests.post(api("/api/webhook"), json=payload, headers=headers)
    assert resp.status_code == 200, f"Webhook failed: {resp.text}"
    return resp.json()

def find_file(files, name):
    return next((f for f in files if name in f["file_path"]), None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def init_repo():
    """Initializes repo at test/stage-1 (clean base) and waits for Celery."""
    resp = requests.post(api("/api/init-all"), json={"ref": STAGE_BRANCH})
    assert resp.status_code == 200, f"init-all failed: {resp.text}"
    data = resp.json()
    assert data["status"] == "triggered"
    wait_for_celery()
    return data

@pytest.fixture(scope="session")
def module_ids(init_repo):
    """Returns dict of module name -> id after initialization."""
    resp = requests.get(api("/api/modules"))
    assert resp.status_code == 200
    modules = resp.json()

    ids = {}
    for m in modules:
        name = m["module_name"].lower()
        if "src" in name:
            ids["src"] = m["module_id"]
        elif "lib" in name:
            ids["lib"] = m["module_id"]

    assert "src" in ids, f"src module not found in: {modules}"
    return ids

@pytest.fixture(scope="session")
def webhook_sent(init_repo):
    """Sends webhook for e.py and waits for Celery."""
    data = send_webhook(added=["src/e.py"], commit_id=SHA_ADD_E)
    assert data["jobs_enqueued"] == 1
    wait_for_celery()
    return data
# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStage2WebhookAddFileImportsUtils:

    def test_webhook_enqueues_job_for_e_py(self, webhook_sent):
        """Webhook for src/e.py should enqueue 1 job."""
        assert webhook_sent["status"] == "processing"
        assert webhook_sent["jobs_enqueued"] == 1

    def test_inbound_coupling_increased_to_5(self, module_ids, webhook_sent):
        files = recalculate_brain_files(module_ids["src"])
        utils = find_file(files, "utils.py")
        assert utils is not None, "utils.py not found after recalculation"
        assert utils["inbound_coupling"] == 5, \
            f"Expected inbound_coupling=5, got {utils['inbound_coupling']}"

    def test_utils_remains_brain_file(self, module_ids, webhook_sent):
        files = recalculate_brain_files(module_ids["src"])
        utils = find_file(files, "utils.py")
        assert utils is not None
        assert utils["is_brain_file"] is True
        assert utils["module_density"] >= 0.8, \
            f"Expected density>=0.8, got {utils['module_density']}"