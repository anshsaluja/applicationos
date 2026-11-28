"""Mutation tests proving the approval guard checker rejects unsafe control flow.

These tests are intentionally independent of the live smoke script so a future
refactor cannot silently weaken the AST regression gate.
"""
import ast
import unittest

from test_smoke_approval_opt_in import approval_requests, guarded_approval_calls


class ApprovalGuardMutationTests(unittest.TestCase):
    def assert_guarded(self, source, expected):
        tree = ast.parse(source)
        main = tree.body[0]
        calls = approval_requests(main)
        self.assertEqual(len(calls), 1, "Fixture must contain exactly one decision POST")
        self.assertEqual(id(calls[0]) in guarded_approval_calls(main), expected)

    def test_approved_inside_explicit_guard(self):
        self.assert_guarded(
            """def main():
    if token and os.getenv("APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION") == "local-only":
        request("POST", decision_path, decision_body)
""", True
        )

    def test_approval_in_else_is_not_guarded(self):
        self.assert_guarded(
            """def main():
    if token and os.getenv("APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION") == "local-only":
        pass
    else:
        request("POST", decision_path, decision_body)
""", False
        )

    def test_approval_after_guard_is_not_guarded(self):
        self.assert_guarded(
            """def main():
    if token and os.getenv("APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION") == "local-only":
        pass
    request("POST", decision_path, decision_body)
""", False
        )

    def test_approval_in_unrelated_branch_is_not_guarded(self):
        self.assert_guarded(
            """def main():
    if token and os.getenv("APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION") == "local-only":
        pass
    if allow_approval:
        request("POST", decision_path, decision_body)
""", False
        )


if __name__ == "__main__":
    unittest.main()
