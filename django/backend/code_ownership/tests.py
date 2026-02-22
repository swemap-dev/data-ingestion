from django.test import TestCase
from git_blame_ingestion_app.models import Repo, Module, File, Engineer, FileOwnershipMetric, InteractionType, Skill, SkillType
from code_ownership.services.module_analytics import calculate_module_ownership, list_module_reviewers_random

class ModuleAnalyticsTest(TestCase):
    # ... existing setUp code ...
    def setUp(self):
        # Create Dummy Repo and Module
        self.repo = Repo.objects.create(name="TestRepo", url="http://github.com/test/repo")
        self.module = Module.objects.create(repo=self.repo, name="TestModule", dir_path="test/module")
        
        # Create Engineers
        self.eng_alice = Engineer.objects.create(name="Alice", email="alice@example.com")
        self.eng_bob = Engineer.objects.create(name="Bob", email="bob@example.com")
        self.eng_charlie = Engineer.objects.create(name="Charlie", email="charlie@example.com")
        
        # Create Files
        # File 1: 100 lines
        self.file1 = File.objects.create(module_id=self.module, file_path="test/module/file1.py", line_count=100)
        # File 2: 200 lines
        self.file2 = File.objects.create(module_id=self.module, file_path="test/module/file2.py", line_count=200)
        
        # Total Module Lines = 300
        
        # Create Ownership Metrics
        # File 1: Alice wrote 60 lines (60%), Bob reviewed 60 lines (60%) 
        FileOwnershipMetric.objects.create(
            file=self.file1, engineer=self.eng_alice, 
            lines_owned=60, lines_owned_percentage=60.0, type=InteractionType.WROTE
        )
        FileOwnershipMetric.objects.create(
            file=self.file1, engineer=self.eng_bob, 
            lines_owned=60, lines_owned_percentage=60.0, type=InteractionType.REVIEWED
        )
        
        # File 2: Alice wrote 150 lines (75%), Bob wrote 50 lines (25%)
        # Add Charlie as writer too to have 3 writers for accurate random testing
        FileOwnershipMetric.objects.create(
            file=self.file2, engineer=self.eng_alice, 
            lines_owned=150, lines_owned_percentage=75.0, type=InteractionType.WROTE
        )
        FileOwnershipMetric.objects.create(
            file=self.file2, engineer=self.eng_bob, 
            lines_owned=50, lines_owned_percentage=25.0, type=InteractionType.WROTE
        )
        FileOwnershipMetric.objects.create(
            file=self.file2, engineer=self.eng_charlie, 
            lines_owned=5, lines_owned_percentage=2.5, type=InteractionType.WROTE
        )

    # ... existing test_calculate_module_ownership code ...

    def test_list_module_reviewers_random(self):
        # We have 3 writers: Alice, Bob, Charlie (Charlie has very small contrib but counts as writer)
        reviewers = list_module_reviewers_random(self.module.id)
        
        # Should return exactly 2 reviewers
        self.assertEqual(len(reviewers), 2)
        
        # All returned reviewers should be from the writer set
        writer_ids = {self.eng_alice.id, self.eng_bob.id, self.eng_charlie.id}
        for r in reviewers:
            self.assertIn(r['engineer_id'], writer_ids)
            self.assertEqual(r['type'], InteractionType.WROTE)
            
    def test_list_module_reviewers_random_not_enough(self):
        # Create a module with only 1 writer
        module2 = Module.objects.create(repo=self.repo, name="SmallModule", dir_path="test/small")
        file_s = File.objects.create(module=module2, file_path="test/small/f.py", line_count=10)
        FileOwnershipMetric.objects.create(
            file=file_s, engineer=self.eng_alice, 
            lines_owned=10, lines_owned_percentage=100.0, type=InteractionType.WROTE
        )
        
        reviewers = list_module_reviewers_random(module2.id)
        self.assertEqual(len(reviewers), 1)
        self.assertEqual(reviewers[0]['engineer_id'], self.eng_alice.id)


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

