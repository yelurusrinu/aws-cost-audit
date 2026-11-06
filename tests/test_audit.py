from datetime import date, datetime, timedelta, timezone

import boto3
import pytest
from botocore.stub import Stubber

from aws_cost_audit.baseline import DailyCost, run_rate, settled_days
from aws_cost_audit.checks import (idle_load_balancers, idle_public_ips, manual_rds_snapshots,
                                   never_expiring_logs, unattached_volumes)
from aws_cost_audit.findings import DEFAULT_RATES, Finding, Tier, total
from aws_cost_audit.report import render

KW = dict(region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")


def test_run_rate_skips_first_of_month_and_lagging_days():
    today = date(2026, 7, 10)
    days = [DailyCost(date(2026, 7, d), 500.0 if d == 1 else (5.0 if d >= 8 else 100.0)) for d in range(1, 10)]
    assert [d.day.day for d in settled_days(days, today)] == list(range(2, 8))
    assert run_rate(days, today) == 3000.0


def test_run_rate_none_when_nothing_settled():
    assert run_rate([DailyCost(date(2026, 7, 1), 9.0)], date(2026, 7, 2)) is None


def test_unattached_volume_priced_by_type():
    ec2 = boto3.client("ec2", **KW)
    with Stubber(ec2) as st:
        st.add_response("describe_volumes", {"Volumes": [
            {"VolumeId": "vol-1", "Size": 100, "VolumeType": "gp2"},
            {"VolumeId": "vol-2", "Size": 100, "VolumeType": "gp3"}]}, None)
        out = list(unattached_volumes(ec2, DEFAULT_RATES))
    assert [(f.resource, f.monthly_saving) for f in out] == [("vol-1", 10.0), ("vol-2", 8.0)]
    assert all(f.tier is Tier.CLEAR_WIN for f in out)


def test_only_unassociated_eips_flagged():
    ec2 = boto3.client("ec2", **KW)
    with Stubber(ec2) as st:
        st.add_response("describe_addresses", {"Addresses": [
            {"PublicIp": "1.1.1.1", "AssociationId": "eipassoc-1"}, {"PublicIp": "2.2.2.2"}]}, {})
        out = list(idle_public_ips(ec2, DEFAULT_RATES))
    assert [f.resource for f in out] == ["2.2.2.2"]


def test_load_balancer_idle_only_when_metric_says_so():
    elbv2, cw = boto3.client("elbv2", **KW), boto3.client("cloudwatch", **KW)
    arn = "arn:aws:elasticloadbalancing:us-east-1:1:loadbalancer/app/{n}/abc"
    with Stubber(elbv2) as es, Stubber(cw) as cs:
        es.add_response("describe_load_balancers", {"LoadBalancers": [
            {"LoadBalancerName": "old-busy", "LoadBalancerArn": arn.format(n="old-busy"), "Type": "application"},
            {"LoadBalancerName": "api", "LoadBalancerArn": arn.format(n="api"), "Type": "application"}]}, {})
        cs.add_response("get_metric_statistics", {"Datapoints": [{"Sum": 12000.0}]}, None)
        cs.add_response("get_metric_statistics", {"Datapoints": []}, None)
        out = list(idle_load_balancers(elbv2, cw, DEFAULT_RATES))
    assert [f.resource for f in out] == ["api"]


def test_logs_without_retention_above_threshold():
    logs = boto3.client("logs", **KW)
    with Stubber(logs) as st:
        st.add_response("describe_log_groups", {"logGroups": [
            {"logGroupName": "/big", "storedBytes": 40 * 10**9},
            {"logGroupName": "/kept", "storedBytes": 40 * 10**9, "retentionInDays": 30},
            {"logGroupName": "/tiny", "storedBytes": 10**6}]}, {})
        out = list(never_expiring_logs(logs, DEFAULT_RATES))
    assert [f.resource for f in out] == ["/big"]


def test_only_old_manual_snapshots():
    rds = boto3.client("rds", **KW)
    now = datetime.now(timezone.utc)
    with Stubber(rds) as st:
        st.add_response("describe_db_snapshots", {"DBSnapshots": [
            {"DBSnapshotIdentifier": "pre-migration-old", "AllocatedStorage": 500,
             "SnapshotCreateTime": now - timedelta(days=200)},
            {"DBSnapshotIdentifier": "last-week", "AllocatedStorage": 500,
             "SnapshotCreateTime": now - timedelta(days=7)}]}, {"SnapshotType": "manual"})
        out = list(manual_rds_snapshots(rds, DEFAULT_RATES))
    assert [f.resource for f in out] == ["pre-migration-old"]
    assert out[0].caveats


def test_report_tiers_and_landing():
    findings = [
        Finding("unattached-ebs", "vol-1", Tier.CLEAR_WIN, 10.0, "100 GB", "delete"),
        Finding("idle-nat", "nat-1", Tier.MEDIUM, 32.85, "0 MB", "delete", risk="medium"),
    ]
    md = render("123", [("2026-06", 1000.0)], [("Amazon EC2", 600.0)], 1000.0, findings)
    assert "### Tier 1" in md and "### Tier 2" in md and "### Tier 3" not in md
    assert "$957.15/month" in md
    assert total(findings) == 42.85


def test_package_makes_no_mutating_call():
    import ast
    import pathlib

    import aws_cost_audit

    reads = ("describe_", "get_", "list_")
    for f in pathlib.Path(aws_cost_audit.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                v = node.func.value
                if isinstance(v, ast.Name) and v.id in {"ec2", "elbv2", "rds", "logs", "cw", "ce"}:
                    assert node.func.attr.startswith(reads), f"{f.name}:{node.lineno} {node.func.attr}"
