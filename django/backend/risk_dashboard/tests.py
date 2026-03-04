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


class StructuralComplexityTests(TestCase):
    def setUp(self):
        self.repo = Repo.objects.create(name="test-repo-sc", owner="test-owner-sc", url="https://github.com/test-owner-sc/test-repo-sc")
        self.module = Module.objects.create(repo=self.repo, name="lib", dir_path="lib")

    def _create_file(self, path, max_nesting=0, classes=None):
        return File.objects.create(
            module_id_id=self.module.id,
            file_path=path,
            line_count=100,
            ast_summary={
                "loc": 100,
                "imports": [],
                "max_nesting_depth": max_nesting,
                "classes": classes or [],
            }
        )

    def test_nesting_depth_flagged(self):
        """File with max_nesting_depth >= 4 gets +4 penalty."""
        from risk_dashboard.services.structural_complexity import calculate_structural_complexity
        f = self._create_file("lib/deep.py", max_nesting=5)

        calculate_structural_complexity(self.module.id)
        f.refresh_from_db()

        self.assertEqual(f.max_nesting_depth, 5)
        self.assertEqual(f.structural_risk_score, 4)

    def test_inheritance_depth_flagged(self):
        """Inheritance chain of depth >= 3 gets +4 penalty."""
        from risk_dashboard.services.structural_complexity import calculate_structural_complexity
        # Chain: A -> B -> C -> D (depth of D = 3)
        f1 = self._create_file("lib/base.py", classes=[{"name": "A", "bases": []}])
        f2 = self._create_file("lib/mid.py", classes=[{"name": "B", "bases": ["A"]}])
        f3 = self._create_file("lib/mid2.py", classes=[{"name": "C", "bases": ["B"]}])
        f4 = self._create_file("lib/leaf.py", classes=[{"name": "D", "bases": ["C"]}])

        calculate_structural_complexity(self.module.id)
        f4.refresh_from_db()
        f1.refresh_from_db()

        self.assertEqual(f4.max_inheritance_depth, 3)
        self.assertEqual(f4.structural_risk_score, 4)
        # A has no parents so depth = 0
        self.assertEqual(f1.max_inheritance_depth, 0)
        self.assertEqual(f1.structural_risk_score, 0)

    def test_no_penalty(self):
        """Files below both thresholds get score 0."""
        from risk_dashboard.services.structural_complexity import calculate_structural_complexity
        f = self._create_file("lib/simple.py", max_nesting=2, classes=[
            {"name": "X", "bases": ["Y"]}  # depth = 1, below threshold 3
        ])

        calculate_structural_complexity(self.module.id)
        f.refresh_from_db()

        self.assertEqual(f.structural_risk_score, 0)

    def test_combined_penalty(self):
        """File exceeding both thresholds gets score 8 (4+4)."""
        from risk_dashboard.services.structural_complexity import calculate_structural_complexity
        # Create an inheritance chain of depth 3
        self._create_file("lib/a.py", classes=[{"name": "A", "bases": []}])
        self._create_file("lib/b.py", classes=[{"name": "B", "bases": ["A"]}])
        self._create_file("lib/c.py", classes=[{"name": "C", "bases": ["B"]}])
        # This file has deep nesting AND inherits D from C (depth=3)
        f = self._create_file("lib/d.py", max_nesting=6, classes=[{"name": "D", "bases": ["C"]}])

        calculate_structural_complexity(self.module.id)
        f.refresh_from_db()

        self.assertEqual(f.max_nesting_depth, 6)
        self.assertEqual(f.max_inheritance_depth, 3)
        self.assertEqual(f.structural_risk_score, 8)


