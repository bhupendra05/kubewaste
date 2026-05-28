"""Data models for kubewaste."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ── Resource helpers ──────────────────────────────────────────────────────────

def parse_cpu(val: Optional[str]) -> float:
    """Parse CPU value to millicores (float). Returns 0 if None."""
    if not val:
        return 0.0
    val = str(val).strip()
    if val.endswith("m"):
        return float(val[:-1])
    return float(val) * 1000.0


def parse_memory(val: Optional[str]) -> float:
    """Parse memory value to MiB (float). Returns 0 if None."""
    if not val:
        return 0.0
    val = str(val).strip()
    units = {
        "Ki": 1 / 1024, "Mi": 1, "Gi": 1024,
        "K": 1 / 1024, "M": 1, "G": 1024,
        "k": 1 / 1024, "m": 1, "g": 1024,
    }
    for suffix, factor in units.items():
        if val.endswith(suffix):
            return float(val[: -len(suffix)]) * factor
    return float(val) / (1024 * 1024)  # assume bytes


def fmt_cpu(millicores: float) -> str:
    if millicores >= 1000:
        return f"{millicores / 1000:.2f} cores"
    return f"{millicores:.0f}m"


def fmt_mem(mib: float) -> str:
    if mib >= 1024:
        return f"{mib / 1024:.2f} GiB"
    return f"{mib:.0f} MiB"


# ── Models ────────────────────────────────────────────────────────────────────

@dataclass
class ContainerWaste:
    """Resource waste for a single container."""

    name: str
    namespace: str
    pod: str
    container: str

    # Requested (from resources.requests)
    cpu_requested_m: float = 0.0    # millicores
    mem_requested_mib: float = 0.0  # MiB

    # Actual usage (from metrics-server)
    cpu_used_m: float = 0.0
    mem_used_mib: float = 0.0

    # Limits
    cpu_limit_m: float = 0.0
    mem_limit_mib: float = 0.0

    @property
    def cpu_waste_m(self) -> float:
        return max(0.0, self.cpu_requested_m - self.cpu_used_m)

    @property
    def mem_waste_mib(self) -> float:
        return max(0.0, self.mem_requested_mib - self.mem_used_mib)

    @property
    def cpu_utilisation_pct(self) -> float:
        if self.cpu_requested_m == 0:
            return 0.0
        return min(100.0, (self.cpu_used_m / self.cpu_requested_m) * 100)

    @property
    def mem_utilisation_pct(self) -> float:
        if self.mem_requested_mib == 0:
            return 0.0
        return min(100.0, (self.mem_used_mib / self.mem_requested_mib) * 100)

    @property
    def severity(self) -> str:
        """waste severity based on utilisation."""
        cpu_util = self.cpu_utilisation_pct
        mem_util = self.mem_utilisation_pct
        # Whichever is worse
        worst = min(cpu_util, mem_util) if (cpu_util > 0 and mem_util > 0) else max(cpu_util, mem_util)
        if worst < 10:
            return "critical"
        if worst < 25:
            return "high"
        if worst < 50:
            return "medium"
        return "low"

    def to_dict(self) -> dict:
        return {
            "namespace": self.namespace,
            "pod": self.pod,
            "container": self.container,
            "cpu_requested": fmt_cpu(self.cpu_requested_m),
            "cpu_used": fmt_cpu(self.cpu_used_m),
            "cpu_waste": fmt_cpu(self.cpu_waste_m),
            "cpu_utilisation_pct": round(self.cpu_utilisation_pct, 1),
            "mem_requested": fmt_mem(self.mem_requested_mib),
            "mem_used": fmt_mem(self.mem_used_mib),
            "mem_waste": fmt_mem(self.mem_waste_mib),
            "mem_utilisation_pct": round(self.mem_utilisation_pct, 1),
            "severity": self.severity,
        }


@dataclass
class UnusedResource:
    """A Kubernetes resource that appears unused."""

    kind: str               # "ConfigMap", "Secret", "PVC", "Service"
    namespace: str
    name: str
    reason: str             # why we think it's unused
    age_days: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "namespace": self.namespace,
            "name": self.name,
            "reason": self.reason,
            "age_days": self.age_days,
        }


@dataclass
class WasteReport:
    """Full waste report for a cluster or namespace."""

    cluster: str
    namespace_filter: Optional[str]
    containers: List[ContainerWaste] = field(default_factory=list)
    unused_resources: List[UnusedResource] = field(default_factory=list)

    @property
    def total_cpu_waste_m(self) -> float:
        return sum(c.cpu_waste_m for c in self.containers)

    @property
    def total_mem_waste_mib(self) -> float:
        return sum(c.mem_waste_mib for c in self.containers)

    @property
    def critical_containers(self) -> List[ContainerWaste]:
        return [c for c in self.containers if c.severity == "critical"]

    def estimated_monthly_savings_usd(
        self,
        cpu_per_core_usd: float = 30.0,
        mem_per_gb_usd: float = 4.0,
    ) -> float:
        """
        Rough monthly $ savings if waste is reclaimed.
        Defaults: AWS on-demand ~$30/core/month, ~$4/GiB/month.
        """
        cpu_saving  = (self.total_cpu_waste_m / 1000) * cpu_per_core_usd
        mem_saving  = (self.total_mem_waste_mib / 1024) * mem_per_gb_usd
        return round(cpu_saving + mem_saving, 2)

    def to_dict(self) -> dict:
        return {
            "cluster": self.cluster,
            "namespace_filter": self.namespace_filter,
            "containers_analysed": len(self.containers),
            "total_cpu_waste": fmt_cpu(self.total_cpu_waste_m),
            "total_mem_waste": fmt_mem(self.total_mem_waste_mib),
            "estimated_monthly_savings_usd": self.estimated_monthly_savings_usd(),
            "critical_containers": len(self.critical_containers),
            "unused_resources": len(self.unused_resources),
            "containers": [c.to_dict() for c in self.containers],
            "unused": [u.to_dict() for u in self.unused_resources],
        }
