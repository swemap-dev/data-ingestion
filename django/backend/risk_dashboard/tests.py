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
from git_blame_ingestion_app.models import Repo, Module, File, PullRequest, PullRequestFile
from .services.brain_file_analysis import calculate_structural_hubs

class StructuralHubAnalysisTests(TestCase):
    def setUp(self):
        self.repo = Repo.objects.create(name="test-repo", owner="test-owner", url="https://github.com/test-owner/test-repo")
        self.module = Module.objects.create(repo=self.repo, name="src", dir_path="src")

        # 5 files: utils.py imported by all 4 others
        self.hub_file = File.objects.create(
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

    def test_global_hub_by_relative_threshold(self):
        """utils.py imported by 4/5 = 80% of repo files → Global Hub."""
        calculate_structural_hubs(self.repo.id)

        self.hub_file.refresh_from_db()
        self.dep1.refresh_from_db()

        self.assertEqual(self.hub_file.hub_type, 'GLOBAL')
        self.assertEqual(self.hub_file.inbound_coupling, 4)
        self.assertEqual(self.hub_file.module_density, 1.0)

        self.assertIsNone(self.dep1.hub_type)
        self.assertEqual(self.dep1.inbound_coupling, 0)

    def test_non_hub_files_have_no_type(self):
        """Files with no importers should have hub_type=None."""
        calculate_structural_hubs(self.repo.id)
        self.dep1.refresh_from_db()
        self.assertIsNone(self.dep1.hub_type)


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
from risk_dashboard.services.brain_file_analysis import calculate_structural_hubs


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


class StructuralHubStressTests(TestCase):
    """Stress tests for structural hub classification (Global, Boundary, Local)."""

    def setUp(self):
        self.repo = Repo.objects.create(name="hub-repo", owner="hub-owner", url="https://github.com/hub/repo")
        self.mod_a = Module.objects.create(repo=self.repo, name="mod_a", dir_path="mod_a")
        self.mod_b = Module.objects.create(repo=self.repo, name="mod_b", dir_path="mod_b")

    def _create_file(self, module, path, loc=100, imports=None):
        return File.objects.create(
            module_id_id=module.id,
            file_path=path,
            line_count=loc,
            ast_summary={"loc": loc, "imports": imports or []},
        )

    # ── Global Hub Tests ─────────────────────────────────────────────

    def test_global_hub_by_relative_threshold(self):
        """File imported by >= 15% of repo files → Global Hub."""
        # 7 files, utils imported by 2 → 2/7 ≈ 28.6% >= 15%
        hub = self._create_file(self.mod_a, "mod_a/utils.py")
        self._create_file(self.mod_a, "mod_a/a.py", imports=["mod_a.utils"])
        self._create_file(self.mod_a, "mod_a/b.py", imports=["mod_a.utils"])
        self._create_file(self.mod_a, "mod_a/c.py")
        self._create_file(self.mod_b, "mod_b/x.py")
        self._create_file(self.mod_b, "mod_b/y.py")
        self._create_file(self.mod_b, "mod_b/z.py")

        calculate_structural_hubs(self.repo.id)
        hub.refresh_from_db()
        self.assertEqual(hub.hub_type, 'GLOBAL')
        self.assertEqual(hub.inbound_coupling, 2)

    def test_global_hub_by_absolute_threshold(self):
        """File imported by >= 30 files → Global Hub (absolute threshold)."""
        hub = self._create_file(self.mod_a, "mod_a/core.py")
        # Create 200 files to make relative threshold irrelevant, 30 import core
        for i in range(30):
            self._create_file(self.mod_a, f"mod_a/dep{i}.py", imports=["mod_a.core"])
        for i in range(170):
            self._create_file(self.mod_b, f"mod_b/other{i}.py")

        calculate_structural_hubs(self.repo.id)
        hub.refresh_from_db()
        self.assertEqual(hub.hub_type, 'GLOBAL')
        self.assertEqual(hub.inbound_coupling, 30)

    def test_below_global_thresholds_not_global(self):
        """File just below both global thresholds → Not Global."""
        # 100 files, imported by 14 → 14% < 15%, 14 < 30
        hub = self._create_file(self.mod_a, "mod_a/utils.py")
        for i in range(14):
            self._create_file(self.mod_a, f"mod_a/dep{i}.py", imports=["mod_a.utils"])
        for i in range(85):
            self._create_file(self.mod_b, f"mod_b/other{i}.py")

        calculate_structural_hubs(self.repo.id)
        hub.refresh_from_db()
        self.assertNotEqual(hub.hub_type, 'GLOBAL')

    # ── Boundary Hub Tests ───────────────────────────────────────────

    def test_boundary_hub_classification(self):
        """File with E_F >= 5 and E_F/(I_F+E_F) >= 80% → Boundary Hub."""
        # 100 total files so relative threshold won't trigger global (need < 15%)
        facade = self._create_file(self.mod_a, "mod_a/api.py")
        # 6 external importers from mod_b
        for i in range(6):
            self._create_file(self.mod_b, f"mod_b/consumer{i}.py", imports=["mod_a.api"])
        # 1 internal importer → ratio = 6/7 ≈ 85.7% >= 80%
        self._create_file(self.mod_a, "mod_a/internal.py", imports=["mod_a.api"])
        # Pad repo to keep below global threshold
        for i in range(92):
            self._create_file(self.mod_b, f"mod_b/pad{i}.py")

        calculate_structural_hubs(self.repo.id)
        facade.refresh_from_db()
        self.assertEqual(facade.hub_type, 'BOUNDARY')
        self.assertEqual(facade.external_imports, 6)
        self.assertEqual(facade.internal_imports, 1)

    def test_boundary_hub_needs_min_external(self):
        """File with E_F < 5 should NOT be a Boundary Hub even with high ratio."""
        facade = self._create_file(self.mod_a, "mod_a/api.py")
        # Only 4 external importers (< 5)
        for i in range(4):
            self._create_file(self.mod_b, f"mod_b/consumer{i}.py", imports=["mod_a.api"])
        for i in range(95):
            self._create_file(self.mod_b, f"mod_b/pad{i}.py")

        calculate_structural_hubs(self.repo.id)
        facade.refresh_from_db()
        self.assertNotEqual(facade.hub_type, 'BOUNDARY')

    def test_boundary_hub_needs_high_ratio(self):
        """File with E_F >= 5 but ratio < 80% should NOT be Boundary."""
        facade = self._create_file(self.mod_a, "mod_a/api.py")
        # 5 external, 3 internal → ratio = 5/8 = 62.5% < 80%
        for i in range(5):
            self._create_file(self.mod_b, f"mod_b/consumer{i}.py", imports=["mod_a.api"])
        for i in range(3):
            self._create_file(self.mod_a, f"mod_a/dep{i}.py", imports=["mod_a.api"])
        for i in range(91):
            self._create_file(self.mod_b, f"mod_b/pad{i}.py")

        calculate_structural_hubs(self.repo.id)
        facade.refresh_from_db()
        self.assertNotEqual(facade.hub_type, 'BOUNDARY')

    # ── Local Hub Tests ──────────────────────────────────────────────

    def test_local_hub_classification(self):
        """File imported by >= 70% siblings with >= 50% internal → Local Hub."""
        # Module with 5 files (4 siblings). 3 internal importers.
        # I_F/S_M = 3/4 = 0.75 >= 0.70. I_F/(I_F+E_F) = 3/3 = 1.0 >= 0.50
        hub = self._create_file(self.mod_a, "mod_a/state.py")
        for i in range(3):
            self._create_file(self.mod_a, f"mod_a/dep{i}.py", imports=["mod_a.state"])
        self._create_file(self.mod_a, "mod_a/standalone.py")
        # Pad repo to prevent global hub classification
        for i in range(95):
            self._create_file(self.mod_b, f"mod_b/pad{i}.py")

        calculate_structural_hubs(self.repo.id)
        hub.refresh_from_db()
        self.assertEqual(hub.hub_type, 'LOCAL')
        self.assertEqual(hub.internal_imports, 3)

    def test_local_hub_needs_min_module_size(self):
        """Module with < 3 siblings (S_M < 3) cannot have Local Hubs."""
        # 3 files in module → S_M = 2 < 3
        hub = self._create_file(self.mod_a, "mod_a/state.py")
        self._create_file(self.mod_a, "mod_a/a.py", imports=["mod_a.state"])
        self._create_file(self.mod_a, "mod_a/b.py", imports=["mod_a.state"])
        for i in range(97):
            self._create_file(self.mod_b, f"mod_b/pad{i}.py")

        calculate_structural_hubs(self.repo.id)
        hub.refresh_from_db()
        self.assertNotEqual(hub.hub_type, 'LOCAL')

    def test_local_hub_fails_internal_dominance(self):
        """File with mostly external usage should NOT be Local Hub."""
        hub = self._create_file(self.mod_a, "mod_a/state.py")
        # 3 internal importers (I_F/S_M would pass)
        for i in range(3):
            self._create_file(self.mod_a, f"mod_a/dep{i}.py", imports=["mod_a.state"])
        self._create_file(self.mod_a, "mod_a/standalone.py")
        # 4 external importers → I_F/(I_F+E_F) = 3/7 ≈ 0.43 < 0.50
        for i in range(4):
            self._create_file(self.mod_b, f"mod_b/ext{i}.py", imports=["mod_a.state"])
        for i in range(89):
            self._create_file(self.mod_b, f"mod_b/pad{i}.py")

        calculate_structural_hubs(self.repo.id)
        hub.refresh_from_db()
        self.assertNotEqual(hub.hub_type, 'LOCAL')

    # ── Edge Cases ───────────────────────────────────────────────────

    def test_self_import_excluded(self):
        """A file importing itself should not count toward inbound coupling."""
        hub = self._create_file(self.mod_a, "mod_a/utils.py", imports=["mod_a.utils"])
        self._create_file(self.mod_a, "mod_a/a.py", imports=["mod_a.utils"])

        calculate_structural_hubs(self.repo.id)
        hub.refresh_from_db()
        self.assertEqual(hub.inbound_coupling, 1)

    def test_circular_imports(self):
        """A imports B, B imports A — both get inbound_coupling=1."""
        a = self._create_file(self.mod_a, "mod_a/a.py", imports=["mod_a.b"])
        b = self._create_file(self.mod_a, "mod_a/b.py", imports=["mod_a.a"])

        calculate_structural_hubs(self.repo.id)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.inbound_coupling, 1)
        self.assertEqual(b.inbound_coupling, 1)

    def test_no_imports_no_hubs(self):
        """Repo where no file imports anything — no hubs."""
        for i in range(5):
            self._create_file(self.mod_a, f"mod_a/f{i}.py")

        calculate_structural_hubs(self.repo.id)
        hubs = File.objects.filter(module_id__repo_id=self.repo.id).exclude(hub_type=None)
        self.assertEqual(hubs.count(), 0)

    def test_import_dotted_path_matching(self):
        """Dotted import 'pkga.utils' matches 'mod_a/pkga/utils.py'."""
        target = self._create_file(self.mod_a, "mod_a/pkga/utils.py")
        self._create_file(self.mod_a, "mod_a/dep.py", imports=["pkga.utils"])

        calculate_structural_hubs(self.repo.id)
        target.refresh_from_db()
        self.assertEqual(target.inbound_coupling, 1)

    def test_import_basename_collision_longest_path_wins(self):
        """Two files named 'utils.py' — longest path matches first."""
        deep = self._create_file(self.mod_a, "mod_a/pkga/utils.py")
        shallow = self._create_file(self.mod_a, "mod_a/utils.py")
        self._create_file(self.mod_a, "mod_a/dep.py", imports=["pkga.utils"])

        calculate_structural_hubs(self.repo.id)
        deep.refresh_from_db()
        shallow.refresh_from_db()
        self.assertEqual(deep.inbound_coupling, 1)
        self.assertEqual(shallow.inbound_coupling, 0)

    def test_non_code_files_excluded(self):
        """Non-source files (e.g. .json) should not be classified as hubs."""
        config = self._create_file(self.mod_a, "mod_a/package.json")
        self._create_file(self.mod_a, "mod_a/a.py")

        calculate_structural_hubs(self.repo.id)
        config.refresh_from_db()
        self.assertIsNone(config.hub_type)
        self.assertEqual(config.inbound_coupling, 0)

    def test_duplicate_imports_counted_once(self):
        """File importing same module twice — counts as one unique importer."""
        target = self._create_file(self.mod_a, "mod_a/utils.py")
        self._create_file(self.mod_a, "mod_a/dep.py", imports=["mod_a.utils", "mod_a.utils"])

        calculate_structural_hubs(self.repo.id)
        target.refresh_from_db()
        self.assertEqual(target.inbound_coupling, 1)

    def test_external_only_imports_no_hubs(self):
        """Imports that don't match any repo file produce no hubs."""
        for i in range(5):
            self._create_file(self.mod_a, f"mod_a/f{i}.py", imports=["numpy", "pandas"])

        calculate_structural_hubs(self.repo.id)
        hubs = File.objects.filter(module_id__repo_id=self.repo.id).exclude(hub_type=None)
        self.assertEqual(hubs.count(), 0)

    def test_empty_repo(self):
        """Repo with 0 files — should not raise."""
        calculate_structural_hubs(self.repo.id)

    def test_none_ast_summary_handling(self):
        """Files with None ast_summary don't break analysis."""
        File.objects.create(
            module_id_id=self.mod_a.id,
            file_path="mod_a/broken.py",
            line_count=50,
            ast_summary=None,
        )
        self._create_file(self.mod_a, "mod_a/ok.py")

        calculate_structural_hubs(self.repo.id)
        # No crash is the assertion

    def test_global_hubs_excluded_from_local_metrics(self):
        """Global Hub importers should not inflate I_F/E_F for non-global files."""
        # Create a global hub (imported by many) that also imports a local file
        # The local file's metrics should not count the global hub as an importer
        global_hub = self._create_file(self.mod_a, "mod_a/config.py")
        local_file = self._create_file(self.mod_a, "mod_a/helper.py")

        # Make config.py a global hub by having many files import it
        for i in range(4):
            self._create_file(self.mod_a, f"mod_a/dep{i}.py", imports=["mod_a.config"])
        # Padding file so helper.py (1/7 = 14.3%) doesn't hit global threshold
        self._create_file(self.mod_a, "mod_a/standalone.py")
        # Also have config.py import helper.py
        global_hub.ast_summary = {"loc": 100, "imports": ["mod_a.helper"]}
        global_hub.save()

        # 7 total files in repo, config imported by 4 → 4/7 ≈ 57% >= 15% → Global
        calculate_structural_hubs(self.repo.id)

        global_hub.refresh_from_db()
        local_file.refresh_from_db()
        self.assertEqual(global_hub.hub_type, 'GLOBAL')
        # helper.py's adjusted I_F should exclude the global hub importer
        self.assertEqual(local_file.internal_imports, 0)

    def test_module_density_computation(self):
        """module_density should be I_F / (module_size - 1)."""
        hub = self._create_file(self.mod_a, "mod_a/core.py")
        for i in range(3):
            self._create_file(self.mod_a, f"mod_a/dep{i}.py", imports=["mod_a.core"])
        # 4 files in module, 3 import core → density = 3/3 = 1.0

        calculate_structural_hubs(self.repo.id)
        hub.refresh_from_db()
        self.assertEqual(hub.module_density, 1.0)

    # ── __init__.py import resolution tests ────────────────────────────

    def test_init_py_receives_package_level_imports(self):
        """'from mod_a.pkg import Solver' resolves to __init__.py (not siblings)."""
        # Parser emits "mod_a.pkg" for "from mod_a.pkg import Solver"
        init_file = self._create_file(self.mod_a, "mod_a/pkg/__init__.py")
        self._create_file(self.mod_a, "mod_a/pkg/helper.py")

        self._create_file(self.mod_b, "mod_b/a.py", imports=["mod_a.pkg"])
        self._create_file(self.mod_b, "mod_b/b.py", imports=["mod_a.pkg"])

        calculate_structural_hubs(self.repo.id)
        init_file.refresh_from_db()
        self.assertEqual(init_file.inbound_coupling, 2)

    def test_import_submodule_file_not_init(self):
        """'from mod_a.pkg.yaml_utils import X' resolves to yaml_utils.py, not __init__.py."""
        # Parser emits "mod_a.pkg.yaml_utils" for "from mod_a.pkg.yaml_utils import load"
        init_file = self._create_file(self.mod_a, "mod_a/pkg/__init__.py")
        sibling = self._create_file(self.mod_a, "mod_a/pkg/yaml_utils.py")

        for i in range(5):
            self._create_file(self.mod_b, f"mod_b/consumer{i}.py",
                              imports=["mod_a.pkg.yaml_utils"])
        for i in range(93):
            self._create_file(self.mod_b, f"mod_b/pad{i}.py")

        calculate_structural_hubs(self.repo.id)
        init_file.refresh_from_db()
        sibling.refresh_from_db()

        self.assertEqual(sibling.inbound_coupling, 5)
        self.assertEqual(init_file.inbound_coupling, 0)

    def test_init_py_not_matched_by_substring(self):
        """__init__.py should not be matched by loose substring of a sibling import."""
        # Verifies exact stem matching prevents the old substring bug
        init_file = self._create_file(self.mod_a, "mod_a/pkg/__init__.py")
        target = self._create_file(self.mod_a, "mod_a/pkg/target.py")
        self._create_file(self.mod_a, "mod_a/pkg/other.py")

        self._create_file(self.mod_b, "mod_b/dep.py", imports=["mod_a.pkg.target"])

        calculate_structural_hubs(self.repo.id)
        init_file.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(target.inbound_coupling, 1)
        self.assertEqual(init_file.inbound_coupling, 0)