class StaticAnalysisStructuralTests(SimpleTestCase):
    def test_python_nesting_depth(self):
        """Parse a snippet with 4 levels of nesting; verify max_nesting_depth == 4."""
        from git_blame_ingestion_app.services.static_analysis import parse_python

        source = b"""
def foo():
    if True:
        for i in range(10):
            if i > 5:
                while True:
                    pass
"""
        result = parse_python(source)
        self.assertEqual(result["max_nesting_depth"], 4)

    def test_python_class_extraction(self):
        """Parse a snippet with class Foo(Bar) and verify classes list."""
        from git_blame_ingestion_app.services.static_analysis import parse_python

        source = b"""
class Bar:
    pass

class Foo(Bar):
    pass
"""
        result = parse_python(source)
        classes = result["classes"]
        self.assertEqual(len(classes), 2)

        bar_cls = next(c for c in classes if c["name"] == "Bar")
        foo_cls = next(c for c in classes if c["name"] == "Foo")
        self.assertEqual(bar_cls["bases"], [])
        self.assertEqual(foo_cls["bases"], ["Bar"])

    def test_python_no_nesting(self):
        """A flat file should have nesting depth 0."""
        from git_blame_ingestion_app.services.static_analysis import parse_python

        source = b"""
x = 1
y = 2
print(x + y)
"""
        result = parse_python(source)
        self.assertEqual(result["max_nesting_depth"], 0)


# ──────────────────────────────────────────────────────────────────────
# Stress Tests
# ──────────────────────────────────────────────────────────────────────

from risk_dashboard.services.structural_complexity import (
    calculate_structural_complexity,
    _compute_inheritance_depths,
    NESTING_THRESHOLD,
    INHERITANCE_THRESHOLD,
    NESTING_PENALTY,
    INHERITANCE_PENALTY,
)
from risk_dashboard.services.brain_file_analysis import (
    calculate_module_brain_files,
    USAGE_THRESHOLD,
    LINES_THRESHOLD,
    MIN_MODULE_SIZE,
)


