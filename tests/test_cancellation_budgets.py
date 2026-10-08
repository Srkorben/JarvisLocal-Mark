from unittest import TestCase

from jarvis_local.budgets import ActionBudget, BudgetExceeded, BudgetLimits
from jarvis_local.cancellation import CancellationToken, OperationCancelled


class CancellationAndBudgetTests(TestCase):
    def test_cancellation_is_idempotent_and_preserves_first_reason(self) -> None:
        token = CancellationToken()
        token.cancel("primera")
        token.cancel("segunda")
        self.assertEqual(token.reason, "primera")
        with self.assertRaises(OperationCancelled):
            token.raise_if_cancelled()

    def test_step_budget_is_enforced(self) -> None:
        budget = ActionBudget(BudgetLimits(1, 10, 1, 0))
        budget.consume_step()
        with self.assertRaises(BudgetExceeded):
            budget.consume_step()

    def test_outbound_budget_defaults_to_zero(self) -> None:
        budget = ActionBudget(BudgetLimits(1, 10, 1, 0))
        with self.assertRaises(BudgetExceeded):
            budget.record_outbound_bytes(1)