# ──────────────────────────────────────────────────────────────────────
# Change Frequency Tests
# ──────────────────────────────────────────────────────────────────────

from risk_dashboard.services.change_frequency import decay_weight, calculate_change_frequency

CHANGE_FREQ_RISK_CONFIG = {
    "CHURN_DECAY_H": 1.0,
    "CHURN_DECAY_L": 0.1,
    "CHURN_DECAY_X0": 21,
    "CHURN_DECAY_K": 0.5,
    "CHURN_LOOKBACK_DAYS": 180,
    "CHURN_HIGH_CAP_THRESHOLD": 2.0,
    "CHURN_HIGH_CAP_FALLBACK": 7,
    "CHURN_LOW_CAP_THRESHOLD": 0.1,
    "CHURN_LOW_CAP_FALLBACK": 3,
    "CHURN_QUIET_VARIANCE": 0.01,
    "CHURN_QUIET_DEFAULT": 3,
    "CHURN_HOTSPOT_THRESHOLD": 8,
}


@override_settings(RISK_CONFIG=CHANGE_FREQ_RISK_CONFIG)
class DecayWeightTests(SimpleTestCase):
    """Unit tests for the sigmoid decay_weight function."""

    def test_recent_change_near_high(self):
        """t=0 should produce weight close to H (1.0)."""
        w = decay_weight(0)
        self.assertAlmostEqual(w, 1.0, delta=0.05)

    def test_midpoint_at_x0(self):
        """At t=x0 the sigmoid midpoint is (H+L)/2 = 0.55."""
        w = decay_weight(21)
        self.assertAlmostEqual(w, 0.55, places=5)

    def test_old_change_near_low(self):
        """t=180 should produce weight close to L (0.1)."""
        w = decay_weight(180)
        self.assertAlmostEqual(w, 0.1, delta=0.01)

    def test_monotonically_decreasing(self):
        """Weight non-increasing as t increases (positive k). Strict in active range."""
        prev = decay_weight(0)
        for t in range(1, 60):
            cur = decay_weight(t)
            self.assertLess(cur, prev, f"decay_weight({t}) >= decay_weight({t-1})")
            prev = cur
        # Past the sigmoid tail, values flatten at L — just check non-increasing
        for t in range(60, 200, 5):
            cur = decay_weight(t)
            self.assertLessEqual(cur, prev)
            prev = cur

    def test_symmetry_around_x0(self):
        """W(x0-d) + W(x0+d) ≈ H + L for any d (sigmoid symmetry)."""
        H, L, x0 = 1.0, 0.1, 21
        for d in [1, 5, 10, 15, 20]:
            total = decay_weight(x0 - d) + decay_weight(x0 + d)
            self.assertAlmostEqual(total, H + L, places=5)

    def test_custom_parameters(self):
        """Override H, L, x0, k directly."""
        w = decay_weight(0, H=2.0, L=0.0, x0=10, k=1.0)
        self.assertAlmostEqual(w, 2.0, delta=0.01)

    def test_k_zero_returns_midpoint(self):
        """k=0 means no decay — every t returns (H+L)/2."""
        for t in [0, 21, 100]:
            w = decay_weight(t, H=1.0, L=0.1, x0=21, k=0)
            self.assertAlmostEqual(w, 0.55, places=5)

    def test_negative_t(self):
        """Negative t (future) should return value > weight at t=0."""
        self.assertGreater(decay_weight(-10), decay_weight(0))

    def test_very_large_k_step_function(self):
        """Large k produces near step-function: ~H before x0, ~L after."""
        self.assertAlmostEqual(decay_weight(20, k=100), 1.0, delta=0.01)
        self.assertAlmostEqual(decay_weight(22, k=100), 0.1, delta=0.01)

    def test_output_always_between_L_and_H(self):
        """Weight is always in [L, H] for any non-negative t."""
        for t in range(0, 365):
            w = decay_weight(t)
            self.assertGreaterEqual(w, 0.1)
            self.assertLessEqual(w, 1.0)