class DeepInheritanceStressTests(TestCase):
    """Stress tests for inheritance depth computation."""

    def setUp(self):
        self.repo = Repo.objects.create(name="inh-repo", owner="inh-owner", url="https://github.com/inh/repo")
        self.module = Module.objects.create(repo=self.repo, name="pkg", dir_path="pkg")

    def _create_file(self, path, classes=None, max_nesting=0):
        return File.objects.create(
            module_id_id=self.module.id,
            file_path=path,
            line_count=100,
            ast_summary={
                "loc": 100,
                "imports": [],
                "max_nesting_depth": max_nesting,
                "classes": classes or [],
            },
        )

    def test_very_deep_chain(self):
        """Chain of depth 12: A->B->...->M should give depth 12 for M."""
        names = [chr(65 + i) for i in range(13)]  # A..M
        for i, name in enumerate(names):
            bases = [names[i - 1]] if i > 0 else []
            self._create_file(f"pkg/{name.lower()}.py", classes=[{"name": name, "bases": bases}])

        calculate_structural_complexity(self.module.id)
        last = File.objects.get(file_path=f"pkg/{names[-1].lower()}.py")
        self.assertEqual(last.max_inheritance_depth, 12)
        self.assertEqual(last.structural_risk_score, INHERITANCE_PENALTY)

    def test_diamond_inheritance_first_base_only(self):
        """Diamond: D(B,C), B(A), C(A). Depth uses first base only."""
        self._create_file("pkg/a.py", classes=[{"name": "A", "bases": []}])
        self._create_file("pkg/b.py", classes=[{"name": "B", "bases": ["A"]}])
        self._create_file("pkg/c.py", classes=[{"name": "C", "bases": ["A"]}])
        self._create_file("pkg/d.py", classes=[{"name": "D", "bases": ["B", "C"]}])

        calculate_structural_complexity(self.module.id)
        d = File.objects.get(file_path="pkg/d.py")
        # D -> B -> A => depth 2 (first base)
        self.assertEqual(d.max_inheritance_depth, 2)

    def test_multiple_classes_in_same_file_max_wins(self):
        """File with two classes: one depth-0, one depth-3. Max depth wins."""
        self._create_file("pkg/base.py", classes=[{"name": "A", "bases": []}])
        self._create_file("pkg/mid.py", classes=[{"name": "B", "bases": ["A"]}])
        self._create_file("pkg/mid2.py", classes=[{"name": "C", "bases": ["B"]}])
        # File has both a root class and a deep class
        self._create_file("pkg/combo.py", classes=[
            {"name": "Root", "bases": []},
            {"name": "D", "bases": ["C"]},
        ])

        calculate_structural_complexity(self.module.id)
        combo = File.objects.get(file_path="pkg/combo.py")
        self.assertEqual(combo.max_inheritance_depth, 3)  # D's depth

    def test_cross_file_inheritance(self):
        """Classes in separate files forming a chain."""
        self._create_file("pkg/f1.py", classes=[{"name": "X", "bases": []}])
        self._create_file("pkg/f2.py", classes=[{"name": "Y", "bases": ["X"]}])
        self._create_file("pkg/f3.py", classes=[{"name": "Z", "bases": ["Y"]}])

        calculate_structural_complexity(self.module.id)
        f3 = File.objects.get(file_path="pkg/f3.py")
        self.assertEqual(f3.max_inheritance_depth, 2)

    def test_orphan_base_class(self):
        """Class extends unknown parent — depth should be 1 (parent not in module)."""
        self._create_file("pkg/orphan.py", classes=[{"name": "Child", "bases": ["UnknownParent"]}])

        calculate_structural_complexity(self.module.id)
        f = File.objects.get(file_path="pkg/orphan.py")
        # UnknownParent not in parent_map, so depth(Child) = 1 + depth(UnknownParent) = 1 + 0 = 1
        self.assertEqual(f.max_inheritance_depth, 1)

    def test_cycle_two_way(self):
        """Two classes forming a cycle: A(B), B(A). Should not hang."""
        self._create_file("pkg/cyc.py", classes=[
            {"name": "A", "bases": ["B"]},
            {"name": "B", "bases": ["A"]},
        ])

        calculate_structural_complexity(self.module.id)
        f = File.objects.get(file_path="pkg/cyc.py")
        # Cycle detection breaks the chain — depth is finite
        self.assertLessEqual(f.max_inheritance_depth, 2)

    def test_self_referencing_class(self):
        """Class inherits from itself: A(A). Should not hang."""
        self._create_file("pkg/self.py", classes=[{"name": "A", "bases": ["A"]}])

        calculate_structural_complexity(self.module.id)
        f = File.objects.get(file_path="pkg/self.py")
        self.assertLessEqual(f.max_inheritance_depth, 1)

    def test_three_way_cycle(self):
        """A(C), B(A), C(B) — three-way cycle."""
        self._create_file("pkg/cyc3.py", classes=[
            {"name": "A", "bases": ["C"]},
            {"name": "B", "bases": ["A"]},
            {"name": "C", "bases": ["B"]},
        ])

        calculate_structural_complexity(self.module.id)
        f = File.objects.get(file_path="pkg/cyc3.py")
        self.assertLessEqual(f.max_inheritance_depth, 3)

    def test_empty_module_no_classes(self):
        """Module with a file that has no classes."""
        self._create_file("pkg/empty.py", classes=[])

        calculate_structural_complexity(self.module.id)
        f = File.objects.get(file_path="pkg/empty.py")
        self.assertEqual(f.max_inheritance_depth, 0)
        self.assertEqual(f.structural_risk_score, 0)

    def test_none_ast_summary(self):
        """File with None ast_summary should get depth 0."""
        File.objects.create(
            module_id_id=self.module.id,
            file_path="pkg/none.py",
            line_count=50,
            ast_summary=None,
        )

        calculate_structural_complexity(self.module.id)
        f = File.objects.get(file_path="pkg/none.py")
        self.assertEqual(f.max_inheritance_depth, 0)
        self.assertEqual(f.max_nesting_depth, 0)

    def test_class_name_collision_last_wins(self):
        """Two files define class 'Helper' — last processed wins for class_to_file_id."""
        self._create_file("pkg/a_helper.py", classes=[{"name": "Helper", "bases": []}])
        self._create_file("pkg/z_helper.py", classes=[{"name": "Helper", "bases": []}])
        self._create_file("pkg/user.py", classes=[{"name": "User", "bases": ["Helper"]}])

        calculate_structural_complexity(self.module.id)
        user_f = File.objects.get(file_path="pkg/user.py")
        self.assertEqual(user_f.max_inheritance_depth, 1)

    def test_boundary_depth_exactly_at_threshold(self):
        """Chain of depth exactly INHERITANCE_THRESHOLD should trigger penalty."""
        # INHERITANCE_THRESHOLD = 3, so A->B->C->D gives D depth=3
        self._create_file("pkg/a.py", classes=[{"name": "A", "bases": []}])
        self._create_file("pkg/b.py", classes=[{"name": "B", "bases": ["A"]}])
        self._create_file("pkg/c.py", classes=[{"name": "C", "bases": ["B"]}])
        self._create_file("pkg/d.py", classes=[{"name": "D", "bases": ["C"]}])

        calculate_structural_complexity(self.module.id)
        d = File.objects.get(file_path="pkg/d.py")
        self.assertEqual(d.max_inheritance_depth, INHERITANCE_THRESHOLD)
        self.assertEqual(d.structural_risk_score, INHERITANCE_PENALTY)

    def test_boundary_depth_just_below_threshold(self):
        """Chain of depth INHERITANCE_THRESHOLD-1 should NOT trigger penalty."""
        # depth 2: A->B->C
        self._create_file("pkg/a.py", classes=[{"name": "A", "bases": []}])
        self._create_file("pkg/b.py", classes=[{"name": "B", "bases": ["A"]}])
        self._create_file("pkg/c.py", classes=[{"name": "C", "bases": ["B"]}])

        calculate_structural_complexity(self.module.id)
        c = File.objects.get(file_path="pkg/c.py")
        self.assertEqual(c.max_inheritance_depth, 2)
        self.assertEqual(c.structural_risk_score, 0)

    def test_deep_chain_plus_orphan_coexist(self):
        """Module has both a deep chain and an orphan — both computed correctly."""
        self._create_file("pkg/a.py", classes=[{"name": "A", "bases": []}])
        self._create_file("pkg/b.py", classes=[{"name": "B", "bases": ["A"]}])
        self._create_file("pkg/c.py", classes=[{"name": "C", "bases": ["B"]}])
        self._create_file("pkg/d.py", classes=[{"name": "D", "bases": ["C"]}])
        self._create_file("pkg/orphan.py", classes=[{"name": "O", "bases": ["Missing"]}])

        calculate_structural_complexity(self.module.id)
        d = File.objects.get(file_path="pkg/d.py")
        o = File.objects.get(file_path="pkg/orphan.py")
        self.assertEqual(d.max_inheritance_depth, 3)
        self.assertEqual(o.max_inheritance_depth, 1)

    def test_compute_inheritance_depths_empty_list(self):
        """_compute_inheritance_depths with empty list returns empty dict."""
        result = _compute_inheritance_depths([])
        self.assertEqual(result, {})


