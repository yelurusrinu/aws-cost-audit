# aws-cost-audit

**A read-only AWS cost audit that goes from "what's my bill?" to a tiered, risk-rated savings plan with a projected target cost.**

It works as a CLI and as a [Claude Code](https://claude.com/claude-code) agent skill. The CLI collects the evidence. The skill teaches the agent the judgement calls the CLI can't make, like whether to go serverless, add RDS Proxy, or drop Multi-AZ.

[![ci](https://github.com/yelurusrinu/aws-cost-audit/actions/workflows/ci.yml/badge.svg)](https://github.com/yelurusrinu/aws-cost-audit/actions)

---

## Principles

1. **Follow the money.** Start from Cost Explorer: the monthly trend, the top services, and the daily run-rate. Optimise the top 2–3 services and ignore the long tail.
2. **Prove idle with a metric, not a name.** `old-api-lb` might carry 12,000 requests a week. `api` might carry zero. Load balancers are judged by `RequestCount` / `NewFlowCount` and NAT gateways by bytes out.
3. **Measure run-rate from *settled* days.** Cost Explorer lags 1–2 days and the 1st of each month has a billing spike. The run-rate is the median of the remaining days × 30.
4. **Read-only by construction.** The package only calls `describe_*`, `get_*` and `list_*`, and a test fails the build if anything else shows up.
5. **Every saving comes with its caveat.** Dropping Multi-AZ is an HA trade-off, not free money. A "...-old" snapshot might be someone's rollback point.

## What it checks

| Check | Tier | Evidence used |
|---|---|---|
| Unattached EBS volumes | 1 | `status=available`, priced by volume type |
| gp2 → gp3 | 1 | ~20% cheaper, online, no downtime |
| Unassociated Elastic IPs | 1 | every public IPv4 now bills ~$3.65/mo |
| Log groups that never expire | 1 | `retentionInDays` is null and ≥ 1 GB stored |
| Idle ALB / NLB | 2 | 0 requests / new flows over 7 days |
| Idle NAT gateways | 2 | < 100 MB out over 7 days |
| Old manual RDS snapshots | 2 | > 90 days old, billed in full |
| RDS Multi-AZ | 3 | flagged for an HA vs cost decision, never auto-priced |

## Output

```markdown
## Savings plan
### Tier 1 — clear wins (low risk, do now) — $412.60/mo
| Resource | Check | Evidence | Action | Risk | $/mo |
| `vol-0a1…` | unattached-ebs | 2000 GB gp2, state=available | snapshot if unsure, then delete | low | 200.00 |
...
## Where the bill lands
$8,940.00 → **$8,120.40/month** if every Tier 1–2 item is done (−$819.60).
```

## Usage

```bash
pip install git+https://github.com/yelurusrinu/aws-cost-audit

aws-cost-audit --profile staging --region ap-south-1 --out report.md
aws-cost-audit --profile staging --json | jq '.[] | select(.tier==1)'
aws-cost-audit --rates my-region-rates.json      # override default list prices
```

It needs only read permissions: `ce:GetCostAndUsage`, plus `Describe*` on EC2, ELB, RDS and Logs, and `cloudwatch:GetMetricStatistics`.

## As a Claude Code agent

Copy `skill/aws-cost-audit/` to `~/.claude/skills/` and ask *"why is our AWS bill up and what can we cut?"*. The agent runs the audit, then goes deeper where the CLI stops. For example, it checks `FreeableMemory` and `DatabaseConnections` before ever suggesting an RDS downsize, because a database at 3% CPU can still be fully memory-bound.

## Tests

```bash
pip install -e ".[dev]" && pytest -q
```

The tests cover run-rate edge cases, idle detection driven by metrics instead of names, pricing per volume type, report tiering and the projected bill, and the read-only guarantee. They use `botocore.Stubber`, so no AWS account is needed.

## Background

I built the methodology while cutting real AWS bills across several accounts. That work included RDS right-sizing, killing idle accelerators and load balancers, ECR lifecycle cleanup, and CloudWatch retention. This repo packages the repeatable part as code and the judgement part as an agent skill.

MIT licensed.