@override_settings(RISK_CONFIG=CHANGE_FREQ_RISK_CONFIG)
class ChangeFrequencyBasicTests(TestCase):
    """Basic functionality tests for calculate_change_frequency."""

    def setUp(self):
        self.repo = Repo.objects.create(name="cf-repo", owner="cf-owner", url="https://github.com/cf/repo")
        self.module = Module.objects.create(repo=self.repo, name="src", dir_path="src")

    def _create_file(self, path):
        return File.objects.create(
            module_id_id=self.module.id,
            file_path=path,
            line_count=100,
        )

    def _create_pr(self, number, merged_days_ago, is_revert=False, file_paths=None):
        pr = PullRequest.objects.create(
            repo=self.repo,
            github_pr_number=number,
            title=f"PR #{number}",
            merged_at=timezone.now() - timedelta(days=merged_days_ago),
            is_revert=is_revert,
        )
        for fp in (file_paths or []):
            PullRequestFile.objects.create(pull_request=pr, file_path=fp)
        return pr

    def test_no_files_returns_early(self):
        """Repo with no File records — should return without error."""
        self._create_pr(1, merged_days_ago=5, file_paths=["src/a.py"])
        calculate_change_frequency(self.repo.id)
        # No assertions needed — just no crash

    def test_no_prs_all_raw_zero(self):
        """No PRs in lookback window — all files get raw score 0."""
        f1 = self._create_file("src/a.py")
        f2 = self._create_file("src/b.py")
        calculate_change_frequency(self.repo.id)
        f1.refresh_from_db()
        f2.refresh_from_db()
        self.assertEqual(f1.change_frequency_raw, 0.0)
        self.assertEqual(f2.change_frequency_raw, 0.0)

    def test_single_file_single_pr(self):
        """One file changed in one PR — should get a non-zero raw score."""
        f = self._create_file("src/a.py")
        self._create_pr(1, merged_days_ago=1, file_paths=["src/a.py"])
        calculate_change_frequency(self.repo.id)
        f.refresh_from_db()
        self.assertGreater(f.change_frequency_raw, 0.0)

    def test_file_not_in_pr_gets_zero(self):
        """File not touched by any PR gets raw score 0."""
        changed = self._create_file("src/changed.py")
        untouched = self._create_file("src/untouched.py")
        self._create_pr(1, merged_days_ago=1, file_paths=["src/changed.py"])
        calculate_change_frequency(self.repo.id)
        changed.refresh_from_db()
        untouched.refresh_from_db()
        self.assertGreater(changed.change_frequency_raw, 0.0)
        self.assertEqual(untouched.change_frequency_raw, 0.0)

    def test_multiple_prs_accumulate(self):
        """File changed in multiple PRs — raw scores accumulate."""
        f = self._create_file("src/a.py")
        self._create_file("src/b.py")  # need 2+ files to avoid quiet repo
        self._create_pr(1, merged_days_ago=1, file_paths=["src/a.py"])
        self._create_pr(2, merged_days_ago=2, file_paths=["src/a.py"])
        self._create_pr(3, merged_days_ago=3, file_paths=["src/a.py"])
        calculate_change_frequency(self.repo.id)
        f.refresh_from_db()
        # Three decayed weights summed
        expected = decay_weight(1) + decay_weight(2) + decay_weight(3)
        self.assertAlmostEqual(f.change_frequency_raw, expected, delta=0.05)

    def test_recent_pr_weights_more_than_old(self):
        """File changed 1 day ago has higher raw score than one changed 100 days ago."""
        f_recent = self._create_file("src/recent.py")
        f_old = self._create_file("src/old.py")
        self._create_pr(1, merged_days_ago=1, file_paths=["src/recent.py"])
        self._create_pr(2, merged_days_ago=100, file_paths=["src/old.py"])
        calculate_change_frequency(self.repo.id)
        f_recent.refresh_from_db()
        f_old.refresh_from_db()
        self.assertGreater(f_recent.change_frequency_raw, f_old.change_frequency_raw)


