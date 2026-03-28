"""
Brain File E2E — Stage 1: Verify Initialization
=================================================
Branch: test/stage-1 (SHA: 58a478c)

Repo state:
    src/: a.py, b.py, c.py, d.py, utils.py, standalone.py
    lib/: helper.py, config.py

Expected:
    - utils.py is a brain file (inbound_coupling=4, density=0.8)
    - standalone.py is NOT a brain file
    - lib/ is skipped (too small, < 5 files)

Usage:
    pytest test_brain_stage1.py -v

Prerequisites:
    - Django server running:  python manage.py runserver
    - Celery worker running:  celery -A backend worker -l info
    - Redis running
    - GITHUB_REPO_URLS env var pointing to brain-test-file-repo
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
CELERY_WAIT    = int(os.getenv("CELERY_WAIT", "10"))

STAGE_BRANCH = "test/stage-1"  # pinned to SHA 58a478c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api(path):
    return f"{BASE_URL}{path}"

def wait_for_celery(seconds=CELERY_WAIT):
    print(f"\n  [waiting {seconds}s for Celery...]")
    time.sleep(seconds)

def get_brain_files(module_id):
    resp = requests.get(api(f"/api/risk/modules/{module_id}/brain-files"))
    assert resp.status_code == 200, f"brain-files endpoint failed: {resp.text}"
    return resp.json()

def find_file(files, name):
    return next((f for f in files if name in f["file_path"]), None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def init_repo():
    """Initializes repo at test/stage-1 branch and waits for Celery."""
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
    assert resp.status_code == 200, f"get modules failed: {resp.text}"
    modules = resp.json()

    ids = {}
    for m in modules:
        name = m["module_name"].lower()
        if "src" in name:
            ids["src"] = m["module_id"]
        elif "lib" in name:
            ids["lib"] = m["module_id"]

    assert "src" in ids, f"src module not found in: {modules}"
    assert "lib" in ids, f"lib module not found in: {modules}"
    return ids


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStage1Setup:

    def test_server_is_reachable(self):
        """Health check — server must respond to GET /api/modules."""
        resp = requests.get(api("/api/modules"))
        assert resp.status_code == 200

    def test_init_all_accepts_ref(self):
        """Verify init-all endpoint accepts a ref parameter in the payload."""
        resp = requests.post(api("/api/init-all"), json={"ref": STAGE_BRANCH})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "triggered"
        assert "task_id" in data
        wait_for_celery()  # wait again since we just re-triggered


class TestStage1VerifyInitialization:

    def test_src_and_lib_modules_exist(self, module_ids):
        """Both src and lib modules should be present after initialization."""
        assert "src" in module_ids
        assert "lib" in module_ids

    def test_src_module_has_correct_files(self, module_ids):
        """src module should have exactly: a, b, c, d, utils, standalone."""
        resp = requests.get(api(f"/api/modules/{module_ids['src']}/files"))
        assert resp.status_code == 200
        files = resp.json()
        py_files = [f["file_path"] for f in files if f["file_path"].endswith(".py")]
        actual = {p.split("/")[-1] for p in py_files}
        expected = {"a.py", "b.py", "c.py", "d.py", "utils.py", "standalone.py"}
        assert expected == actual, f"Expected {expected}, got {actual}"

    def test_utils_is_brain_file(self, module_ids):
        """utils.py should be a brain file with inbound_coupling=4 and density>=0.8."""
        files = get_brain_files(module_ids["src"])
        utils = find_file(files, "utils.py")
        assert utils is not None, "utils.py not found in brain-files response"
        assert utils["is_brain_file"] is True, f"Expected is_brain_file=True, got {utils}"
        assert utils["inbound_coupling"] == 4, f"Expected inbound_coupling=4, got {utils['inbound_coupling']}"
        assert utils["module_density"] >= 0.8, f"Expected module_density>=0.8, got {utils['module_density']}"

    def test_standalone_is_not_brain_file(self, module_ids):
        """standalone.py should NOT be a brain file."""
        files = get_brain_files(module_ids["src"])
        standalone = find_file(files, "standalone.py")
        assert standalone is not None, "standalone.py not found in brain-files response"
        assert standalone["is_brain_file"] is False
        assert standalone["inbound_coupling"] == 0

    def test_lib_module_skipped_too_small(self, module_ids):
        """lib/ has < 5 files so brain file analysis should not run."""
        files = get_brain_files(module_ids["lib"])
        for f in files:
            assert f["is_brain_file"] is False, \
                f"Expected is_brain_file=False for {f['file_path']}, got True"