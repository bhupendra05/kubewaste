"""kubewaste CLI."""
from __future__ import annotations

import json
import sys

import click

from .models import WasteReport, fmt_cpu, fmt_mem

_SEVERITY_COLOUR = {
    "critical": "\033[1;31m",
    "high":     "\033[0;31m",
    "medium":   "\033[0;33m",
    "low":      "\033[0;36m",
}
_RESET = "\033[0m"
_GREEN = "\033[0;32m"
_BOLD  = "\033[1m"


@click.group()
@click.version_option()
def cli() -> None:
    """kubewaste — find Kubernetes resource waste before your cloud bill does."""


@cli.command()
@click.option("--namespace", "-n", default=None, help="Only scan this namespace")
@click.option("--context", "-c", default=None, help="Kubernetes context to use")
@click.option("--threshold", default=50.0, show_default=True,
              help="Flag containers using < this % of requested resources")
@click.option("--no-unused", is_flag=True, help="Skip unused resource scan")
@click.option("--json", "as_json", is_flag=True, help="Output JSON report")
@click.option("--min-severity", default="low",
              type=click.Choice(["critical", "high", "medium", "low"]),
              help="Only show containers at this severity or above")
@click.option("--top", default=None, type=int, help="Show only top N worst containers")
def scan(
    namespace, context, threshold, no_unused, as_json, min_severity, top
) -> None:
    """Scan the cluster for resource waste."""
    try:
        from .analyzer import KubeWasteAnalyzer
    except ImportError:
        click.echo("❌  kubernetes package required. Run: pip install kubernetes", err=True)
        sys.exit(1)

    click.echo("🔍 Connecting to cluster...", err=True)
    try:
        analyzer = KubeWasteAnalyzer(context=context)
        report = analyzer.analyze(
            namespace=namespace,
            utilisation_threshold_pct=threshold,
            include_unused=not no_unused,
        )
    except Exception as e:
        click.echo(f"❌  Error: {e}", err=True)
        sys.exit(1)

    # Filter by severity
    sev_order = ["critical", "high", "medium", "low"]
    max_idx = sev_order.index(min_severity)
    filtered = [c for c in report.containers if sev_order.index(c.severity) <= max_idx]
    if top:
        filtered = filtered[:top]
    report.containers = filtered

    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
        return

    _print_report(report)


def _print_report(report: WasteReport) -> None:
    print(f"\n{'─'*70}")
    print(f"  kubewaste — Kubernetes Resource Waste Report")
    ns_str = report.namespace_filter or "all namespaces"
    print(f"  Cluster: {_BOLD}{report.cluster}{_RESET}   Namespace: {ns_str}")
    print(f"{'─'*70}")

    if not report.containers:
        print(f"\n{_GREEN}✓ No significant resource waste detected.{_RESET}\n")
    else:
        print(f"\n  {'SEVERITY':<10} {'NAMESPACE':<16} {'POD':<30} {'CONTAINER':<16} "
              f"{'CPU REQ':>8} {'CPU USE':>8} {'%':>5}  "
              f"{'MEM REQ':>8} {'MEM USE':>8} {'%':>5}")
        print("  " + "─" * 115)

        for c in report.containers:
            col = _SEVERITY_COLOUR.get(c.severity, "")
            sev = f"{col}{c.severity:<10}{_RESET}"
            pod_short = c.pod[:28]
            print(
                f"  {sev} {c.namespace:<16} {pod_short:<30} {c.container:<16} "
                f"{fmt_cpu(c.cpu_requested_m):>8} {fmt_cpu(c.cpu_used_m):>8} {c.cpu_utilisation_pct:>4.0f}%  "
                f"{fmt_mem(c.mem_requested_mib):>8} {fmt_mem(c.mem_used_mib):>8} {c.mem_utilisation_pct:>4.0f}%"
            )

    print(f"\n{'─'*70}")
    savings = report.estimated_monthly_savings_usd()
    print(f"  Total CPU waste : {fmt_cpu(report.total_cpu_waste_m)}")
    print(f"  Total MEM waste : {fmt_mem(report.total_mem_waste_mib)}")
    print(f"  Est. savings    : {_BOLD}${savings:.2f}/month{_RESET}  "
          f"(${savings * 12:.0f}/year)")

    if report.unused_resources:
        print(f"\n  {'─'*40}")
        print(f"  Unused resources: {len(report.unused_resources)}")
        for u in report.unused_resources[:10]:
            print(f"    [{u.kind}] {u.namespace}/{u.name}  — {u.reason}")
        if len(report.unused_resources) > 10:
            print(f"    ... and {len(report.unused_resources) - 10} more (use --json to see all)")

    print(f"{'─'*70}\n")


@cli.command()
@click.option("--context", "-c", default=None)
def contexts(context) -> None:
    """List available Kubernetes contexts."""
    try:
        from kubernetes import config as k8s_config
        contexts_list, active = k8s_config.list_kube_config_contexts()
        for ctx in contexts_list:
            name = ctx["name"]
            marker = "* " if name == active["name"] else "  "
            print(f"{marker}{name}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