@override_settings(RISK_CONFIG=CHANGE_FREQ_RISK_CONFIG)
class ChangeFrequencyRevertTests(TestCase):
    """Revert PRs should be excluded from change frequency."""

    def setUp(self):
        self.repo = Repo.objects.create(name="rev-repo", owner="rev-owner", url="https://github.com/rev/repo")
        self.module = Module.objects.create(repo=self.repo, name="src", dir_path="src")

    def _create_file(self, path):
        return File.objects.create(module_id_id=self.module.id, file_path=path, line_count=100)

    def _create_pr(self, number, merged_days_ago, is_revert=False, file_paths=None):
        pr = PullRequest.objects.create(
            repo=self.repo,
            github_pr_number=number,
            title=f"PR #{number}",
            merged_at=timezone.now() - timedelta(days=merged_days_ago),
            is_revert=is_revert,
        )
        for fp in (file_paths or []):
            PullRequestFile.objects.create(pull_request=pr, file_path=fp)
        return pr

    def test_revert_pr_excluded(self):
        """Revert PRs do not contribute to raw scores."""
        f = self._create_file("src/a.py")
        self._create_file("src/other.py")
        self._create_pr(1, merged_days_ago=1, is_revert=True, file_paths=["src/a.py"])
        calculate_change_frequency(self.repo.id)
        f.refresh_from_db()
        self.assertEqual(f.change_frequency_raw, 0.0)

    def test_mix_revert_and_normal(self):
        """Only non-revert PRs contribute to raw score."""
        f = self._create_file("src/a.py")
        self._create_file("src/other.py")
        self._create_pr(1, merged_days_ago=1, is_revert=False, file_paths=["src/a.py"])
        self._create_pr(2, merged_days_ago=2, is_revert=True, file_paths=["src/a.py"])
        calculate_change_frequency(self.repo.id)
        f.refresh_from_db()
        # Only PR #1 counts
        expected = decay_weight(1)
        self.assertAlmostEqual(f.change_frequency_raw, expected, delta=0.05)


