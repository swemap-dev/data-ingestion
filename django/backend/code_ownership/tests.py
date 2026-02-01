from django.test import TestCase
from git_blame_ingestion_app.models import Repo, Module, File, Engineer, FileOwnershipMetric, InteractionType, Skill, SkillType
from code_ownership.services.module_analytics import calculate_module_ownership

class ModuleAnalyticsTest(TestCase):
    def setUp(self):
        # Create Dummy Repo and Module
        self.repo = Repo.objects.create(name="TestRepo", url="http://github.com/test/repo")
        self.module = Module.objects.create(repo=self.repo, name="TestModule", dir_path="test/module")
        
        # Create Engineers
        self.eng_alice = Engineer.objects.create(name="Alice", email="alice@example.com")
        self.eng_bob = Engineer.objects.create(name="Bob", email="bob@example.com")
        
        # Create Files
        # File 1: 100 lines
        self.file1 = File.objects.create(module=self.module, file_path="test/module/file1.py", line_count=100)
        # File 2: 200 lines
        self.file2 = File.objects.create(module=self.module, file_path="test/module/file2.py", line_count=200)
        
        # Total Module Lines = 300
        
        # Create Ownership Metrics
        # File 1: Alice wrote 60 lines (60%), Bob reviewed 60 lines (60%) -- logic allows > 100% total if reviewed count is separate? 
        # Actually reviewed is separate type.
        FileOwnershipMetric.objects.create(
            file=self.file1, engineer=self.eng_alice, 
            lines_owned=60, lines_owned_percentage=60.0, type=InteractionType.WROTE
        )
        FileOwnershipMetric.objects.create(
            file=self.file1, engineer=self.eng_bob, 
            lines_owned=60, lines_owned_percentage=60.0, type=InteractionType.REVIEWED
        )
        
        # File 2: Alice wrote 150 lines (75%), Bob wrote 50 lines (25%)
        FileOwnershipMetric.objects.create(
            file=self.file2, engineer=self.eng_alice, 
            lines_owned=150, lines_owned_percentage=75.0, type=InteractionType.WROTE
        )
        FileOwnershipMetric.objects.create(
            file=self.file2, engineer=self.eng_bob, 
            lines_owned=50, lines_owned_percentage=25.0, type=InteractionType.WROTE
        )

    def test_calculate_module_ownership(self):
        result = calculate_module_ownership(self.module.id)
        
        self.assertEqual(result['module_name'], "TestModule")
        self.assertEqual(result['total_lines'], 300)
        
        ownership = result['ownership']
        
        # Expected Results:
        # Alice WROTE: 60 (File1) + 150 (File2) = 210 lines. 210 / 300 = 70%
        # Bob WROTE: 0 (File1) + 50 (File2) = 50 lines. 50 / 300 = 16.67%
        # Bob REVIEWED: 60 (File1) = 60 lines. 60 / 300 = 20%
        
        alice_wrote = next(x for x in ownership if x['engineer_name'] == "Alice" and x['type'] == InteractionType.WROTE)
        self.assertEqual(alice_wrote['lines_owned'], 210)
        self.assertAlmostEqual(alice_wrote['percentage'], 70.0)
        
        bob_wrote = next(x for x in ownership if x['engineer_name'] == "Bob" and x['type'] == InteractionType.WROTE)
        self.assertEqual(bob_wrote['lines_owned'], 50)
        self.assertAlmostEqual(bob_wrote['percentage'], 16.67, places=2)
        
        bob_reviewed = next(x for x in ownership if x['engineer_name'] == "Bob" and x['type'] == InteractionType.REVIEWED)
        self.assertEqual(bob_reviewed['lines_owned'], 60)
        self.assertAlmostEqual(bob_reviewed['percentage'], 20.0)

