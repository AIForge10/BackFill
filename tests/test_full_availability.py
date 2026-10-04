import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from full_availability import all_presentations_available


class FullAvailabilityTests(unittest.TestCase):
    def rows(self, statuses, allocations=None, presentations=None):
        return pd.DataFrame(dict(availability=statuses,
            on_allocation=allocations if allocations is not None else [False] * len(statuses),
            presentation=presentations if presentations is not None else [f"p{i}" for i in range(len(statuses))]))

    def test_available_strength_does_not_hide_backordered_strength(self):
        self.assertFalse(all_presentations_available(self.rows(["available", "disrupted"])))
        self.assertFalse(all_presentations_available(self.rows(["available", "unknown"])))
        self.assertFalse(all_presentations_available(self.rows(["available", "discontinued"])))

    def test_allocation_missing_evidence_and_empty_group_do_not_qualify(self):
        self.assertFalse(all_presentations_available(self.rows(["available"], ["True"])))
        self.assertFalse(all_presentations_available(self.rows(["available"], presentations=[""])))
        self.assertFalse(all_presentations_available(self.rows([])))

    def test_all_presentations_available_qualifies(self):
        self.assertTrue(all_presentations_available(self.rows(["available", "available"])))


if __name__ == "__main__":
    unittest.main()
