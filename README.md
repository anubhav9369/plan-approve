# plan-approve

The human decision point for an InspectablePlan: approve, reject, or
request-changes — with a reason, and an append-only audit log so every
decision can be traced back to who made it and why.

Part of Week 1 (Inspectable Plans) of the trustworthy-agentic-ai
prototype for **BRJP26100123 — Building Trustworthy AI Systems through
Explainability and Human-in-the-Loop Control**. Companion repos:
[trustworthy-agentic-ai](https://github.com/anubhav9369/trustworthy-agentic-ai)
(the InspectablePlan schema),
[plan-explainer](https://github.com/anubhav9369/plan-explainer)
(plain-language rendering + review checklist),
[plan-diff](https://github.com/anubhav9369/plan-diff)
(what changed between two plan versions), and
[plan-risk-scan](https://github.com/anubhav9369/plan-risk-scan)
(what needs a human's attention before approval).

## The rules

| Rule | What it stops |
| --- | --- |
| A decision needs a reviewer and a reason | Reason-less approvals nobody can defend later |
| `request-changes` needs change notes | A plan sent back with no idea what to fix |
| `approve` is refused while the plan carries a high-severity risk signal, unless an explicit override is recorded | Rubber-stamping a plan with an ungated send/delete/publish/pay step, or a permission-gated step with no failure points |
| One decision per plan version | The same version being re-decided after it was already approved, rejected, or sent back |
| Decisions append to a JSONL log, never edited in place | Rewriting history after the fact |

A plan version is the hash of the plan's contents. Give a plan an
`"id"` to group its versions — without one, the id is derived from
the hash, so a revised plan looks like a new plan instead of a new
version of the same one.

## Usage

```bash
python3 plan_approve.py examples/plan.json request-changes \
  --reviewer Anubhav \
  --reason "Step 3 must name the exact recipient check before sending." \
  --changes "Add a recipient check against the address book to step 3." \
  --log decisions.jsonl

python3 plan_approve.py examples/plan-v2.json approve \
  --reviewer Anubhav \
  --reason "Recipient check added as a failure point and a constraint; good to go." \
  --log decisions.jsonl
```

The first command is refused if the plan is approved without an
override while it still carries a high-severity risk signal; the
second is refused if the same version was already decided. A refusal
exits with code 2 and prints why.

`examples/decisions.jsonl` is the log those two commands produce:
`request-changes` on v1, then `approve` on the revised v2 — same plan
id, two versions.

Python API:

```python
from plan_approve import decide, append_decision, read_log, latest_decision

record = decide(plan, "approve", "Anubhav", "Steps are gated; good to go.",
                prior_records=read_log("decisions.jsonl"))
append_decision("decisions.jsonl", record)
latest_decision(read_log("decisions.jsonl"), "summarise-paper")
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

9 tests, all passing.
