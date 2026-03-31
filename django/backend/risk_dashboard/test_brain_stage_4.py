"""
Brain File E2E — Stage 4: Webhook Grow Small Module
=====================================================
Branch: test/stage-4 (SHA: 8b40b50)

Repo state (adds to stage-3):
    lib/x.py, lib/y.py, lib/z.py added — all import helper.py

Expected:
    - lib/ module now has >= 5 files, triggering brain file analysis
    - helper.py becomes a brain file (inbound_coupling=3, imported by x/y/z)

Usage:
    pytest test_brain_stage4.py -v

Prerequisites:
    - Stage 3 tests should have passed first
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

BASE_URL       = os.getenv("BASE_URL", "http://localhost:8000")
GITHUB_OWNER   = os.getenv("GITHUB_OWNER", "swemap-dev")
REPO_NAME      = os.getenv("REPO_NAME", "brain-test-file-repo")
REPO_FULL_NAME = f"{GITHUB_OWNER}/{REPO_NAME}"
CELERY_WAIT    = int(os.getenv("CELERY_WAIT", "45"))

STAGE_BRANCH = "test/stage-3"  # init from stage-3 (f.py already present)
SHA_ADD_XYZ  = "test/stage-4"  # branch name, not short SHA


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
    """Initializes repo at test/stage-3 (f.py already present) and waits for Celery."""
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

    assert "lib" in ids, f"lib module not found in: {modules}"
    return ids

@pytest.fixture(scope="session")
def webhook_sent(module_ids):
    """Sends webhook for x/y/z.py and waits for Celery."""
    data = send_webhook(
        added=["lib/x.py", "lib/y.py", "lib/z.py"],
        commit_id=SHA_ADD_XYZ
    )
    assert data["jobs_enqueued"] == 3
    wait_for_celery()
    return data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStage4WebhookGrowSmallModule:

    def test_webhook_enqueues_three_jobs(self, webhook_sent):
        """Webhook for x/y/z.py at test/stage-4 should enqueue 3 jobs."""
        assert webhook_sent["status"] == "processing"
        assert webhook_sent["jobs_enqueued"] == 3

    def test_lib_module_now_has_enough_files(self, module_ids, webhook_sent):
        """lib/ module should now have >= 5 files after x/y/z are added."""
        files = recalculate_brain_files(module_ids["lib"])
        assert len(files) >= 5, \
            f"Expected >= 5 files in lib/ module, got {len(files)}"

    def test_helper_py_is_brain_file_in_lib(self, module_ids, webhook_sent):
        """lib/ now has >= 5 files so brain file analysis runs.
        helper.py has inbound_coupling=3 but density=0.75 < 0.8 so is_brain_file=False."""
        files = recalculate_brain_files(module_ids["lib"])
        helper = find_file(files, "helper.py")
        assert helper is not None, "helper.py not found in lib/ brain-files response"
        assert helper["inbound_coupling"] == 3, \
            f"Expected inbound_coupling=3, got {helper['inbound_coupling']}"
        assert helper["module_density"] == 0.75, \
            f"Expected module_density=0.75, got {helper['module_density']}"
        assert helper["is_brain_file"] is False, \
            f"Expected is_brain_file=False (density 0.75 < 0.8), got {helper}"