# kubewaste

**Find Kubernetes resource waste before your cloud bill does.**

```bash
pip install kubewaste
kubewaste scan --namespace production
```

[![CI](https://github.com/bhupendra05/kubewaste/actions/workflows/ci.yml/badge.svg)](https://github.com/bhupendra05/kubewaste/actions)
[![PyPI](https://img.shields.io/pypi/v/kubewaste)](https://pypi.org/project/kubewaste/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## The problem

Your team requested `cpu: 4` and `memory: 8Gi` per pod.  
Actual usage: `200m` CPU and `512Mi` RAM.

That's **95% waste**. Multiplied by 50 pods. Across 3 clusters.  
You're paying $8,000/month for work that costs $400.

`kubewaste` finds every over-provisioned container and tells you exactly how much you could save.

---

## Sample output

```
──────────────────────────────────────────────────────────────────────
  kubewaste — Kubernetes Resource Waste Report
  Cluster: production   Namespace: all namespaces
──────────────────────────────────────────────────────────────────────

  SEVERITY   NAMESPACE        POD                            CONTAINER   CPU REQ  CPU USE    %   MEM REQ  MEM USE    %
  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  critical   payments         payment-api-7d9f-xk2p          app          2 cores    80m    4%   4.00 GiB  210 MiB   5%
  critical   analytics        spark-worker-0                 spark        4 cores   120m    3%   8.00 GiB  380 MiB   5%
  high       auth             auth-svc-8b4c-jk9m             api        500m       85m    17%   512 MiB   95 MiB   19%
  medium     staging          web-frontend-6d7b-mp3q         nginx      200m       80m    40%   256 MiB  110 MiB   43%

──────────────────────────────────────────────────────────────────────
  Total CPU waste : 7.32 cores
  Total MEM waste : 11.88 GiB
  Est. savings    : $267.74/month  ($3,212/year)

  Unused resources: 3
    [ConfigMap] analytics/old-spark-config  — Not referenced by any pod
    [PVC]       staging/unused-data-pvc     — PVC not mounted by any running pod
──────────────────────────────────────────────────────────────────────
```

---

## Installation

```bash
# Core (models + CLI)
pip install kubewaste

# With Kubernetes client
pip install "kubewaste[k8s]"
```

---

## CLI usage

```bash
# Scan all namespaces
kubewaste scan

# Scan one namespace
kubewaste scan --namespace production

# Only show critical waste (< 10% utilisation)
kubewaste scan --min-severity critical

# Custom utilisation threshold
kubewaste scan --threshold 30    # flag containers using < 30% of requested

# Top 10 worst containers
kubewaste scan --top 10

# JSON output (for dashboards / CI)
kubewaste scan --json > waste_report.json

# Use a specific kubectl context
kubewaste scan --context staging-cluster

# Skip unused resource scan
kubewaste scan --no-unused

# List available contexts
kubewaste contexts
```

---

## Python API

```python
from kubewaste import KubeWasteAnalyzer

analyzer = KubeWasteAnalyzer()   # uses current kubeconfig context
report = analyzer.analyze(namespace="production")

print(f"Wasted CPU  : {report.total_cpu_waste_m:.0f}m")
print(f"Wasted RAM  : {report.total_mem_waste_mib:.0f} MiB")
print(f"Savings     : ${report.estimated_monthly_savings_usd():.2f}/month")

# Critical containers only
for c in report.critical_containers:
    print(f"{c.namespace}/{c.pod}/{c.container}")
    print(f"  CPU: {c.cpu_requested_m:.0f}m requested, {c.cpu_used_m:.0f}m used ({c.cpu_utilisation_pct:.0f}%)")
    print(f"  RAM: {c.mem_requested_mib:.0f}MiB requested, {c.mem_used_mib:.0f}MiB used ({c.mem_utilisation_pct:.0f}%)")
```

---

## Severity levels

| Severity | CPU or RAM utilisation |
|---|---|
| **Critical** | < 10% |
| **High** | 10–25% |
| **Medium** | 25–50% |
| **Low** | 50–threshold% |

---

## Cost estimation

Default pricing (AWS on-demand, configurable):

```python
savings = report.estimated_monthly_savings_usd(
    cpu_per_core_usd=30.0,   # ~$30/core/month
    mem_per_gb_usd=4.0,      # ~$4/GiB/month
)
```

---

## Requirements

- Kubernetes cluster with `kubectl` access (kubeconfig)
- [metrics-server](https://github.com/kubernetes-sigs/metrics-server) installed for live usage data

```bash
# Install metrics-server (if not present)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

Without metrics-server, kubewaste reports 0 actual usage — still useful for finding unused ConfigMaps and PVCs.

---

## CI/CD integration

```yaml
# Weekly waste report
- name: Check K8s resource waste
  run: |
    pip install "kubewaste[k8s]"
    kubewaste scan --json --min-severity high > waste.json
    cat waste.json | python -c "
    import json,sys
    r=json.load(sys.stdin)
    savings=r['estimated_monthly_savings_usd']
    print(f'Potential savings: \${savings:.2f}/month')
    "
```

---

## Running tests

Tests run without a Kubernetes cluster — models and business logic only.

```bash
git clone https://github.com/bhupendra05/kubewaste
cd kubewaste
pip install -e ".[dev]"
pytest -v
```

---

## License

MIT © [Bhupendra Tale](https://github.com/bhupendra05)
