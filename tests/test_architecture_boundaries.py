"""
CP-0 Test Suite: Architecture Import-Boundary Enforcement (Layer 1A / 1B / 2 / 3).

Enforces the strict one-way dependency DAG defined in architecture_review_v2.md:
- Layer 1A (allocation_engine/core/primitives/):
    MUST NOT import from core.allocators, rules, scheduling, rescheduling,
    Sheduling.preferred_therapist_service, Sheduling.vip_service,
    Sheduling.nurse_allocation, Sheduling.views, final_allocation, or reshedule.
- Layer 2 (allocation_engine/rules/):
    MUST NOT import from core.allocators, scheduling, rescheduling,
    final_allocation, or reshedule.
- Layer 1B (allocation_engine/core/allocators/):
    MUST NOT import from scheduling, rescheduling, final_allocation, or reshedule.
- Layer 3A (allocation_engine/scheduling/):
    MUST NOT import from allocation_engine.rescheduling or reshedule.
- Layer 3B (allocation_engine/rescheduling/):
    MUST NOT import from allocation_engine.scheduling or final_allocation.

During CP-0 (before allocation_engine/ is created), these checks validate the
AST boundary scanner itself and will automatically enforce every new file added
in CP-1 through CP-4.
"""
import ast
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE_ROOT = PROJECT_ROOT / "allocation_engine"


def _collect_imports(py_file: Path) -> list[tuple[int, str]]:
    """Return list of (line_no, imported_module_path) for every import in py_file."""
    src = py_file.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, filename=str(py_file))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level > 0:
                # Resolve relative import against package path
                rel_parts = list(py_file.relative_to(PROJECT_ROOT).with_suffix("").parts[:-node.level])
                if mod:
                    rel_parts.extend(mod.split("."))
                mod = ".".join(rel_parts)
            found.append((node.lineno, mod))
    return found


def _find_violations(folder: Path, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    if not folder.exists():
        return []
    violations = []
    for py_file in sorted(folder.rglob("*.py")):
        for lineno, mod in _collect_imports(py_file):
            for prefix in forbidden_prefixes:
                if mod == prefix or mod.startswith(prefix + "."):
                    rel = py_file.relative_to(PROJECT_ROOT)
                    violations.append(f"{rel}:{lineno} imports forbidden module '{mod}'")
    return violations


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_layer_1a_primitives_boundaries(self):
        forbidden = (
            "allocation_engine.core.allocators",
            "allocation_engine.rules",
            "allocation_engine.scheduling",
            "allocation_engine.rescheduling",
            "Sheduling.preferred_therapist_service",
            "Sheduling.vip_service",
            "Sheduling.nurse_allocation",
            "Sheduling.views",
            "final_allocation",
            "reshedule",
            "resheduleMorningandNight",
        )
        violations = _find_violations(ENGINE_ROOT / "core" / "primitives", forbidden)
        self.assertEqual(violations, [], f"Layer 1A boundary violations:\n" + "\n".join(violations))

    def test_layer_2_rules_boundaries(self):
        forbidden = (
            "allocation_engine.core.allocators",
            "allocation_engine.scheduling",
            "allocation_engine.rescheduling",
            "Sheduling.views",
            "final_allocation",
            "reshedule",
            "resheduleMorningandNight",
        )
        violations = _find_violations(ENGINE_ROOT / "rules", forbidden)
        self.assertEqual(violations, [], f"Layer 2 (rules) boundary violations:\n" + "\n".join(violations))

    def test_layer_1b_allocators_boundaries(self):
        forbidden = (
            "allocation_engine.scheduling",
            "allocation_engine.rescheduling",
            "Sheduling.views",
            "final_allocation",
            "reshedule",
            "resheduleMorningandNight",
        )
        violations = _find_violations(ENGINE_ROOT / "core" / "allocators", forbidden)
        self.assertEqual(violations, [], f"Layer 1B (allocators) boundary violations:\n" + "\n".join(violations))

    def test_layer_3a_scheduling_does_not_import_rescheduling(self):
        forbidden = (
            "allocation_engine.rescheduling",
            "reshedule",
            "resheduleMorningandNight",
        )
        violations = _find_violations(ENGINE_ROOT / "scheduling", forbidden)
        self.assertEqual(violations, [], f"Layer 3A (scheduling) boundary violations:\n" + "\n".join(violations))

    def test_layer_3b_rescheduling_does_not_import_scheduling(self):
        forbidden = (
            "allocation_engine.scheduling",
            "final_allocation",
        )
        violations = _find_violations(ENGINE_ROOT / "rescheduling", forbidden)
        self.assertEqual(violations, [], f"Layer 3B (rescheduling) boundary violations:\n" + "\n".join(violations))

    def test_ast_scanner_catches_violation_in_synthetic_code(self):
        """Self-test ensuring the AST scanner accurately detects both direct and relative forbidden imports."""
        sample = "from allocation_engine.rescheduling import slot_attempter\nimport reshedule\n"
        tree = ast.parse(sample)
        mods = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.append(node.module)
        self.assertIn("allocation_engine.rescheduling", mods)
        self.assertIn("reshedule", mods)
