"""
kubewaste — find Kubernetes resource waste before your cloud bill does.

Quick Start
-----------
    from kubewaste import KubeWasteAnalyzer

    analyzer = KubeWasteAnalyzer()
    report = analyzer.analyze(namespace="production")

    print(f"CPU wasted : {report.total_cpu_waste_m:.0f}m")
    print(f"RAM wasted : {report.total_mem_waste_mib:.0f} MiB")
    print(f"Savings    : ${report.estimated_monthly_savings_usd():.2f}/month")
"""
from .models import ContainerWaste, WasteReport, UnusedResource
from .analyzer import KubeWasteAnalyzer

__version__ = "0.1.0"
__all__ = ["KubeWasteAnalyzer", "ContainerWaste", "WasteReport", "UnusedResource"]
