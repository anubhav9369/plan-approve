"""Tests for plan_approve: the human decision point for InspectablePlans."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plan_approve import (
    DecisionRefused,
    append_decision,
    decide,
    latest_decision,
    plan_hash,
    read_log,
    risk_signals,
)

CLEAN_PLAN = {
    "id": "summarise-paper",
    "goal": "Summarise this paper and email the summary to me by 6 PM today",
    "steps": [
        {"id": "step-1", "action": "Draft the summary.",
         "why": "The summary is the deliverable.",
         "needs_permission": False,
         "failure_points": ["Summary misstates the paper"],
         "alternatives_considered": []},
        {"id": "step-2", "action": "Send the approved message.",
         "why": "Sending is the delivery step.",
         "needs_permission": True,
         "failure_points": ["Wrong recipient"],
         "alternatives_considered": []},
    ],
}

RISKY_PLAN = {
    "id": "email-summary-fast",
    "goal": "Email the summary out as soon as it is drafted",
    "steps": [
        {"id": "step-1", "action": "Send the summary to the team.",
         "why": "Fast delivery.",
         "needs_permission": False,
         "failure_points": [],
         "alternatives_considered": []},
    ],
}


def revised(plan):
    """A new version of a plan: same goal, one extra failure point."""
    copy = json.loads(json.dumps(plan))
    copy["steps"][0]["failure_points"].append("Draft never reviewed")
    return copy


class TestDecide(unittest.TestCase):
    def test_approve_clean_plan_records_everything(self):
        record = decide(CLEAN_PLAN, "approve", "Anubhav",
                        "Steps are gated; summary stays under the cap.")
        self.assertEqual(record["decision"], "approve")
        self.assertEqual(record["reviewer"], "Anubhav")
        self.assertEqual(record["plan_version"], plan_hash(CLEAN_PLAN))
        self.assertEqual(record["risk_signals"], [])
        self.assertIsNone(record["override"])

    def test_approve_risky_plan_without_override_is_refused(self):
        self.assertEqual(len(risk_signals(RISKY_PLAN)), 1)
        with self.assertRaises(DecisionRefused):
            decide(RISKY_PLAN, "approve", "Anubhav",
                   "Looks fine to me.")

    def test_approve_risky_plan_with_override_records_it(self):
        record = decide(RISKY_PLAN, "approve", "Anubhav",
                        "Team list is verified by hand first.",
                        override="I checked the recipient list myself.")
        self.assertEqual(record["decision"], "approve")
        self.assertEqual(record["override"],
                         "I checked the recipient list myself.")
        self.assertEqual(len(record["risk_signals"]), 1)

    def test_decision_without_a_reason_is_refused(self):
        with self.assertRaises(DecisionRefused):
            decide(CLEAN_PLAN, "reject", "Anubhav", "   ")

    def test_request_changes_needs_change_notes(self):
        with self.assertRaises(DecisionRefused):
            decide(CLEAN_PLAN, "request-changes", "Anubhav",
                   "Not quite right yet.")
        record = decide(CLEAN_PLAN, "request-changes", "Anubhav",
                        "Step 1 needs a citation check.",
                        changes=["Add a citation check to step 1."])
        self.assertEqual(record["changes"],
                         ["Add a citation check to step 1."])

    def test_same_version_cannot_be_decided_twice(self):
        first = decide(CLEAN_PLAN, "approve", "Anubhav", "Good to go.")
        with self.assertRaises(DecisionRefused):
            decide(CLEAN_PLAN, "reject", "Anubhav", "Changed my mind.",
                   prior_records=[first])

    def test_new_version_after_request_changes_can_be_decided(self):
        sent_back = decide(CLEAN_PLAN, "request-changes", "Anubhav",
                           "Step 1 needs a citation check.",
                           changes=["Add a citation check to step 1."])
        record = decide(revised(CLEAN_PLAN), "approve", "Anubhav",
                        "Citation check added; good to go.",
                        prior_records=[sent_back])
        self.assertEqual(record["decision"], "approve")
        self.assertNotEqual(record["plan_version"], sent_back["plan_version"])


class TestAuditLog(unittest.TestCase):
    def test_append_and_read_round_trip_keeps_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "decisions.jsonl")
            first = decide(CLEAN_PLAN, "request-changes", "Anubhav",
                           "Needs a citation check.",
                           changes=["Add a citation check."])
            append_decision(path, first)
            second = decide(revised(CLEAN_PLAN), "approve", "Anubhav",
                            "Fixed.", prior_records=[first])
            append_decision(path, second)
            records = read_log(path)
            self.assertEqual([r["decision"] for r in records],
                             ["request-changes", "approve"])

    def test_latest_decision_picks_the_last_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "decisions.jsonl")
            first = decide(CLEAN_PLAN, "request-changes", "Anubhav",
                           "Needs a citation check.",
                           changes=["Add a citation check."])
            append_decision(path, first)
            second = decide(revised(CLEAN_PLAN), "approve", "Anubhav",
                            "Fixed.", prior_records=[first])
            append_decision(path, second)
            records = read_log(path)
            latest = latest_decision(records, first["plan_id"])
            self.assertEqual(latest["decision"], "approve")
            self.assertIsNone(latest_decision(records, "plan-nonexistent"))


if __name__ == "__main__":
    unittest.main()
