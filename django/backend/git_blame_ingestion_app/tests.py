
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase
from git_blame_ingestion_app.tasks import initialize

class TaskTests(SimpleTestCase):
    @patch('git_blame_ingestion_app.tasks.GitHubClient')
    @patch('git_blame_ingestion_app.tasks.FileContentsServiceGQL')
    @patch('git_blame_ingestion_app.services.module_resolver.ModuleResolver')
    @patch('git_blame_ingestion_app.tasks.chord')
    @patch('git_blame_ingestion_app.tasks.process_commit_blame')
    @patch('git_blame_ingestion_app.tasks.finalize_repo_ingestion')
    @patch('git_blame_ingestion_app.models.Repo')
    @patch('git_blame_ingestion_app.tasks.ingestion')
    @patch('git_blame_ingestion_app.services.pr_ingestion.ingest_merged_prs')
    @patch('git_blame_ingestion_app.models.Module')
    def test_initialize_uses_chord(self, mock_Module, mock_ingest_prs, mock_ingestion, mock_Repo, mock_finalize, mock_process, mock_chord, mock_resolver, mock_service, mock_client):
        # Setup mocks
        mock_client_instance = mock_client.return_value
        mock_client_instance.get_repository.return_value.default_branch = 'main'
        
        mock_service_instance = mock_service.return_value
        mock_service_instance._get_tree_sha.return_value = ('sha123', None, None)
        mock_service_instance.get_all_file_paths.return_value = ['file1.py', 'file2.py']
        
        mock_resolver_instance = mock_resolver.return_value
        mock_resolver_instance.known_modules = {'mod1', 'mod2'}
        
        # Mock ingestion
        mock_ingestion.parse_repo_url.return_value = ('test-owner', 'test-repo')
        
        # Mock DB calls
        # Repo.objects.get_or_create
        mock_repo_obj = MagicMock()
        mock_repo_obj.id = 1
        mock_Repo.objects.get_or_create.return_value = (mock_repo_obj, True)
        
        # Mock tasks.s() to return something we can check
        mock_process.s.side_effect = lambda *args: f"task_for_{args[3]}"
        # Mock .si() for finalize
        mock_finalize.si.return_value = "finalize_callback_immutable"
        
        # Run initialize
        initialize('https://github.com/test-owner/test-repo')
        
        # Verify chord was called
        self.assertTrue(mock_chord.called)
        
        # Verify tasks in chord header
        args, _ = mock_chord.call_args
        task_list = args[0]
        self.assertEqual(len(task_list), 2)
        
        # Verify callback
        mock_chord_return = mock_chord.return_value
        mock_chord_return.assert_called_once_with("finalize_callback_immutable")
        
        # Verify .si() was called
        mock_finalize.si.assert_called_once()
        
        # Verify Repo was created
        mock_Repo.objects.get_or_create.assert_called()

from django.test import TestCase, override_settings
from django.db import IntegrityError
from unittest.mock import patch, MagicMock
from git_blame_ingestion_app.api import api
from git_blame_ingestion_app.services import ingestion
from git_blame_ingestion_app.tasks import process_commit_blame

class WebhookAndFallbackTests(TestCase):
    def setUp(self):
        from git_blame_ingestion_app.models import Repo, Module
        self.repo = Repo.objects.create(name="test-repo", owner="test-owner", url="https://github.com/test-owner/test-repo")
        self.root_module = Module.objects.create(repo=self.repo, name="ROOT", dir_path="")

    @patch('git_blame_ingestion_app.api.process_commit_blame')
    def test_webhook_creates_new_module(self, mock_process_commit_blame):
        payload = {
            "repository": {"full_name": "test-owner/test-repo"},
            "commits": [
                {
                    "id": "abc1234",
                    "added": ["src/new_module/package.json"],
                    "modified": ["src/new_module/index.js"]
                }
            ]
        }
        
        response = self.client.post("/api/webhook", data=payload, content_type="application/json", headers={"X-GitHub-Event": "push"})
        self.assertEqual(response.status_code, 200)
        
        # Verify that the new module was created in the DB
        from git_blame_ingestion_app.models import Module
        new_module_exists = Module.objects.filter(repo=self.repo, name="src/new_module").exists()
        self.assertTrue(new_module_exists)
        
        # Verify task was enqueued
        self.assertEqual(mock_process_commit_blame.s.call_count, 2)

    @patch('git_blame_ingestion_app.tasks.ingestion.process_blame_response')
    @patch('git_blame_ingestion_app.tasks.FileContentsServiceGQL')
    @patch('git_blame_ingestion_app.tasks.get_shared_client')
    def test_process_commit_blame_fallback_to_root(self, mock_get_client, mock_service, mock_process_blame):
        # Setup mocks
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_srv = MagicMock()
        mock_service.return_value = mock_srv
        mock_srv.get_blame_with_content.return_value = ({"some": "data"}, None)

        # First, test success fallback
        process_commit_blame("test-owner", "test-repo", "abc1234", "some/random/file.py")
        
        # Should process with ROOT module ID
        mock_process_blame.assert_called_once_with(self.root_module.id, {"some": "data"}, "some/random/file.py", ast_summary=None)
        
        # Next, test what happens if ROOT is missing
        self.root_module.delete()
        mock_process_blame.reset_mock()
        
        process_commit_blame("test-owner", "test-repo", "abc1234", "some/random/file.py")
        # Should abort, not call process_blame
        mock_process_blame.assert_not_called()

