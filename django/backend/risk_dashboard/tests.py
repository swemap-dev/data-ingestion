from django.test import SimpleTestCase, override_settings
from unittest.mock import patch, MagicMock
from datetime import timedelta
from django.utils import timezone
from .services.risk_analytics import calculate_knowledge_distribution

@override_settings(RISK_CONFIG={
    "BUS_FACTOR_THRESHOLD": 90.0,
    "ABANDONED_CODE_THRESHOLD": 30.0,
    "ABANDONED_INACTIVE_DAYS": 90,
    "HEALTHY_SILO_TOP_MIN": 50.0,
    "HEALTHY_SILO_TOP_MAX": 70.0,
    "HEALTHY_SILO_OTHER_MIN": 10.0,
    "HEALTHY_SILO_OTHER_MAX": 20.0,
})
class RiskAnalyticsTests(SimpleTestCase):
    def setUp(self):
        self.engineer_1 = MagicMock()
        self.engineer_1.id = 1
        self.engineer_1.name = "Alice"
        self.engineer_1.last_active = timezone.now()

        self.engineer_2 = MagicMock()
        self.engineer_2.id = 2
        self.engineer_2.name = "Bob"
        self.engineer_2.last_active = timezone.now()
        
        self.engineer_3 = MagicMock()
        self.engineer_3.id = 3
        self.engineer_3.name = "Charlie"
        self.engineer_3.last_active = timezone.now()

    @patch('risk_dashboard.services.risk_analytics.Engineer.objects.get')
    @patch('risk_dashboard.services.risk_analytics.get_module_writers')
    def test_bus_factor_toxic_silo(self, mock_get_writers, mock_get_engineer):
        # Setup: Alice has 95% ownership
        mock_get_writers.return_value = [
            {'engineer_id': 1, 'engineer__name': 'Alice', 'percentage': 95.0, 'lines_owned': 950, 'type': 'WROTE'},
            {'engineer_id': 2, 'engineer__name': 'Bob', 'percentage': 5.0, 'lines_owned': 50, 'type': 'WROTE'},
        ]
        
        # Mock Engineer.objects.get to return corresponding mock engineer
        def side_effect(id):
            if id == 1: return self.engineer_1
            if id == 2: return self.engineer_2
            return None
        mock_get_engineer.side_effect = side_effect
        
        result = calculate_knowledge_distribution(1)
        
        self.assertTrue(result['bus_factor'])
        self.assertEqual(result['silo_type'], 'TOXIC_SILO')

    @patch('risk_dashboard.services.risk_analytics.Engineer.objects.get')
    @patch('risk_dashboard.services.risk_analytics.get_module_writers')
    def test_healthy_silo(self, mock_get_writers, mock_get_engineer):
        # Setup: Alice has 60%, Bob has 15%
        mock_get_writers.return_value = [
            {'engineer_id': 1, 'engineer__name': 'Alice', 'percentage': 60.0, 'lines_owned': 600, 'type': 'WROTE'},
            {'engineer_id': 2, 'engineer__name': 'Bob', 'percentage': 15.0, 'lines_owned': 150, 'type': 'WROTE'},
            {'engineer_id': 3, 'engineer__name': 'Charlie', 'percentage': 10.0, 'lines_owned': 100, 'type': 'WROTE'},
        ]
        
        def side_effect(id):
            if id == 1: return self.engineer_1
            if id == 2: return self.engineer_2
            if id == 3: return self.engineer_3
            return None
        mock_get_engineer.side_effect = side_effect
        
        result = calculate_knowledge_distribution(1)
        
        self.assertFalse(result['bus_factor'])
        self.assertEqual(result['silo_type'], 'HEALTHY_SILO')

    @patch('risk_dashboard.services.risk_analytics.Engineer.objects.get')
    @patch('risk_dashboard.services.risk_analytics.get_module_writers')
    def test_abandoned_code(self, mock_get_writers, mock_get_engineer):
        # Setup: Alice has 40% but is inactive
        self.engineer_1.last_active = timezone.now() - timedelta(days=100)
        
        mock_get_writers.return_value = [
            {'engineer_id': 1, 'engineer__name': 'Alice', 'percentage': 40.0, 'lines_owned': 400, 'type': 'WROTE'},
            {'engineer_id': 2, 'engineer__name': 'Bob', 'percentage': 30.0, 'lines_owned': 300, 'type': 'WROTE'},
        ]
        
        def side_effect(id):
            if id == 1: return self.engineer_1
            if id == 2: return self.engineer_2
            return None
        mock_get_engineer.side_effect = side_effect
        
        result = calculate_knowledge_distribution(1)
        
        self.assertTrue(result['abandoned_code'])
        self.assertIn("Alice", result['abandoned_details'])

from django.test import TestCase
from git_blame_ingestion_app.models import Repo, Module, File
from .services.brain_file_analysis import calculate_module_brain_files

class BrainFileAnalysisTests(TestCase):
    def setUp(self):
        self.repo = Repo.objects.create(name="test-repo", owner="test-owner", url="https://github.com/test-owner/test-repo")
        self.module = Module.objects.create(repo=self.repo, name="src", dir_path="src")
        
        # Create 5 files to meet MIN_MODULE_SIZE (5)
        # 1 central file (brain file), 4 dependent files
        
        # Central file: size > 500, imported by all 4 other files (Density = 4 / (5 - 1) = 1.0 > 0.8)
        self.brain_file = File.objects.create(
            module_id_id=self.module.id,
            file_path="src/utils.py",
            line_count=600,
            ast_summary={"loc": 600, "imports": []}
        )
        
        self.dep1 = File.objects.create(
            module_id_id=self.module.id,
            file_path="src/a.py",
            line_count=100,
            ast_summary={"loc": 100, "imports": ["src.utils"]}
        )
        self.dep2 = File.objects.create(
            module_id_id=self.module.id,
            file_path="src/b.py",
            line_count=100,
            ast_summary={"loc": 100, "imports": ["src.utils"]}
        )
        self.dep3 = File.objects.create(
            module_id_id=self.module.id,
            file_path="src/c.py",
            line_count=100,
            ast_summary={"loc": 100, "imports": ["src.utils"]}
        )
        self.dep4 = File.objects.create(
            module_id_id=self.module.id,
            file_path="src/d.py",
            line_count=100,
            ast_summary={"loc": 100, "imports": ["src.utils"]}
        )

    def test_calculate_module_brain_files(self):
        calculate_module_brain_files(self.module.id)
        
        # Refresh from DB
        self.brain_file.refresh_from_db()
        self.dep1.refresh_from_db()
        
        # Assertions
        self.assertTrue(self.brain_file.is_brain_file, "File should be a brain file")
        self.assertEqual(self.brain_file.inbound_coupling, 4)
        self.assertEqual(self.brain_file.module_density, 1.0)
        
        self.assertFalse(self.dep1.is_brain_file)
        self.assertEqual(self.dep1.inbound_coupling, 0)
        self.assertEqual(self.dep1.module_density, 0.0)

    def test_small_module_ignores_brain_files(self):
        # Remove a dependency so module size < MIN_MODULE_SIZE (5)
        self.dep4.delete()
        
        calculate_module_brain_files(self.module.id)
        self.brain_file.refresh_from_db()
        
        self.assertFalse(self.brain_file.is_brain_file, "Small modules should not have Brain Files")
