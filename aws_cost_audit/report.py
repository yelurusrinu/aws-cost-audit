from __future__ import annotations

from .findings import TIER_LABEL, Finding, Tier, total


def render(account: str, trend: list[tuple[str, float]], services: list[tuple[str, float]],
           rate: float | None, findings: list[Finding]) -> str:
    out = [f"# AWS cost audit — account {account}", ""]

    out += ["## Baseline", "", "| Month | Cost (USD) |", "|---|---:|"]
    out += [f"| {m} | {a:,.2f} |" for m, a in trend]
    if rate is not None:
        out += ["", f"**Current run-rate:** ${rate:,.2f}/month (median of settled days × 30)"]

    out += ["", "## Top services", "", "| Service | Cost (USD) |", "|---|---:|"]
    out += [f"| {s} | {a:,.2f} |" for s, a in services]

    out += ["", "## Savings plan", ""]
    for tier in Tier:
        rows = [f for f in findings if f.tier == tier]
        if not rows:
            continue
        out += [f"### {TIER_LABEL[tier]} — ${total(findings, tier):,.2f}/mo", "",
                "| Resource | Check | Evidence | Action | Risk | $/mo |", "|---|---|---|---|---|---:|"]
        out += [f"| `{f.resource}` | {f.check} | {f.evidence} | {f.action} | {f.risk} | {f.monthly_saving:,.2f} |"
                for f in sorted(rows, key=lambda f: -f.monthly_saving)]
        caveats = sorted({c for f in rows for c in f.caveats})
        if caveats:
            out += [""] + [f"> {c}" for c in caveats]
        out.append("")

    saving = total(findings)
    out += ["## Where the bill lands", ""]
    if rate is not None:
        out.append(f"${rate:,.2f} → **${max(rate - saving, 0):,.2f}/month** if every Tier 1–2 item is done "
                   f"(−${saving:,.2f}). Tier 3 items are priced as 0 until sized.")
    else:
        out.append(f"Identified savings: **${saving:,.2f}/month**.")
    out += ["", "Assumptions: on-demand list prices; savings plans and reserved instances not modelled. "
            "Re-check the daily run-rate a few days after changes to confirm the drop landed."]
    return "\n".join(out) + "\n"