class IngestionServiceTests(TestCase):
    def setUp(self):
        from git_blame_ingestion_app.models import Repo
        self.repo = Repo.objects.create(name="test-repo", owner="test-owner", url="https://github.com/test-owner/test-repo")

    @patch('git_blame_ingestion_app.models.Module.objects.get_or_create')
    @patch('git_blame_ingestion_app.models.Module.objects.get')
    def test_get_or_create_module_concurrency(self, mock_get, mock_get_or_create):
        # Simulate IntegrityError on creation Attempt
        mock_get_or_create.side_effect = IntegrityError("Concurrent insertion")
        
        # Simulate successful get afterwards
        mock_module = MagicMock()
        mock_get.return_value = mock_module
        
        result = ingestion.get_or_create_module(self.repo.id, "concurrent_mod", "concurrent_mod")
        
        # Verify we got the module back and get() was called
        self.assertEqual(result, mock_module)
        mock_get_or_create.assert_called_once()
        mock_get.assert_called_once_with(repo_id=self.repo.id, name="concurrent_mod")

class BrainFileE2ETests(TestCase):
    def setUp(self):
        # 60 lines to bypass the LINES_THRESHOLD=50 rule
        self.mock_brain_content = b"def brain():\n" + b"".join([b"    pass\n" for _ in range(60)])
        self.mock_dep_content = b"import src.utils\ndef dep():\n    pass\n"
        
        self.file_paths = [
            "src/requirements.txt",
            "src/utils.py",
            "src/a.py",
            "src/b.py",
            "src/c.py",
            "src/d.py",
        ]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch('git_blame_ingestion_app.services.pr_ingestion.ingest_merged_prs')
    @patch('git_blame_ingestion_app.tasks.get_shared_client')
    @patch('git_blame_ingestion_app.tasks.FileContentsServiceGQL')
    @patch('git_blame_ingestion_app.tasks.GitHubClient')
    def test_e2e_initialize_and_webhook_brain_file(self, mock_gh_client, mock_service_class, mock_get_client, mock_ingest_prs):
        # 1. Setup mocks
        mock_client = MagicMock()
        mock_gh_client.return_value = mock_client
        mock_get_client.return_value = mock_client
        mock_client.get_repository.return_value.default_branch = 'main'
        
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service._get_tree_sha.return_value = ('sha123', None, None)
        mock_service.get_all_file_paths.return_value = self.file_paths
        
        # Valid dummy blame response
        blame_response = {
            "data": {
                "repository": {
                    "ref": {
                        "target": {
                            "blame": {
                                "ranges": [
                                    {"startingLine": 1, "endingLine": 1, "age": 1, "commit": {"oid": "abc", "author": {"user": {"login": "test"}}}}
                                ]
                            }
                        }
                    }
                }
            }
        }
        
        def fake_get_blame_with_content(owner, repo, file_path, ref="main", reviewer_cache=None):
            if "utils.py" in file_path:
                return blame_response, self.mock_brain_content
            return blame_response, self.mock_dep_content
        mock_service.get_blame_with_content.side_effect = fake_get_blame_with_content
        
        # 2. Run initialize using a fake chord to ensure synchronous execution
        from git_blame_ingestion_app.tasks import initialize
        with patch('git_blame_ingestion_app.tasks.chord') as mock_chord:
            def fake_chord(tasks):
                for task in tasks:
                    task.apply()
                def callback_runner(callback):
                    callback.apply()
                return callback_runner
            mock_chord.side_effect = fake_chord
            
            initialize("https://github.com/test-owner/test-repo")

        # 3. Verify Repo and DB state
        from git_blame_ingestion_app.models import Repo, Module, File
        repo = Repo.objects.get(owner="test-owner", name="test-repo")
        module = Module.objects.get(repo=repo, name="src")
        
        # Assert file count is 6 (requirements.txt + utils + a,b,c,d)
        self.assertEqual(File.objects.filter(module_id=module.id).count(), 6)
        
        hub_file = File.objects.get(module_id=module.id, file_path="src/utils.py")

        # 4 importers out of 5 source files = 80% >= 15% relative threshold → Global Hub
        self.assertEqual(hub_file.hub_type, 'GLOBAL', "utils.py should be flagged as a Global Hub")
        self.assertEqual(hub_file.inbound_coupling, 4)
        
        # 4. Test webhook incremental update
        # We simulate a new webhook that adds 'src/e.py' which also imports 'src/utils.py'
        self.file_paths.append("src/e.py")
        payload = {
            "repository": {"full_name": "test-owner/test-repo"},
            "commits": [
                {
                    "id": "new_commit_hash",
                    "added": ["src/e.py"],
                    "modified": []
                }
            ]
        }
        
        # Send Webhook
        response = self.client.post("/api/webhook", data=payload, content_type="application/json", headers={"X-GitHub-Event": "push"})
        self.assertEqual(response.status_code, 200)
         
        # Emulate the calculation trigger that handles recalculation
        from risk_dashboard.services.brain_file_analysis import calculate_structural_hubs
        calculate_structural_hubs(repo.id)

        # Verify hub coupling increased
        hub_file.refresh_from_db()
        self.assertEqual(hub_file.inbound_coupling, 5, "Inbound coupling should dynamically increase from the webhook")


