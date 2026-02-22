
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase
from git_blame_ingestion_app.tasks import initialize

class TaskTests(SimpleTestCase):
    @patch('git_blame_ingestion_app.tasks.GitHubClient')
    @patch('git_blame_ingestion_app.tasks.FileContentsService')
    @patch('git_blame_ingestion_app.services.module_resolver.ModuleResolver')
    @patch('git_blame_ingestion_app.tasks.chord')
    @patch('git_blame_ingestion_app.tasks.process_commit_blame')
    @patch('git_blame_ingestion_app.tasks.finalize_repo_ingestion')
    @patch('git_blame_ingestion_app.models.Repo')
    @patch('git_blame_ingestion_app.tasks.ingestion')
    def test_initialize_uses_chord(self, mock_ingestion, mock_Repo, mock_finalize, mock_process, mock_chord, mock_resolver, mock_service, mock_client):
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
        self.assertEqual(mock_process_commit_blame.delay.call_count, 2)

    @patch('git_blame_ingestion_app.tasks.ingestion.process_blame_response')
    @patch('git_blame_ingestion_app.tasks.FileContentsService')
    @patch('git_blame_ingestion_app.tasks.get_shared_client')
    def test_process_commit_blame_fallback_to_root(self, mock_get_client, mock_service, mock_process_blame):
        # Setup mocks
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_srv = MagicMock()
        mock_service.return_value = mock_srv
        mock_srv.get_raw_blame.return_value = {"some": "data"}

        # First, test success fallback
        process_commit_blame("test-owner", "test-repo", "abc1234", "some/random/file.py")
        
        # Should process with ROOT module ID
        mock_process_blame.assert_called_once_with(self.root_module.id, {"some": "data"}, "some/random/file.py")
        
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
