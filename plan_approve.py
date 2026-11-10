"""Record a human's decision on an InspectablePlan.

An agent plan does nothing until a human says so. This module is the
decision point: it takes a plan and a human verdict — approve, reject,
or request-changes — validates the verdict, and records it in an
append-only audit log (one JSON object per line).

Rules (Week 1, BRJP26100123 — human-in-the-loop control):

- A decision needs a reviewer and a reason. A reason-less decision
  is not a decision, it is a shrug.
- ``request-changes`` needs at least one change note: what must change.
- ``approve`` is refused while the plan carries a high-severity risk
  signal (an ungated irreversible step, or a permission-gated step
  with no failure points) unless the reviewer records an explicit
  override with its own reason.
- One decision per plan version. A version is identified by the hash
  of the plan's contents, so a revised plan is a new version and can
  be decided again, but the same version cannot be re-decided after
  it was approved, rejected, or sent back for changes.
- Decisions are appended to the log, never edited in place.

Stdlib only, no third-party dependencies.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone

DECISIONS = ("approve", "reject", "request-changes")

# Action words that cannot be undone once they run.
IRREVERSIBLE_WORDS = ("send", "delete", "publish", "pay", "share")


class DecisionRefused(ValueError):
    """The decision was not recorded because it breaks a rule above."""


def plan_hash(plan):
    """Content hash of a plan: the same plan always hashes the same."""
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def plan_id(plan):
    """Stable id for a plan: its own id, or one derived from its hash."""
    if isinstance(plan, dict) and plan.get("id"):
        return str(plan["id"])
    return "plan-" + plan_hash(plan)[:12]


def risk_signals(plan):
    """High-severity signals that block an approval without an override."""
    signals = []
    for step in plan.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action", "")).lower()
        needs_permission = bool(step.get("needs_permission"))
        failure_points = step.get("failure_points") or []
        if not needs_permission and any(w in action for w in IRREVERSIBLE_WORDS):
            signals.append({
                "signal": "ungated-irreversible",
                "step": step.get("id"),
                "detail": f"Step {step.get('id')} runs an irreversible action "
                          f"without human permission.",
            })
        if needs_permission and not failure_points:
            signals.append({
                "signal": "permission-no-failure-mode",
                "step": step.get("id"),
                "detail": f"Step {step.get('id')} needs permission but "
                          f"declares no failure points.",
            })
    return signals


def decide(plan, decision, reviewer, reason, changes=None,
           override=None, decided_at=None, prior_records=()):
    """Validate a decision and return the record to append to the log.

    ``prior_records`` are the records already in the audit log; they
    enforce the one-decision-per-version rule.
    """
    if decision not in DECISIONS:
        raise DecisionRefused(
            f"Unknown decision {decision!r}; use one of {', '.join(DECISIONS)}.")
    if not isinstance(plan, dict) or not str(plan.get("goal", "")).strip():
        raise DecisionRefused("The plan has no goal to decide on.")
    if not plan.get("steps"):
        raise DecisionRefused("The plan has no steps to decide on.")
    if not str(reviewer or "").strip():
        raise DecisionRefused("A decision needs a named reviewer.")
    if not str(reason or "").strip():
        raise DecisionRefused("A decision needs a reason.")
    changes = [c for c in (changes or []) if str(c).strip()]
    if decision == "request-changes" and not changes:
        raise DecisionRefused(
            "request-changes needs at least one change note: what must change.")

    signals = risk_signals(plan)
    if decision == "approve" and signals and not str(override or "").strip():
        raise DecisionRefused(
            "Approval refused: the plan carries "
            f"{len(signals)} high-severity risk signal(s) "
            f"({', '.join(sorted({s['signal'] for s in signals}))}). "
            "Record an explicit override with its own reason, or fix the plan.")

    version = plan_hash(plan)
    pid = plan_id(plan)
    for record in prior_records:
        if record.get("plan_id") == pid and record.get("plan_version") == version:
            raise DecisionRefused(
                f"Plan version {version[:12]} was already decided "
                f"({record['decision']} by {record['reviewer']}). "
                "Revise the plan to decide again.")

    return {
        "plan_id": pid,
        "plan_version": version,
        "decision": decision,
        "reviewer": reviewer.strip(),
        "reason": reason.strip(),
        "changes": changes,
        "override": (override.strip() if override else None),
        "risk_signals": signals,
        "decided_at": decided_at or datetime.now(timezone.utc).isoformat(),
    }


def append_decision(path, record):
    """Append one decision record to a JSONL audit log."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def read_log(path):
    """Read an audit log back into a list of records (empty if missing)."""
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


def latest_decision(records, pid):
    """The most recent decision for a plan id, or None."""
    for record in reversed(records):
        if record.get("plan_id") == pid:
            return record
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Record a human decision on an InspectablePlan.")
    parser.add_argument("plan", help="Path to the plan JSON file.")
    parser.add_argument("decision", choices=DECISIONS,
                        help="The human verdict.")
    parser.add_argument("--reviewer", required=True,
                        help="Who is deciding (a name, not a role).")
    parser.add_argument("--reason", required=True,
                        help="Why this decision.")
    parser.add_argument("--changes", default="",
                        help="Semicolon-separated change notes "
                             "(required for request-changes).")
    parser.add_argument("--override", default="",
                        help="Reason for approving despite risk signals.")
    parser.add_argument("--log", default="decisions.jsonl",
                        help="Audit log to append to (default: decisions.jsonl).")
    args = parser.parse_args(argv)

    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    changes = [c.strip() for c in args.changes.split(";") if c.strip()]
    try:
        record = decide(
            plan, args.decision, args.reviewer, args.reason,
            changes=changes, override=args.override or None,
            prior_records=read_log(args.log),
        )
    except DecisionRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    append_decision(args.log, record)
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