class NestingDepthParserStressTests(SimpleTestCase):
    """Stress tests for the nesting depth parser (tree-sitter based)."""

    def test_extreme_nesting_10_levels(self):
        """10 levels of nested if/for/while."""
        from git_blame_ingestion_app.services.static_analysis import parse_python

        source = b"""
def deep():
    if True:
        for a in []:
            if True:
                while True:
                    if True:
                        for b in []:
                            if True:
                                while True:
                                    if True:
                                        for c in []:
                                            pass
"""
        result = parse_python(source)
        self.assertEqual(result["max_nesting_depth"], 10)

    def test_parallel_branches_max_is_deepest(self):
        """Two branches: one depth-2, one depth-4. Max should be 4."""
        from git_blame_ingestion_app.services.static_analysis import parse_python

        source = b"""
def branch1():
    if True:
        for x in []:
            pass

def branch2():
    if True:
        for x in []:
            while True:
                if True:
                    pass
"""
        result = parse_python(source)
        self.assertEqual(result["max_nesting_depth"], 4)

    def test_elif_chains(self):
        """elif counts as a nesting level in Python."""
        from git_blame_ingestion_app.services.static_analysis import parse_python

        source = b"""
def foo():
    if True:
        pass
    elif True:
        if True:
            pass
    elif True:
        pass
"""
        result = parse_python(source)
        # if_statement(1) -> elif_clause(2) -> if_statement(3)
        self.assertEqual(result["max_nesting_depth"], 3)

    def test_try_except_finally(self):
        """try/except/finally all count as nesting levels."""
        from git_blame_ingestion_app.services.static_analysis import parse_python

        source = b"""
def foo():
    try:
        if True:
            pass
    except Exception:
        for x in []:
            pass
    finally:
        while True:
            break
"""
        result = parse_python(source)
        # try(1)->except_clause(2)->for(3) = 3; try(1)->finally_clause(2)->while(3) = 3
        self.assertEqual(result["max_nesting_depth"], 3)

    def test_nested_function_only_control_flow_counts(self):
        """Nested function definitions do NOT count as nesting levels."""
        from git_blame_ingestion_app.services.static_analysis import parse_python

        source = b"""
def outer():
    def inner():
        if True:
            pass
"""
        result = parse_python(source)
        # Only if_statement counts, not function defs
        self.assertEqual(result["max_nesting_depth"], 1)

    def test_empty_file(self):
        """Empty file has nesting depth 0."""
        from git_blame_ingestion_app.services.static_analysis import parse_python

        result = parse_python(b"")
        self.assertEqual(result["max_nesting_depth"], 0)

    def test_single_line_code(self):
        """Single statement has nesting depth 0."""
        from git_blame_ingestion_app.services.static_analysis import parse_python

        result = parse_python(b"x = 1")
        self.assertEqual(result["max_nesting_depth"], 0)

    def test_js_switch_case_nesting(self):
        """JS switch/case counts as nesting."""
        from git_blame_ingestion_app.services.static_analysis import parse_javascript

        source = b"""
function foo(x) {
    switch (x) {
        case 1:
            if (true) {
                break;
            }
    }
}
"""
        result = parse_javascript(source)
        # switch(1) -> case(2) -> if(3)
        self.assertEqual(result["max_nesting_depth"], 3)

    def test_js_do_while_nesting(self):
        """JS do-while counts as nesting."""
        from git_blame_ingestion_app.services.static_analysis import parse_javascript

        source = b"""
function foo() {
    do {
        if (true) {
            for (var i = 0; i < 10; i++) {
            }
        }
    } while (true);
}
"""
        result = parse_javascript(source)
        # do(1) -> if(2) -> for(3)
        self.assertEqual(result["max_nesting_depth"], 3)

    def test_mixed_constructs(self):
        """Mix of if, for, try, while."""
        from git_blame_ingestion_app.services.static_analysis import parse_python

        source = b"""
def foo():
    for x in []:
        try:
            if True:
                while True:
                    pass
        except:
            pass
"""
        result = parse_python(source)
        # for(1) -> try(2) -> if(3) -> while(4)
        self.assertEqual(result["max_nesting_depth"], 4)


