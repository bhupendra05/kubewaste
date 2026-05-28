"""Tests for kubewaste models — zero K8s dependency."""
import pytest
from kubewaste.models import (
    ContainerWaste, WasteReport, UnusedResource,
    parse_cpu, parse_memory, fmt_cpu, fmt_mem,
)


# ── parse_cpu ─────────────────────────────────────────────────────────────────
class TestParseCPU:
    def test_millicores(self):
        assert parse_cpu("500m") == 500.0

    def test_cores(self):
        assert parse_cpu("2") == 2000.0

    def test_none(self):
        assert parse_cpu(None) == 0.0

    def test_zero(self):
        assert parse_cpu("0") == 0.0

    def test_decimal_cores(self):
        assert parse_cpu("0.5") == 500.0


# ── parse_memory ──────────────────────────────────────────────────────────────
class TestParseMemory:
    def test_mib(self):
        assert parse_memory("256Mi") == 256.0

    def test_gib(self):
        assert parse_memory("2Gi") == 2048.0

    def test_kib(self):
        assert abs(parse_memory("1024Ki") - 1.0) < 0.01

    def test_none(self):
        assert parse_memory(None) == 0.0

    def test_bytes(self):
        assert parse_memory("1048576") == pytest.approx(1.0, abs=0.01)


# ── fmt helpers ───────────────────────────────────────────────────────────────
class TestFmt:
    def test_fmt_cpu_m(self):
        assert "m" in fmt_cpu(500)

    def test_fmt_cpu_cores(self):
        assert "cores" in fmt_cpu(2000)

    def test_fmt_mem_mib(self):
        assert "MiB" in fmt_mem(512)

    def test_fmt_mem_gib(self):
        assert "GiB" in fmt_mem(2048)


# ── ContainerWaste ────────────────────────────────────────────────────────────
class TestContainerWaste:
    def _make(self, cpu_req=1000, mem_req=512, cpu_used=100, mem_used=50) -> ContainerWaste:
        return ContainerWaste(
            name="default/mypod/mycontainer",
            namespace="default", pod="mypod", container="mycontainer",
            cpu_requested_m=cpu_req, mem_requested_mib=mem_req,
            cpu_used_m=cpu_used,    mem_used_mib=mem_used,
        )

    def test_cpu_waste(self):
        c = self._make(cpu_req=1000, cpu_used=200)
        assert c.cpu_waste_m == 800.0

    def test_mem_waste(self):
        c = self._make(mem_req=512, mem_used=128)
        assert c.mem_waste_mib == 384.0

    def test_cpu_utilisation_pct(self):
        c = self._make(cpu_req=1000, cpu_used=100)
        assert c.cpu_utilisation_pct == pytest.approx(10.0)

    def test_mem_utilisation_pct(self):
        c = self._make(mem_req=512, mem_used=256)
        assert c.mem_utilisation_pct == pytest.approx(50.0)

    def test_severity_critical_when_low_utilisation(self):
        c = self._make(cpu_req=1000, mem_req=512, cpu_used=50, mem_used=25)
        assert c.severity == "critical"

    def test_severity_low_when_high_utilisation(self):
        c = self._make(cpu_req=1000, mem_req=512, cpu_used=900, mem_used=480)
        assert c.severity == "low"

    def test_no_negative_waste(self):
        # Used more than requested (burst) → waste = 0
        c = self._make(cpu_req=500, cpu_used=700)
        assert c.cpu_waste_m == 0.0

    def test_to_dict_keys(self):
        c = self._make()
        d = c.to_dict()
        assert "cpu_waste" in d
        assert "mem_waste" in d
        assert "severity" in d
        assert "cpu_utilisation_pct" in d


# ── WasteReport ───────────────────────────────────────────────────────────────
class TestWasteReport:
    def _make_report(self) -> WasteReport:
        report = WasteReport(cluster="test-cluster", namespace_filter="default")
        report.containers = [
            ContainerWaste(
                name="n/p/c1", namespace="default", pod="pod1", container="c1",
                cpu_requested_m=1000, mem_requested_mib=512,
                cpu_used_m=100, mem_used_mib=50,
            ),
            ContainerWaste(
                name="n/p/c2", namespace="default", pod="pod2", container="c2",
                cpu_requested_m=2000, mem_requested_mib=1024,
                cpu_used_m=200, mem_used_mib=100,
            ),
        ]
        return report

    def test_total_cpu_waste(self):
        r = self._make_report()
        assert r.total_cpu_waste_m == pytest.approx(2700.0)

    def test_total_mem_waste(self):
        r = self._make_report()
        assert r.total_mem_waste_mib == pytest.approx(1386.0)

    def test_savings_positive(self):
        r = self._make_report()
        assert r.estimated_monthly_savings_usd() > 0

    def test_critical_containers(self):
        r = self._make_report()
        assert len(r.critical_containers) == 2   # both < 10% utilisation

    def test_to_dict(self):
        r = self._make_report()
        d = r.to_dict()
        assert "total_cpu_waste" in d
        assert "estimated_monthly_savings_usd" in d
        assert "containers" in d
        assert len(d["containers"]) == 2

    def test_empty_report(self):
        r = WasteReport(cluster="c", namespace_filter=None)
        assert r.total_cpu_waste_m == 0.0
        assert r.estimated_monthly_savings_usd() == 0.0


# ── UnusedResource ─────────────────────────────────────────────────────────────
class TestUnusedResource:
    def test_to_dict(self):
        u = UnusedResource(
            kind="ConfigMap", namespace="default", name="old-config",
            reason="Not referenced by any pod"
        )
        d = u.to_dict()
        assert d["kind"] == "ConfigMap"
        assert d["reason"] == "Not referenced by any pod"