@override_settings(RISK_CONFIG=CHANGE_FREQ_RISK_CONFIG)
class ChangeFrequencyLookbackTests(TestCase):
    """Tests for lookback window boundaries."""

    def setUp(self):
        self.repo = Repo.objects.create(name="lb-repo", owner="lb-owner", url="https://github.com/lb/repo")
        self.module = Module.objects.create(repo=self.repo, name="src", dir_path="src")

    def _create_file(self, path):
        return File.objects.create(module_id_id=self.module.id, file_path=path, line_count=100)

    def _create_pr(self, number, merged_days_ago, file_paths=None):
        pr = PullRequest.objects.create(
            repo=self.repo,
            github_pr_number=number,
            title=f"PR #{number}",
            merged_at=timezone.now() - timedelta(days=merged_days_ago),
        )
        for fp in (file_paths or []):
            PullRequestFile.objects.create(pull_request=pr, file_path=fp)
        return pr

    def test_pr_outside_lookback_excluded(self):
        """PR merged 200 days ago (> 180 lookback) should be excluded."""
        f = self._create_file("src/a.py")
        self._create_file("src/b.py")
        self._create_pr(1, merged_days_ago=200, file_paths=["src/a.py"])
        calculate_change_frequency(self.repo.id)
        f.refresh_from_db()
        self.assertEqual(f.change_frequency_raw, 0.0)

    def test_pr_inside_lookback_included(self):
        """PR merged 10 days ago should be included."""
        f = self._create_file("src/a.py")
        self._create_file("src/b.py")
        self._create_pr(1, merged_days_ago=10, file_paths=["src/a.py"])
        calculate_change_frequency(self.repo.id)
        f.refresh_from_db()
        self.assertGreater(f.change_frequency_raw, 0.0)

    def test_pr_at_lookback_boundary(self):
        """PR merged exactly 180 days ago — borderline inclusion."""
        f = self._create_file("src/a.py")
        self._create_file("src/b.py")
        self._create_pr(1, merged_days_ago=180, file_paths=["src/a.py"])
        calculate_change_frequency(self.repo.id)
        f.refresh_from_db()
        # merged_at >= cutoff, so included (equal is included by __gte)
        self.assertGreaterEqual(f.change_frequency_raw, 0.0)


@override_settings(RISK_CONFIG=CHANGE_FREQ_RISK_CONFIG)
class ChangeFrequencyQuietRepoTests(TestCase):
    """Tests for quiet repo detection (low variance)."""

    def setUp(self):
        self.repo = Repo.objects.create(name="q-repo", owner="q-owner", url="https://github.com/q/repo")
        self.module = Module.objects.create(repo=self.repo, name="src", dir_path="src")

    def _create_file(self, path):
        return File.objects.create(module_id_id=self.module.id, file_path=path, line_count=100)

    def _create_pr(self, number, merged_days_ago, file_paths=None):
        pr = PullRequest.objects.create(
            repo=self.repo,
            github_pr_number=number,
            title=f"PR #{number}",
            merged_at=timezone.now() - timedelta(days=merged_days_ago),
        )
        for fp in (file_paths or []):
            PullRequestFile.objects.create(pull_request=pr, file_path=fp)
        return pr

    def test_no_prs_quiet_repo(self):
        """No PRs means all raw=0, variance=0 → quiet default."""
        f1 = self._create_file("src/a.py")
        f2 = self._create_file("src/b.py")
        calculate_change_frequency(self.repo.id)
        f1.refresh_from_db()
        f2.refresh_from_db()
        self.assertEqual(f1.change_frequency_score, 3)  # CHURN_QUIET_DEFAULT
        self.assertEqual(f2.change_frequency_score, 3)

    def test_all_files_changed_equally_quiet(self):
        """All files changed in the same PR → all raw scores equal → variance=0."""
        files = [self._create_file(f"src/f{i}.py") for i in range(5)]
        self._create_pr(1, merged_days_ago=5, file_paths=[f"src/f{i}.py" for i in range(5)])
        calculate_change_frequency(self.repo.id)
        for f in files:
            f.refresh_from_db()
            self.assertEqual(f.change_frequency_score, 3)

    def test_single_file_quiet(self):
        """Single file → variance=0 → quiet default."""
        f = self._create_file("src/only.py")
        self._create_pr(1, merged_days_ago=1, file_paths=["src/only.py"])
        calculate_change_frequency(self.repo.id)
        f.refresh_from_db()
        self.assertEqual(f.change_frequency_score, 3)

    def test_high_variance_not_quiet(self):
        """One file changed many times, others not → high variance → not quiet."""
        hot = self._create_file("src/hot.py")
        cold = self._create_file("src/cold.py")
        for i in range(10):
            self._create_pr(i + 1, merged_days_ago=i + 1, file_paths=["src/hot.py"])
        calculate_change_frequency(self.repo.id)
        hot.refresh_from_db()
        cold.refresh_from_db()
        # Scores should differ — not quiet default
        self.assertNotEqual(hot.change_frequency_score, cold.change_frequency_score)