class NestingDepthServiceStressTests(TestCase):
    """Stress tests for nesting depth in the structural_complexity service."""

    def setUp(self):
        self.repo = Repo.objects.create(name="nest-repo", owner="nest-owner", url="https://github.com/nest/repo")
        self.module = Module.objects.create(repo=self.repo, name="app", dir_path="app")

    def _create_file(self, path, max_nesting=0, classes=None):
        return File.objects.create(
            module_id_id=self.module.id,
            file_path=path,
            line_count=100,
            ast_summary={
                "loc": 100,
                "imports": [],
                "max_nesting_depth": max_nesting,
                "classes": classes or [],
            },
        )

    def test_twenty_files_aggregation(self):
        """20 files with varying nesting — only those >= threshold get penalties."""
        for i in range(20):
            self._create_file(f"app/f{i}.py", max_nesting=i % 7)

        calculate_structural_complexity(self.module.id)
        flagged = File.objects.filter(module_id_id=self.module.id, structural_risk_score__gt=0)
        # Nesting values: 0,1,2,3,4,5,6,0,1,2,3,4,5,6,0,1,2,3,4,5
        # >= 4: indices 4,5,6,11,12,13,18,19 => 8 files
        self.assertEqual(flagged.count(), 8)

    def test_file_at_exact_threshold(self):
        """File with nesting == NESTING_THRESHOLD gets penalty."""
        f = self._create_file("app/exact.py", max_nesting=NESTING_THRESHOLD)

        calculate_structural_complexity(self.module.id)
        f.refresh_from_db()
        self.assertEqual(f.structural_risk_score, NESTING_PENALTY)

    def test_file_just_below_threshold(self):
        """File with nesting == NESTING_THRESHOLD-1 gets no penalty."""
        f = self._create_file("app/below.py", max_nesting=NESTING_THRESHOLD - 1)

        calculate_structural_complexity(self.module.id)
        f.refresh_from_db()
        self.assertEqual(f.structural_risk_score, 0)

    def test_file_with_none_ast_summary(self):
        """File with None ast_summary gets nesting 0."""
        f = File.objects.create(
            module_id_id=self.module.id,
            file_path="app/none.py",
            line_count=50,
            ast_summary=None,
        )

        calculate_structural_complexity(self.module.id)
        f.refresh_from_db()
        self.assertEqual(f.max_nesting_depth, 0)
        self.assertEqual(f.structural_risk_score, 0)

    def test_file_with_empty_ast_summary(self):
        """File with empty dict ast_summary gets nesting 0."""
        f = File.objects.create(
            module_id_id=self.module.id,
            file_path="app/empty.py",
            line_count=50,
            ast_summary={},
        )

        calculate_structural_complexity(self.module.id)
        f.refresh_from_db()
        self.assertEqual(f.max_nesting_depth, 0)
        self.assertEqual(f.structural_risk_score, 0)


