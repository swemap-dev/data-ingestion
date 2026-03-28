"""
Brain File E2E — Stage 3: Webhook Add File That Does NOT Import Utils
======================================================================
Branch: test/stage-3 (SHA: 05fe37a)

Repo state (adds to stage-2):
    src/f.py added — no imports

Expected:
    - utils.py inbound_coupling stays at 5 (f.py doesn't import it)
    - module_density drops: 5/7 peers = 0.714 < 0.8
    - utils.py LOSES brain file status

This is a critical edge case — a file with no imports should cause utils.py
to drop below the 0.8 density threshold and lose brain file classification.

Usage:
    pytest test_brain_stage3.py -v

Prerequisites:
    - Stage 2 tests should have passed first
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
CELERY_WAIT = int(os.getenv("CELERY_WAIT", "45"))

STAGE_BRANCH = "test/stage-2"  # init from stage-2 (e.py already present)
SHA_ADD_F = "test/stage-3"     # commit SHA where f.py was added


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
    """Initializes repo at test/stage-2 (e.py already present) and waits for Celery."""
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
def webhook_sent(module_ids):
    """Sends webhook for f.py and waits for Celery."""
    data = send_webhook(added=["src/f.py"], commit_id=SHA_ADD_F)
    assert data["jobs_enqueued"] == 1
    wait_for_celery()
    return data

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStage3WebhookAddFileNoImports:

    def test_webhook_enqueues_job_for_f_py(self, webhook_sent):
        """Webhook for src/f.py should enqueue 1 job."""
        assert webhook_sent["status"] == "processing"
        assert webhook_sent["jobs_enqueued"] == 1

    def test_density_decreased_below_threshold(self, module_ids, webhook_sent):
        """After f.py (no imports) is added, module_density should drop below 0.8."""
        files = recalculate_brain_files(module_ids["src"])
        utils = find_file(files, "utils.py")
        assert utils is not None, "utils.py not found after recalculation"
        assert utils["module_density"] < 0.8, \
            f"Expected module_density<0.8, got {utils['module_density']}"

    def test_utils_loses_brain_file_status(self, module_ids, webhook_sent):
        """utils.py should no longer be a brain file after density drops below 0.8."""
        files = recalculate_brain_files(module_ids["src"])
        utils = find_file(files, "utils.py")
        assert utils is not None
        assert utils["is_brain_file"] is False, \
            f"Expected is_brain_file=False after density drop, got {utils}"

    def test_inbound_coupling_unchanged(self, module_ids, webhook_sent):
        """inbound_coupling should still be 5 — f.py doesn't import utils."""
        files = recalculate_brain_files(module_ids["src"])
        utils = find_file(files, "utils.py")
        assert utils is not None
        assert utils["inbound_coupling"] == 5, \
            f"Expected inbound_coupling=5 (unchanged), got {utils['inbound_coupling']}"
