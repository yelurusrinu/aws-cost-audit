from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Tier(IntEnum):
    CLEAR_WIN = 1
    MEDIUM = 2
    ARCHITECTURAL = 3


TIER_LABEL = {
    Tier.CLEAR_WIN: "Tier 1 — clear wins (low risk, do now)",
    Tier.MEDIUM: "Tier 2 — medium (needs a check before acting)",
    Tier.ARCHITECTURAL: "Tier 3 — architectural (effort and sign-off)",
}

# On-demand list prices, us-east-1, USD per month. Override with --rates for your region.
DEFAULT_RATES = {
    "ebs_gp2_gb": 0.10,
    "ebs_gp3_gb": 0.08,
    "ebs_snapshot_gb": 0.05,
    "public_ipv4": 3.65,
    "alb_hour": 0.0225,
    "nlb_hour": 0.0225,
    "nat_hour": 0.045,
    "logs_gb": 0.03,
    "rds_snapshot_gb": 0.095,
}
HOURS = 730


@dataclass
class Finding:
    check: str
    resource: str
    tier: Tier
    monthly_saving: float
    evidence: str
    action: str
    risk: str = "low"
    caveats: list[str] = field(default_factory=list)


def total(findings: list[Finding], tier: Tier | None = None) -> float:
    return round(sum(f.monthly_saving for f in findings if tier is None or f.tier == tier), 2)