@override_settings(RISK_CONFIG=CHANGE_FREQ_RISK_CONFIG)
class ChangeFrequencyPercentileTests(TestCase):
    """Tests for percentile ranking and capped normalization."""

    def setUp(self):
        self.repo = Repo.objects.create(name="pct-repo", owner="pct-owner", url="https://github.com/pct/repo")
        self.module = Module.objects.create(repo=self.repo, name="src", dir_path="src")

    def _create_file(self, path):
        return File.objects.create(module_id_id=self.module.id, file_path=path, line_count=100)

    def _create_pr(self, number, merged_days_ago, file_paths=None):
        pr = PullRequest.objects.create(
            repo=self.repo,
            github_pr_number=number,
            title=f"PR #{number}",
            merged_at=timezone.now() - timedelta(days=merged_days_ago),
        )
        for fp in (file_paths or []):
            PullRequestFile.objects.create(pull_request=pr, file_path=fp)
        return pr

    def test_highest_scorer_gets_max(self):
        """File with highest raw score gets effective_max."""
        hot = self._create_file("src/hot.py")
        cold = self._create_file("src/cold.py")
        for i in range(5):
            self._create_pr(i + 1, merged_days_ago=i + 1, file_paths=["src/hot.py"])
        calculate_change_frequency(self.repo.id)
        hot.refresh_from_db()
        cold.refresh_from_db()
        # hot has max raw (>2.0 → effective_max=10), cold has 0 → effective_min=1
        self.assertEqual(hot.change_frequency_score, 10.0)
        self.assertEqual(cold.change_frequency_score, 1.0)

    def test_score_ordering_preserved(self):
        """Files with more changes should get higher scores."""
        f_high = self._create_file("src/high.py")
        f_mid = self._create_file("src/mid.py")
        f_low = self._create_file("src/low.py")
        # high: 3 PRs, mid: 1 PR, low: 0 PRs
        for i in range(3):
            self._create_pr(i + 1, merged_days_ago=i + 1, file_paths=["src/high.py"])
        self._create_pr(4, merged_days_ago=1, file_paths=["src/mid.py"])
        calculate_change_frequency(self.repo.id)
        f_high.refresh_from_db()
        f_mid.refresh_from_db()
        f_low.refresh_from_db()
        self.assertGreater(f_high.change_frequency_score, f_mid.change_frequency_score)
        self.assertGreater(f_mid.change_frequency_score, f_low.change_frequency_score)

    def test_tied_raw_scores_get_same_score(self):
        """Files with identical raw scores get same final score."""
        f1 = self._create_file("src/a.py")
        f2 = self._create_file("src/b.py")
        f3 = self._create_file("src/other.py")
        # f1 and f2 both in same PR, f3 untouched
        self._create_pr(1, merged_days_ago=1, file_paths=["src/a.py", "src/b.py"])
        calculate_change_frequency(self.repo.id)
        f1.refresh_from_db()
        f2.refresh_from_db()
        self.assertEqual(f1.change_frequency_score, f2.change_frequency_score)

    def test_scores_rounded_to_two_decimals(self):
        """All scores should be rounded to 2 decimal places."""
        for i in range(10):
            self._create_file(f"src/f{i}.py")
        for i in range(10):
            self._create_pr(i + 1, merged_days_ago=i * 10 + 1,
                            file_paths=[f"src/f{j}.py" for j in range(i + 1)])
        calculate_change_frequency(self.repo.id)
        for f in File.objects.filter(module_id__repo_id=self.repo.id):
            self.assertEqual(f.change_frequency_score, round(f.change_frequency_score, 2))


@override_settings(RISK_CONFIG=CHANGE_FREQ_RISK_CONFIG)
class ChangeFrequencyCappingTests(TestCase):
    """Tests for high/low cap normalization logic."""

    def setUp(self):
        self.repo = Repo.objects.create(name="cap-repo", owner="cap-owner", url="https://github.com/cap/repo")
        self.module = Module.objects.create(repo=self.repo, name="src", dir_path="src")

    def _create_file(self, path):
        return File.objects.create(module_id_id=self.module.id, file_path=path, line_count=100)

    def _create_pr(self, number, merged_days_ago, file_paths=None):
        pr = PullRequest.objects.create(
            repo=self.repo,
            github_pr_number=number,
            title=f"PR #{number}",
            merged_at=timezone.now() - timedelta(days=merged_days_ago),
        )
        for fp in (file_paths or []):
            PullRequestFile.objects.create(pull_request=pr, file_path=fp)
        return pr

    def test_high_cap_triggered(self):
        """max_raw >= 2.0 → effective_max = 10, highest file scores 10."""
        hot = self._create_file("src/hot.py")
        cold = self._create_file("src/cold.py")
        # 5 recent PRs gives raw > 2.0
        for i in range(5):
            self._create_pr(i + 1, merged_days_ago=i + 1, file_paths=["src/hot.py"])
        calculate_change_frequency(self.repo.id)
        hot.refresh_from_db()
        self.assertEqual(hot.change_frequency_score, 10.0)

    def test_high_cap_fallback(self):
        """max_raw < 2.0 → effective_max = 7."""
        hot = self._create_file("src/hot.py")
        cold = self._create_file("src/cold.py")
        # One recent PR gives raw ~1.0, which is > CHURN_QUIET_VARIANCE but < 2.0
        self._create_pr(1, merged_days_ago=1, file_paths=["src/hot.py"])
        calculate_change_frequency(self.repo.id)
        hot.refresh_from_db()
        self.assertLess(hot.change_frequency_raw, 2.0)
        self.assertEqual(hot.change_frequency_score, 7.0)

    def test_low_cap_triggered(self):
        """min_raw <= 0.1 (i.e. 0.0 for untouched files) → effective_min = 1."""
        hot = self._create_file("src/hot.py")
        cold = self._create_file("src/cold.py")
        for i in range(5):
            self._create_pr(i + 1, merged_days_ago=i + 1, file_paths=["src/hot.py"])
        calculate_change_frequency(self.repo.id)
        cold.refresh_from_db()
        self.assertEqual(cold.change_frequency_score, 1.0)

    def test_low_cap_fallback(self):
        """All files have raw > 0.1 → effective_min = 3."""
        f1 = self._create_file("src/a.py")
        f2 = self._create_file("src/b.py")
        # Both files changed, one more than the other
        for i in range(5):
            self._create_pr(i + 1, merged_days_ago=i + 1, file_paths=["src/a.py"])
        self._create_pr(6, merged_days_ago=1, file_paths=["src/b.py"])
        calculate_change_frequency(self.repo.id)
        f2.refresh_from_db()
        # f2 has lowest raw but > 0.1, so effective_min = 3
        self.assertEqual(f2.change_frequency_score, 3.0)


