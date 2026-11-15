"""Guard against ambient credentials enabling smoke approvals without opt-in."""
import ast
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke_local_journey.py"


class SmokeApprovalOptInTests(unittest.TestCase):
    def test_decision_calls_are_guarded_by_explicit_local_only_mode(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        guards = []
        for node in ast.walk(main):
            if not isinstance(node, ast.If):
                continue
            text = ast.unparse(node.test)
            if "token" in text and "APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION" in text:
                guards.append(node)
        decision_calls = [
            node for node in ast.walk(main)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "request"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "POST"
            and len(node.args) > 1
            and (
                isinstance(node.args[1], ast.Name) and node.args[1].id == "decision_path"
                or isinstance(node.args[1], ast.BinOp) and "/decision" in ast.unparse(node.args[1])
            )
        ]
        self.assertTrue(decision_calls, "Expected approval decision requests in smoke journey")
        # An earlier fail-fast token validation is also guarded by local-only
        # mode. Select the guard that actually encloses every decision call,
        # rather than assuming there is only one matching conditional.
        approval_guards = [
            guard for guard in guards
            if all(guard.lineno < call.lineno <= guard.end_lineno for call in decision_calls)
        ]
        self.assertEqual(
            len(approval_guards), 1,
            "All approval decisions must share one explicit local-only token guard",
        )
        guard = approval_guards[0]
        self.assertIn("'local-only'", ast.unparse(guard.test))
        guarded_lines = (guard.lineno, guard.end_lineno)
        self.assertTrue(
            all(guarded_lines[0] < call.lineno <= guarded_lines[1] for call in decision_calls),
            "Approval decisions must remain inside explicit opt-in guard",
        )


if __name__ == "__main__":
    unittest.main()
