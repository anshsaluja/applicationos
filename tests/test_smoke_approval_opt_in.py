"""Ensure every synthetic approval request is structurally inside local-only opt-in."""
import ast
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke_local_journey.py"


def approval_requests(tree):
    """Find synthetic approval POSTs; distinguish deliberately forged probes."""
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "request"
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "POST"
        and (
            isinstance(node.args[1], ast.Name) and node.args[1].id == "decision_path"
            or isinstance(node.args[1], ast.BinOp)
            and "/decision" in ast.unparse(node.args[1])
        )
    ]


def is_forged_negative_probe(node):
    """Only exempt a call with the explicit invalid credential literal."""
    for keyword in node.keywords:
        if keyword.arg != "extra_headers" or not isinstance(keyword.value, ast.Dict):
            continue
        headers = keyword.value
        return any(
            isinstance(key, ast.Constant) and key.value == "X-Review-Token"
            and isinstance(value, ast.Constant)
            and value.value == "invalid-synthetic-review-token"
            for key, value in zip(headers.keys, headers.values)
        )
    return False


def guarded_approval_calls(main):
    """Return approval calls reached through the *body* of a local-only guard.

    Line-number containment is insufficient: calls in an else branch or nested
    unrelated scope can fall inside the same source span without being guarded.
    """
    guarded = set()

    class GuardVisitor(ast.NodeVisitor):
        def __init__(self):
            self.local_only = False

        def visit_If(self, node):
            expression = ast.unparse(node.test)
            is_guard = (
                "APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION" in expression
                and "local-only" in expression
                and "token" in expression
                and isinstance(node.test, ast.BoolOp)
                and isinstance(node.test.op, ast.And)
            )
            previous = self.local_only
            self.local_only = previous or is_guard
            for child in node.body:
                self.visit(child)
            self.local_only = previous
            for child in node.orelse:
                self.visit(child)

        def visit_Call(self, node):
            if self.local_only and node in approval_requests(node):
                guarded.add(id(node))
            self.generic_visit(node)

    GuardVisitor().visit(main)
    return guarded


class SmokeApprovalOptInTests(unittest.TestCase):
    def test_decision_calls_are_inside_explicit_local_only_guard_body(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        main = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        calls = approval_requests(main)
        self.assertTrue(calls, "Expected synthetic approval requests")
        forged = [call for call in calls if is_forged_negative_probe(call)]
        self.assertEqual(len(forged), 1, "Expected one explicit forged-token negative probe")
        guarded = guarded_approval_calls(main)
        self.assertEqual(
            {id(call) for call in calls if not is_forged_negative_probe(call)}, guarded,
            "Every synthetic approval POST must be inside the body of a token "
            "and explicit local-only execution guard",
        )


if __name__ == "__main__":
    unittest.main()
