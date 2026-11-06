from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

from .findings import HOURS, Finding, Tier

Check = Callable[..., Iterable[Finding]]


def _metric_sum(cw, namespace: str, metric: str, dims: list[dict], days: int = 7, stat: str = "Sum") -> float | None:
    end = datetime.now(timezone.utc)
    r = cw.get_metric_statistics(Namespace=namespace, MetricName=metric, Dimensions=dims,
                                 StartTime=end - timedelta(days=days), EndTime=end,
                                 Period=days * 86400, Statistics=[stat])
    points = r.get("Datapoints") or []
    return sum(p[stat] for p in points) if points else None


def unattached_volumes(ec2, rates, **_) -> Iterable[Finding]:
    for page in ec2.get_paginator("describe_volumes").paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for v in page["Volumes"]:
            rate = rates["ebs_gp3_gb"] if v["VolumeType"] == "gp3" else rates["ebs_gp2_gb"]
            yield Finding("unattached-ebs", v["VolumeId"], Tier.CLEAR_WIN, round(v["Size"] * rate, 2),
                          f"{v['Size']} GB {v['VolumeType']}, state=available",
                          "snapshot if unsure, then delete the volume")


def gp2_volumes(ec2, rates, **_) -> Iterable[Finding]:
    delta = rates["ebs_gp2_gb"] - rates["ebs_gp3_gb"]
    for page in ec2.get_paginator("describe_volumes").paginate(Filters=[{"Name": "volume-type", "Values": ["gp2"]},
                                                                         {"Name": "status", "Values": ["in-use"]}]):
        for v in page["Volumes"]:
            yield Finding("gp2-to-gp3", v["VolumeId"], Tier.CLEAR_WIN, round(v["Size"] * delta, 2),
                          f"{v['Size']} GB gp2 in use",
                          "modify-volume --volume-type gp3 (online, no downtime)")


def idle_public_ips(ec2, rates, **_) -> Iterable[Finding]:
    for a in ec2.describe_addresses()["Addresses"]:
        if not a.get("AssociationId"):
            yield Finding("unassociated-eip", a["PublicIp"], Tier.CLEAR_WIN, rates["public_ipv4"],
                          "Elastic IP not associated with anything", "release the address")


def idle_load_balancers(elbv2, cw, rates, **_) -> Iterable[Finding]:
    """Idle is proven by traffic, not by a name like 'old-' or 'test-'."""
    for page in elbv2.get_paginator("describe_load_balancers").paginate():
        for lb in page["LoadBalancers"]:
            dim = lb["LoadBalancerArn"].split("loadbalancer/", 1)[1]
            if lb["Type"] == "application":
                used = _metric_sum(cw, "AWS/ApplicationELB", "RequestCount", [{"Name": "LoadBalancer", "Value": dim}])
                rate, metric = rates["alb_hour"], "RequestCount"
            elif lb["Type"] == "network":
                used = _metric_sum(cw, "AWS/NetworkELB", "NewFlowCount", [{"Name": "LoadBalancer", "Value": dim}])
                rate, metric = rates["nlb_hour"], "NewFlowCount"
            else:
                continue
            if not used:
                yield Finding("idle-load-balancer", lb["LoadBalancerName"], Tier.MEDIUM, round(rate * HOURS, 2),
                              f"{metric} = 0 over 7 days", "confirm no DNS points at it, then delete",
                              risk="medium", caveats=["LCU charges not included; saving is the hourly floor only"])


def idle_nat_gateways(ec2, cw, rates, **_) -> Iterable[Finding]:
    for n in ec2.describe_nat_gateways(Filter=[{"Name": "state", "Values": ["available"]}])["NatGateways"]:
        out = _metric_sum(cw, "AWS/NATGateway", "BytesOutToDestination",
                          [{"Name": "NatGatewayId", "Value": n["NatGatewayId"]}])
        if not out or out < 100 * 1024 * 1024:
            yield Finding("idle-nat", n["NatGatewayId"], Tier.MEDIUM, round(rates["nat_hour"] * HOURS, 2),
                          f"{(out or 0) / 1e6:.1f} MB out over 7 days",
                          "check route tables that point at it before deleting", risk="medium")


def never_expiring_logs(logs, rates, min_gb: float = 1.0, **_) -> Iterable[Finding]:
    for page in logs.get_paginator("describe_log_groups").paginate():
        for g in page["logGroups"]:
            gb = g.get("storedBytes", 0) / 1e9
            if g.get("retentionInDays") is None and gb >= min_gb:
                yield Finding("log-retention", g["logGroupName"], Tier.CLEAR_WIN, round(gb * rates["logs_gb"] * 0.75, 2),
                              f"{gb:.1f} GB stored, never expires", "set retention (e.g. 90 days)",
                              caveats=["for regulated audit logs, export to S3 before expiring"])


def manual_rds_snapshots(rds, rates, min_age_days: int = 90, **_) -> Iterable[Finding]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
    for page in rds.get_paginator("describe_db_snapshots").paginate(SnapshotType="manual"):
        for s in page["DBSnapshots"]:
            if s.get("SnapshotCreateTime") and s["SnapshotCreateTime"] < cutoff:
                yield Finding("old-rds-snapshot", s["DBSnapshotIdentifier"], Tier.MEDIUM,
                              round(s["AllocatedStorage"] * rates["rds_snapshot_gb"], 2),
                              f"{s['AllocatedStorage']} GB, created {s['SnapshotCreateTime']:%Y-%m-%d}",
                              "confirm it backs no unfinished migration, then delete", risk="medium",
                              caveats=["never delete a rollback snapshot before the migration it backs is validated"])


def rds_multi_az(rds, **_) -> Iterable[Finding]:
    for page in rds.get_paginator("describe_db_instances").paginate():
        for db in page["DBInstances"]:
            if db.get("MultiAZ"):
                yield Finding("rds-multi-az", db["DBInstanceIdentifier"], Tier.ARCHITECTURAL, 0.0,
                              f"{db['DBInstanceClass']} Multi-AZ (≈2× instance + storage)",
                              "keep for prod; consider single-AZ for non-prod", risk="high",
                              caveats=["HA trade-off: minutes of downtime on host failure instead of seconds",
                                       "saving depends on instance price; see Cost Explorer by USAGE_TYPE"])


ALL_CHECKS: list[Check] = [
    unattached_volumes, gp2_volumes, idle_public_ips, idle_load_balancers,
    idle_nat_gateways, never_expiring_logs, manual_rds_snapshots, rds_multi_az,
]