class ModuleHierarchyTests(TestCase):
    """Tests for hierarchical module parent-child relationships."""

    def setUp(self):
        from git_blame_ingestion_app.models import Repo, Module
        self.repo = Repo.objects.create(name="conda", owner="conda", url="https://github.com/conda/conda")
        
        # Create a 3-level hierarchy:
        #   ROOT
        #   └── conda
        #       ├── conda/core
        #       └── conda/plugins
        #           └── conda/plugins/virtual_packages
        self.root = Module.objects.create(repo=self.repo, name="ROOT", dir_path="")
        self.conda = Module.objects.create(repo=self.repo, name="conda", dir_path="conda", parent=self.root)
        self.core = Module.objects.create(repo=self.repo, name="conda/core", dir_path="conda/core", parent=self.conda)
        self.plugins = Module.objects.create(repo=self.repo, name="conda/plugins", dir_path="conda/plugins", parent=self.conda)
        self.virt_pkgs = Module.objects.create(repo=self.repo, name="conda/plugins/virtual_packages", dir_path="conda/plugins/virtual_packages", parent=self.plugins)

    def test_parent_child_relationships(self):
        """Verify parent FK creates correct tree structure."""
        self.assertIsNone(self.root.parent)
        self.assertEqual(self.conda.parent, self.root)
        self.assertEqual(self.core.parent, self.conda)
        self.assertEqual(self.plugins.parent, self.conda)
        self.assertEqual(self.virt_pkgs.parent, self.plugins)

        # Verify children traversal
        self.assertEqual(set(self.conda.children.all()), {self.core, self.plugins})
        self.assertEqual(set(self.plugins.children.all()), {self.virt_pkgs})
        self.assertEqual(self.core.children.count(), 0)

    def test_module_resolver_get_parent_module(self):
        """Verify ModuleResolver.get_parent_module finds nearest ancestor."""
        from git_blame_ingestion_app.services.module_resolver import ModuleResolver
        
        resolver = ModuleResolver([], manual_modules=[
            "", "conda", "conda/core", "conda/plugins", "conda/plugins/virtual_packages"
        ])
        
        self.assertIsNone(resolver.get_parent_module(""))
        self.assertEqual(resolver.get_parent_module("conda"), "")
        self.assertEqual(resolver.get_parent_module("conda/core"), "conda")
        self.assertEqual(resolver.get_parent_module("conda/plugins"), "conda")
        self.assertEqual(resolver.get_parent_module("conda/plugins/virtual_packages"), "conda/plugins")

    def test_modules_tree_endpoint(self):
        """Verify /modules/tree returns nested JSON structure."""
        response = self.client.get(f"/api/modules/tree?repo_id={self.repo.id}")
        self.assertEqual(response.status_code, 200)
        
        tree = response.json()
        # ROOT is the only top-level node (parent=None)
        self.assertEqual(len(tree), 1)
        root_node = tree[0]
        self.assertEqual(root_node["module_name"], "ROOT")
        
        # ROOT has one child: conda
        self.assertEqual(len(root_node["children"]), 1)
        conda_node = root_node["children"][0]
        self.assertEqual(conda_node["module_name"], "conda")
        
        # conda has two children: core and plugins
        self.assertEqual(len(conda_node["children"]), 2)
        child_names = {c["module_name"] for c in conda_node["children"]}
        self.assertEqual(child_names, {"conda/core", "conda/plugins"})

    def test_aggregate_risk_endpoint(self):
        """Verify /aggregate-risk rolls up metrics from descendants."""
        from git_blame_ingestion_app.models import File
        
        # Add a global hub file to the leaf module
        File.objects.create(
            module_id=self.virt_pkgs,
            file_path="conda/plugins/virtual_packages/cuda.py",
            line_count=200,
            hub_type='GLOBAL',
            structural_risk_score=5,
        )
        # Add a normal file to the parent
        File.objects.create(
            module_id=self.plugins,
            file_path="conda/plugins/main.py",
            line_count=100,
            hub_type=None,
            structural_risk_score=2,
        )

        response = self.client.get(f"/api/risk/modules/{self.plugins.id}/aggregate-risk")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["module_name"], "conda/plugins")

        # Own risk: 0 hubs, 2 structural risk
        self.assertEqual(data["own_risk"]["global_hub_count"], 0)
        self.assertEqual(data["own_risk"]["structural_risk_score"], 2)

        # Rolled up: 1 global hub (from child), 7 structural risk (2+5)
        self.assertEqual(data["rolled_up_risk"]["global_hub_count"], 1)
        self.assertEqual(data["rolled_up_risk"]["structural_risk_score"], 7)
