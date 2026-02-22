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