@override_settings(RISK_CONFIG=CHANGE_FREQ_RISK_CONFIG)
class ChangeFrequencyStressTests(TestCase):
    """Stress tests with larger datasets and edge cases."""

    def setUp(self):
        self.repo = Repo.objects.create(name="stress-repo", owner="stress-owner", url="https://github.com/stress/repo")
        self.module = Module.objects.create(repo=self.repo, name="src", dir_path="src")

    def _create_file(self, path):
        return File.objects.create(module_id_id=self.module.id, file_path=path, line_count=100)

    def _create_pr(self, number, merged_days_ago, file_paths=None):
        pr = PullRequest.objects.create(
            repo=self.repo,
            github_pr_number=number,
            title=f"PR #{number}",
            merged_at=timezone.now() - timedelta(days=merged_days_ago),
        )
        for fp in (file_paths or []):
            PullRequestFile.objects.create(pull_request=pr, file_path=fp)
        return pr

    def test_50_files_10_prs(self):
        """50 files, 10 PRs each touching a subset — scores computed without error."""
        files = [self._create_file(f"src/f{i}.py") for i in range(50)]
        for pr_num in range(1, 11):
            # Each PR touches files [0..pr_num*3]
            touched = [f"src/f{i}.py" for i in range(min(pr_num * 3, 50))]
            self._create_pr(pr_num, merged_days_ago=pr_num * 5, file_paths=touched)

        calculate_change_frequency(self.repo.id)

        scores = []
        for f in files:
            f.refresh_from_db()
            scores.append(f.change_frequency_score)
        # All scores should be assigned (no zeros from uninitialized)
        self.assertEqual(len(scores), 50)
        # Scores should be within expected range
        for s in scores:
            self.assertGreaterEqual(s, 1.0)
            self.assertLessEqual(s, 10.0)

    def test_100_files_no_prs(self):
        """100 files, 0 PRs — all quiet default."""
        files = [self._create_file(f"src/f{i}.py") for i in range(100)]
        calculate_change_frequency(self.repo.id)
        for f in files:
            f.refresh_from_db()
            self.assertEqual(f.change_frequency_score, 3)  # quiet default

    def test_one_hotspot_many_cold(self):
        """One file changed in 20 PRs, 19 others never changed. Hotspot should score 10."""
        hot = self._create_file("src/hot.py")
        colds = [self._create_file(f"src/cold{i}.py") for i in range(19)]
        for i in range(20):
            self._create_pr(i + 1, merged_days_ago=i + 1, file_paths=["src/hot.py"])
        calculate_change_frequency(self.repo.id)
        hot.refresh_from_db()
        self.assertEqual(hot.change_frequency_score, 10.0)
        for c in colds:
            c.refresh_from_db()
            self.assertEqual(c.change_frequency_score, 1.0)

    def test_all_files_in_every_pr(self):
        """Every file touched in every PR — all equal raw scores → quiet repo."""
        files = [self._create_file(f"src/f{i}.py") for i in range(10)]
        all_paths = [f"src/f{i}.py" for i in range(10)]
        for pr_num in range(1, 6):
            self._create_pr(pr_num, merged_days_ago=pr_num, file_paths=all_paths)
        calculate_change_frequency(self.repo.id)
        for f in files:
            f.refresh_from_db()
            self.assertEqual(f.change_frequency_score, 3)

    def test_gradual_decay_ordering(self):
        """Files changed at different times — ordering should match recency."""
        files = []
        for i in range(10):
            f = self._create_file(f"src/f{i}.py")
            files.append(f)
            # f0 changed 1 day ago, f1 changed 20 days ago, ..., f9 changed 181 days ago
            days = 1 + i * 20
            if days <= 180:
                self._create_pr(i + 1, merged_days_ago=days, file_paths=[f"src/f{i}.py"])

        calculate_change_frequency(self.repo.id)
        for f in files:
            f.refresh_from_db()

        # f0 should have highest score, scores should be non-increasing
        scores = [f.change_frequency_score for f in files]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1],
                                    f"Score for f{i} should be >= f{i+1}")

    def test_pr_file_not_in_file_table_ignored(self):
        """PR touches a file that isn't in the File table — doesn't crash."""
        f = self._create_file("src/exists.py")
        self._create_pr(1, merged_days_ago=1, file_paths=["src/exists.py", "src/ghost.py"])
        calculate_change_frequency(self.repo.id)
        f.refresh_from_db()
        self.assertGreater(f.change_frequency_raw, 0.0)

    def test_multiple_modules_same_repo(self):
        """Files across different modules in the same repo all get scored."""
        mod2 = Module.objects.create(repo=self.repo, name="lib", dir_path="lib")
        f1 = self._create_file("src/a.py")
        f2 = File.objects.create(module_id_id=mod2.id, file_path="lib/b.py", line_count=100)
        self._create_pr(1, merged_days_ago=1, file_paths=["src/a.py"])
        self._create_pr(2, merged_days_ago=1, file_paths=["lib/b.py"])
        calculate_change_frequency(self.repo.id)
        f1.refresh_from_db()
        f2.refresh_from_db()
        self.assertGreater(f1.change_frequency_raw, 0.0)
        self.assertGreater(f2.change_frequency_raw, 0.0)

    def test_idempotent_recalculation(self):
        """Running calculate_change_frequency twice produces same results."""
        hot = self._create_file("src/hot.py")
        cold = self._create_file("src/cold.py")
        for i in range(5):
            self._create_pr(i + 1, merged_days_ago=i + 1, file_paths=["src/hot.py"])
        calculate_change_frequency(self.repo.id)
        hot.refresh_from_db()
        score_1 = hot.change_frequency_score
        raw_1 = hot.change_frequency_raw
        calculate_change_frequency(self.repo.id)
        hot.refresh_from_db()
        self.assertAlmostEqual(hot.change_frequency_score, score_1, places=1)
        self.assertAlmostEqual(hot.change_frequency_raw, raw_1, places=1)

    def test_bot_prs_still_count(self):
        """Bot PRs (is_bot=True but is_revert=False) still contribute to churn."""
        f = self._create_file("src/a.py")
        self._create_file("src/b.py")
        pr = PullRequest.objects.create(
            repo=self.repo, github_pr_number=1, title="bot PR",
            merged_at=timezone.now() - timedelta(days=1),
            is_bot=True, is_revert=False,
        )
        PullRequestFile.objects.create(pull_request=pr, file_path="src/a.py")
        calculate_change_frequency(self.repo.id)
        f.refresh_from_db()
        self.assertGreater(f.change_frequency_raw, 0.0)


