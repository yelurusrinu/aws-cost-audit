---
name: aws-cost-audit
description: >-
  Systematic AWS cost optimization for one account: Cost Explorer baseline, utilization-proven
  idle resources, and a tiered, risk-rated savings plan with a target monthly cost. Use for
  "why is our AWS bill up", "reduce AWS cost", "find idle resources", "should this RDS go
  serverless", "right-size this database", "compare spend before and after". Requires the
  `aws-cost-audit` CLI (pip install git+https://github.com/yelurusrinu/aws-cost-audit).
---

# aws-cost-audit

## Workflow

1. **Confirm the account.** `aws sts get-caller-identity` — never assume the profile.
2. **Run the audit.** `aws-cost-audit --profile <p> --region <r> --out report.md`. This is
   read-only and safe on prod.
3. **Drill into the top 2–3 services** from the report. Ignore the long tail.
4. **Decide** using the heuristics below — this is where the CLI stops and judgement starts.
5. **Present** the tiered plan, the projected bill, and every caveat.
6. **Verify** a few days after changes: re-run and compare the run-rate, not the monthly total.

## Rules

- **Prod is read-only** until the user explicitly signs off on a specific change.
- **Prove idle with a metric**, not a name. `old-`, `test-`, `second-` mean nothing until measured.
- **CPU lies.** Pull `FreeableMemory` and `DatabaseConnections` before recommending any DB downsize.
- **State assumptions** on every estimate and give a range.

## Heuristics

**RDS serverless vs provisioned**
- Steady 24/7 workload → serverless is a wash or a loss: it sits at a constant floor ACU and
  adds per-I/O charges. Prefer RDS Proxy + a right-sized provisioned instance.
- Spiky, idle or dev/test → serverless wins (min ACU 0).
- Many connections + low CPU + memory-starved → the fix is RDS Proxy; pooling is what makes
  a memory downsize safe.
- Multi-AZ ≈ 2× instance + 2× storage. Dropping it is an HA trade-off, not free.
- RDS cannot shrink allocated storage in place. Dump/restore into a smaller instance, then
  rename-swap to keep the same endpoint.
- Deleting rows does not cut storage cost — allocated is billed, not used.

**Savings Plans** — right-sizing SP-covered EC2 does not lower the bill until the SP renews.
Storage (EBS, RDS, S3) is outside the SP, so those savings are immediate.

**ECR** — before a "keep last N" lifecycle, confirm no running service is pinned to an old tag
beyond the window, or its next task launch fails to pull.

**CloudWatch** — for regulated audit logs, export to S3 before setting retention.

## Output

Tier 1 clear wins · Tier 2 medium · Tier 3 architectural, a savings table, where the bill
lands per scenario, and a prod-safe execution order with reversible items first.
