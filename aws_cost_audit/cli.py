from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from .baseline import by_service, daily, monthly_trend, run_rate
from .checks import ALL_CHECKS
from .findings import DEFAULT_RATES, Finding
from .report import render


def run(profile: str | None, region: str | None, rates: dict, today: date | None = None) -> tuple[str, list[Finding]]:
    import boto3

    s = boto3.Session(profile_name=profile, region_name=region)
    account = s.client("sts").get_caller_identity()["Account"]
    ce = s.client("ce", region_name="us-east-1")
    clients = {n: s.client(n) for n in ("ec2", "elbv2", "rds", "logs")}
    clients["cw"] = s.client("cloudwatch")

    today = today or date.today()
    trend = monthly_trend(ce, 4, today)
    month_start = today.replace(day=1)
    prev_start = (month_start - timedelta(days=1)).replace(day=1)
    services = by_service(ce, prev_start, month_start)
    rate = run_rate(daily(ce, month_start if today.day > 4 else prev_start, today), today)

    findings: list[Finding] = []
    errors: list[str] = []
    for check in ALL_CHECKS:
        try:
            findings.extend(check(rates=rates, **clients))
        except Exception as e:
            errors.append(f"{check.__name__}: {e}")
    md = render(account, trend, services, rate, findings)
    if errors:
        md += "\n## Checks that could not run\n\n" + "\n".join(f"- {e}" for e in errors) + "\n"
    return md, findings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aws-cost-audit",
                                description="Read-only AWS cost audit: baseline, idle resources, tiered savings plan.")
    p.add_argument("--profile")
    p.add_argument("--region")
    p.add_argument("--rates", type=Path, help="JSON overriding default USD rates")
    p.add_argument("--out", type=Path, help="write the markdown report here")
    p.add_argument("--json", action="store_true", help="print findings as JSON")
    a = p.parse_args(argv)

    rates = {**DEFAULT_RATES, **(json.loads(a.rates.read_text()) if a.rates else {})}
    md, findings = run(a.profile, a.region, rates)
    if a.json:
        print(json.dumps([f.__dict__ | {"tier": int(f.tier)} for f in findings], indent=2, default=str))
    elif a.out:
        a.out.write_text(md)
        print(f"wrote {a.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