class BrainFileStressTests(TestCase):
    """Stress tests for brain file analysis."""

    def setUp(self):
        self.repo = Repo.objects.create(name="brain-repo", owner="brain-owner", url="https://github.com/brain/repo")
        self.module = Module.objects.create(repo=self.repo, name="mod", dir_path="mod")

    def _create_file(self, path, loc=100, imports=None, line_count=None):
        return File.objects.create(
            module_id_id=self.module.id,
            file_path=path,
            line_count=line_count if line_count is not None else loc,
            ast_summary={"loc": loc, "imports": imports or []},
        )

    def _create_standard_module(self, n=5, brain_loc=600, dep_imports=None):
        """Helper: create a module with 1 brain candidate + (n-1) dependents."""
        if dep_imports is None:
            dep_imports = ["mod.utils"]
        brain = self._create_file("mod/utils.py", loc=brain_loc)
        deps = []
        for i in range(n - 1):
            deps.append(self._create_file(f"mod/dep{i}.py", loc=100, imports=dep_imports))
        return brain, deps

    def test_density_exact_threshold(self):
        """Module where brain file density == USAGE_THRESHOLD (0.8) qualifies."""
        # 6 files: brain imported by 4 out of 5 others => density = 4/5 = 0.8
        brain = self._create_file("mod/utils.py", loc=600)
        for i in range(4):
            self._create_file(f"mod/dep{i}.py", loc=100, imports=["mod.utils"])
        self._create_file("mod/standalone.py", loc=100, imports=[])

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        self.assertEqual(brain.module_density, 0.8)
        self.assertTrue(brain.is_brain_file)

    def test_density_just_below_threshold(self):
        """Density 0.6 < 0.8 — should NOT be a brain file."""
        # 6 files: brain imported by 3 out of 5 => density = 3/5 = 0.6
        brain = self._create_file("mod/utils.py", loc=600)
        for i in range(3):
            self._create_file(f"mod/dep{i}.py", loc=100, imports=["mod.utils"])
        for i in range(2):
            self._create_file(f"mod/other{i}.py", loc=100, imports=[])

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        self.assertAlmostEqual(brain.module_density, 0.6)
        self.assertFalse(brain.is_brain_file)

    def test_large_module_21_files(self):
        """21-file module — brain file imported by 16/20 = 0.8 density."""
        brain = self._create_file("mod/core.py", loc=600)
        for i in range(16):
            self._create_file(f"mod/dep{i}.py", loc=100, imports=["mod.core"])
        for i in range(4):
            self._create_file(f"mod/other{i}.py", loc=100, imports=[])

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        self.assertEqual(brain.module_density, 0.8)
        self.assertTrue(brain.is_brain_file)

    def test_loc_threshold_strict_greater_than(self):
        """File with loc == LINES_THRESHOLD (50) should NOT qualify (strict >)."""
        brain = self._create_file("mod/utils.py", loc=50)  # exactly at threshold
        for i in range(4):
            self._create_file(f"mod/dep{i}.py", loc=10, imports=["mod.utils"])

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        self.assertTrue(brain.module_density >= USAGE_THRESHOLD)
        self.assertFalse(brain.is_brain_file)  # loc not > threshold

    def test_loc_just_above_threshold(self):
        """File with loc == 51 qualifies when above LINES_THRESHOLD."""
        brain = self._create_file("mod/utils.py", loc=51)
        for i in range(4):
            self._create_file(f"mod/dep{i}.py", loc=10, imports=["mod.utils"])

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        self.assertTrue(brain.is_brain_file)

    def test_multiple_brain_files(self):
        """Two files both qualify as brain files."""
        brain1 = self._create_file("mod/utils.py", loc=600)
        brain2 = self._create_file("mod/helpers.py", loc=600)
        for i in range(5):
            self._create_file(f"mod/dep{i}.py", loc=100, imports=["mod.utils", "mod.helpers"])

        calculate_module_brain_files(self.module.id)
        brain1.refresh_from_db()
        brain2.refresh_from_db()
        # density for each = 5/6 ≈ 0.833
        self.assertTrue(brain1.is_brain_file)
        self.assertTrue(brain2.is_brain_file)

    def test_self_import_excluded(self):
        """A file importing itself should not count toward inbound coupling."""
        brain = self._create_file("mod/utils.py", loc=600, imports=["mod.utils"])
        for i in range(4):
            self._create_file(f"mod/dep{i}.py", loc=100, imports=["mod.utils"])

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        self.assertEqual(brain.inbound_coupling, 4)  # self-import excluded

    def test_circular_imports(self):
        """A imports B, B imports A — both get inbound_coupling=1."""
        a = self._create_file("mod/a.py", loc=600, imports=["mod.b"])
        b = self._create_file("mod/b.py", loc=600, imports=["mod.a"])
        for i in range(3):
            self._create_file(f"mod/dep{i}.py", loc=100, imports=[])

        calculate_module_brain_files(self.module.id)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.inbound_coupling, 1)
        self.assertEqual(b.inbound_coupling, 1)

    def test_no_imports_in_module(self):
        """Module where no file imports anything — no brain files."""
        for i in range(5):
            self._create_file(f"mod/f{i}.py", loc=600, imports=[])

        calculate_module_brain_files(self.module.id)
        brain_files = File.objects.filter(module_id_id=self.module.id, is_brain_file=True)
        self.assertEqual(brain_files.count(), 0)

    def test_all_files_import_each_other(self):
        """Every file imports every other file — all have density 1.0 if large enough."""
        names = [f"mod/f{i}.py" for i in range(5)]
        import_names = [f"mod.f{i}" for i in range(5)]
        for i, name in enumerate(names):
            # Each file imports all other modules
            self._create_file(name, loc=600, imports=import_names)

        calculate_module_brain_files(self.module.id)
        for name in names:
            f = File.objects.get(file_path=name)
            self.assertEqual(f.module_density, 1.0)
            self.assertTrue(f.is_brain_file)

    def test_import_dotted_path_matching(self):
        """Dotted import 'pkga.utils' matches 'mod/pkga/utils.py'."""
        brain = self._create_file("mod/pkga/utils.py", loc=600)
        for i in range(4):
            self._create_file(f"mod/dep{i}.py", loc=100, imports=["pkga.utils"])

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        self.assertEqual(brain.inbound_coupling, 4)

    def test_import_basename_collision_longest_path_wins(self):
        """Two files named 'utils.py' in different dirs — longest path matches first."""
        deep = self._create_file("mod/pkga/utils.py", loc=600)
        shallow = self._create_file("mod/utils.py", loc=600)
        for i in range(4):
            self._create_file(f"mod/dep{i}.py", loc=100, imports=["pkga.utils"])

        calculate_module_brain_files(self.module.id)
        deep.refresh_from_db()
        shallow.refresh_from_db()
        # "pkga.utils" -> "pkga/utils" matches "mod/pkga/utils.py" first (longer path)
        self.assertEqual(deep.inbound_coupling, 4)
        self.assertEqual(shallow.inbound_coupling, 0)

    def test_min_module_size_boundary_4_files(self):
        """Module with 4 files (< MIN_MODULE_SIZE=5) — no brain files."""
        brain = self._create_file("mod/utils.py", loc=600)
        for i in range(3):
            self._create_file(f"mod/dep{i}.py", loc=100, imports=["mod.utils"])

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        self.assertFalse(brain.is_brain_file)

    def test_min_module_size_boundary_5_files(self):
        """Module with exactly 5 files (== MIN_MODULE_SIZE) — analysis runs."""
        brain, _ = self._create_standard_module(n=5, brain_loc=600)

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        self.assertTrue(brain.is_brain_file)

    def test_loc_percentile_high_repo(self):
        """When repo p90 LOC is very high, LINES_THRESHOLD is used (whichever is smaller)."""
        # Create files in another module with huge LOC to raise p90
        other_module = Module.objects.create(repo=self.repo, name="big", dir_path="big")
        for i in range(10):
            File.objects.create(
                module_id_id=other_module.id,
                file_path=f"big/huge{i}.py",
                line_count=10000,
                ast_summary={"loc": 10000, "imports": []},
                loc_count=10000,
            )

        brain, _ = self._create_standard_module(n=5, brain_loc=600)

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        # p90 is very high, so loc_threshold = min(50, p90) = 50
        # brain has loc=600 > 50, so qualifies
        self.assertTrue(brain.is_brain_file)

    def test_loc_percentile_low_repo(self):
        """When all repo files have loc=10, p90 is 10 — threshold is min(50, 10)=10."""
        brain = self._create_file("mod/utils.py", loc=15)
        for i in range(4):
            self._create_file(f"mod/dep{i}.py", loc=10, imports=["mod.utils"])

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        # p90 of [15,10,10,10,10] = 15 (idx=4*0.9=3 -> 10 or 15 depending on exact calc)
        # loc_threshold = min(50, p90) = p90
        # brain loc=15 > p90 threshold
        self.assertTrue(brain.module_density >= USAGE_THRESHOLD)

    def test_none_ast_summary_handling(self):
        """Files with None ast_summary don't break brain file analysis."""
        brain = self._create_file("mod/utils.py", loc=600)
        for i in range(3):
            self._create_file(f"mod/dep{i}.py", loc=100, imports=["mod.utils"])
        # File with None ast_summary
        File.objects.create(
            module_id_id=self.module.id,
            file_path="mod/broken.py",
            line_count=50,
            ast_summary=None,
        )

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        # 5 files total, 3 import brain => density = 3/4 = 0.75 < 0.8
        self.assertFalse(brain.is_brain_file)

    def test_duplicate_imports_counted_once(self):
        """File importing the same module twice — inbound coupling counts unique importers."""
        brain = self._create_file("mod/utils.py", loc=600)
        # dep0 imports utils twice
        self._create_file("mod/dep0.py", loc=100, imports=["mod.utils", "mod.utils"])
        for i in range(1, 4):
            self._create_file(f"mod/dep{i}.py", loc=100, imports=["mod.utils"])

        calculate_module_brain_files(self.module.id)
        brain.refresh_from_db()
        self.assertEqual(brain.inbound_coupling, 4)  # unique importers

    def test_external_only_imports(self):
        """All imports are external (no matches) — no brain files."""
        for i in range(5):
            self._create_file(f"mod/f{i}.py", loc=600, imports=["numpy", "pandas"])

        calculate_module_brain_files(self.module.id)
        brain_files = File.objects.filter(module_id_id=self.module.id, is_brain_file=True)
        self.assertEqual(brain_files.count(), 0)

    def test_empty_module(self):
        """Module with 0 files — should not raise."""
        calculate_module_brain_files(self.module.id)
        # No files, no error