@override_settings(RISK_CONFIG=CHANGE_FREQ_RISK_CONFIG)
class ChangeFrequencyOutlierTests(TestCase):
    """Scenario A: 1000 files, 1 outlier hotspot changed 100 times in 2 days."""

    def setUp(self):
        self.repo = Repo.objects.create(
            name="outlier-repo", owner="outlier-owner",
            url="https://github.com/outlier/repo",
        )
        self.module = Module.objects.create(repo=self.repo, name="src", dir_path="src")

        # 1000 files via bulk_create
        self.files = File.objects.bulk_create([
            File(module_id_id=self.module.id, file_path=f"src/file_{i}.py", line_count=100)
            for i in range(1000)
        ])
        # Rename the first file to be the outlier
        self.outlier = self.files[0]
        self.outlier.file_path = "src/outlier_hotspot.py"
        self.outlier.save(update_fields=["file_path"])

        # 100 PRs each touching only the outlier, spread over ~2 days
        now = timezone.now()
        prs = PullRequest.objects.bulk_create([
            PullRequest(
                repo=self.repo,
                github_pr_number=i + 1,
                title=f"PR #{i + 1}",
                merged_at=now - timedelta(hours=i * 0.48),
            )
            for i in range(100)
        ])
        PullRequestFile.objects.bulk_create([
            PullRequestFile(pull_request=pr, file_path="src/outlier_hotspot.py")
            for pr in prs
        ])

        calculate_change_frequency(self.repo.id)
        # Refresh all files from DB
        self.outlier.refresh_from_db()
        self.stable_files = list(
            File.objects.filter(module_id__repo_id=self.repo.id)
            .exclude(pk=self.outlier.pk)
        )

    def test_outlier_hotspot_scores_max(self):
        """The outlier file should score 10.0."""
        self.assertEqual(self.outlier.change_frequency_score, 10.0)

    def test_stable_files_score_min(self):
        """All 999 stable files should score 1.0 (untouched -> raw=0 -> effective_min=1)."""
        for f in self.stable_files:
            self.assertEqual(
                f.change_frequency_score, 1.0,
                f"{f.file_path} expected 1.0, got {f.change_frequency_score}",
            )

    def test_outlier_does_not_break_scale(self):
        """All scores in [1.0, 10.0], no NaN or infinity."""
        import math
        all_files = [self.outlier] + self.stable_files
        for f in all_files:
            self.assertFalse(math.isnan(f.change_frequency_score), f"{f.file_path} is NaN")
            self.assertFalse(math.isinf(f.change_frequency_score), f"{f.file_path} is Inf")
            self.assertGreaterEqual(f.change_frequency_score, 1.0)
            self.assertLessEqual(f.change_frequency_score, 10.0)


@override_settings(RISK_CONFIG=CHANGE_FREQ_RISK_CONFIG)
class ChangeFrequencyDecayTests(TestCase):
    """Scenario B: Zombie file — verify score drops as time passes the x0=21 cliff."""

    def _setup_repo(self, name):
        repo = Repo.objects.create(
            name=f"{name}-repo", owner=f"{name}-owner",
            url=f"https://github.com/{name}/repo",
        )
        module = Module.objects.create(repo=repo, name="src", dir_path="src")
        return repo, module

    def _create_zombie_scenario(self, repo, module, zombie_path, days_offset, n_changes=10):
        """Create a zombie file with n_changes PRs at days_offset..days_offset+n_changes."""
        zombie = File.objects.create(
            module_id_id=module.id, file_path=zombie_path, line_count=100,
        )
        # A stable companion so the repo is never "quiet"
        companion = File.objects.create(
            module_id_id=module.id, file_path="src/companion.py", line_count=100,
        )
        now = timezone.now()
        prs = PullRequest.objects.bulk_create([
            PullRequest(
                repo=repo,
                github_pr_number=i + 1,
                title=f"PR #{i + 1}",
                merged_at=now - timedelta(days=days_offset + i),
            )
            for i in range(n_changes)
        ])
        PullRequestFile.objects.bulk_create([
            PullRequestFile(pull_request=pr, file_path=zombie_path)
            for pr in prs
        ])
        return zombie, companion

    def test_zombie_recent_is_hot(self):
        """When 10 changes happened 1-10 days ago, zombie scores high."""
        repo, module = self._setup_repo("zombie-recent")
        zombie, _ = self._create_zombie_scenario(repo, module, "src/zombie.py", days_offset=1)
        calculate_change_frequency(repo.id)
        zombie.refresh_from_db()
        # 10 changes all within 1-10 days (well before x0=21 cliff) → high score
        self.assertGreaterEqual(zombie.change_frequency_score, 8.0)

    def test_zombie_past_cliff_is_cold(self):
        """When 10 changes happened 40-50 days ago (past x0=21 cliff), zombie scores low.

        The raw score decays heavily past x0=21, so it stays below
        CHURN_HIGH_CAP_THRESHOLD (2.0). This means effective_max = 7 (fallback)
        rather than 10, proving the sigmoid decay took effect.
        """
        repo, module = self._setup_repo("zombie-old")
        zombie, _ = self._create_zombie_scenario(repo, module, "src/zombie.py", days_offset=40)
        calculate_change_frequency(repo.id)
        zombie.refresh_from_db()
        # Raw score should be close to 10 * L ≈ 1.0 (heavily decayed)
        self.assertLess(zombie.change_frequency_raw, 2.0)
        # Score capped by fallback (7) rather than reaching 10
        self.assertLess(zombie.change_frequency_score, 10.0)

    def test_decay_comparison(self):
        """Recent changes score significantly higher than old changes past the cliff."""
        repo = Repo.objects.create(
            name="decay-cmp-repo", owner="decay-cmp-owner",
            url="https://github.com/decay-cmp/repo",
        )
        module = Module.objects.create(repo=repo, name="src", dir_path="src")

        recent_file = File.objects.create(
            module_id_id=module.id, file_path="src/recent.py", line_count=100,
        )
        old_file = File.objects.create(
            module_id_id=module.id, file_path="src/old.py", line_count=100,
        )

        now = timezone.now()
        pr_num = 1
        # 10 recent PRs for recent_file (1-10 days ago)
        recent_prs = PullRequest.objects.bulk_create([
            PullRequest(
                repo=repo, github_pr_number=pr_num + i,
                title=f"PR #{pr_num + i}",
                merged_at=now - timedelta(days=1 + i),
            )
            for i in range(10)
        ])
        PullRequestFile.objects.bulk_create([
            PullRequestFile(pull_request=pr, file_path="src/recent.py")
            for pr in recent_prs
        ])

        pr_num = 100
        # 10 old PRs for old_file (40-50 days ago)
        old_prs = PullRequest.objects.bulk_create([
            PullRequest(
                repo=repo, github_pr_number=pr_num + i,
                title=f"PR #{pr_num + i}",
                merged_at=now - timedelta(days=40 + i),
            )
            for i in range(10)
        ])
        PullRequestFile.objects.bulk_create([
            PullRequestFile(pull_request=pr, file_path="src/old.py")
            for pr in old_prs
        ])

        calculate_change_frequency(repo.id)
        recent_file.refresh_from_db()
        old_file.refresh_from_db()

        self.assertGreater(
            recent_file.change_frequency_score,
            old_file.change_frequency_score,
            "Recent changes should score higher than old changes past the sigmoid cliff",
        )

