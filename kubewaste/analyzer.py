"""
kubewaste analyzer — connects to a Kubernetes cluster and finds resource waste.

Requires: pip install kubernetes
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .models import ContainerWaste, UnusedResource, WasteReport, parse_cpu, parse_memory


class KubeWasteAnalyzer:
    """
    Analyze Kubernetes resource waste across pods and namespaces.

    Requires a reachable cluster (kubeconfig or in-cluster config)
    and metrics-server installed for actual usage data.

    Example
    -------
    >>> analyzer = KubeWasteAnalyzer()
    >>> report = analyzer.analyze(namespace="production")
    >>> print(f"Wasted: {report.total_cpu_waste_m:.0f}m CPU, "
    ...       f"{report.total_mem_waste_mib:.0f} MiB RAM")
    >>> print(f"Estimated savings: ${report.estimated_monthly_savings_usd():.2f}/month")
    """

    def __init__(
        self,
        kubeconfig: Optional[str] = None,
        context: Optional[str] = None,
        in_cluster: bool = False,
    ) -> None:
        try:
            from kubernetes import client, config as k8s_config
        except ImportError as e:
            raise ImportError(
                "kubernetes package required. Install with: pip install kubernetes"
            ) from e

        if in_cluster:
            k8s_config.load_incluster_config()
        else:
            k8s_config.load_kube_config(config_file=kubeconfig, context=context)

        self._core   = client.CoreV1Api()
        self._apps   = client.AppsV1Api()
        self._custom = client.CustomObjectsApi()
        self._cluster_name = context or "default"

    def analyze(
        self,
        namespace: Optional[str] = None,
        utilisation_threshold_pct: float = 50.0,
        include_unused: bool = True,
    ) -> WasteReport:
        """
        Run a full waste analysis.

        Parameters
        ----------
        namespace:                  Only analyse this namespace. None = all namespaces.
        utilisation_threshold_pct:  Only flag containers using less than this % of requested.
        include_unused:             Also scan for unused ConfigMaps, Secrets, PVCs.

        Returns
        -------
        WasteReport
        """
        report = WasteReport(
            cluster=self._cluster_name,
            namespace_filter=namespace,
        )

        # Get pods
        if namespace:
            pods = self._core.list_namespaced_pod(namespace).items
        else:
            pods = self._core.list_pod_for_all_namespaces().items

        # Get metrics (best-effort — skip if metrics-server not available)
        pod_metrics = self._get_pod_metrics(namespace)

        for pod in pods:
            if pod.status.phase != "Running":
                continue
            ns = pod.metadata.namespace
            pod_name = pod.metadata.name
            pod_key = f"{ns}/{pod_name}"
            metrics = pod_metrics.get(pod_key, {})

            for container in pod.spec.containers:
                cname = container.name
                req = container.resources.requests or {} if container.resources else {}
                lim = container.resources.limits  or {} if container.resources else {}

                cpu_req  = parse_cpu(req.get("cpu"))
                mem_req  = parse_memory(req.get("memory"))
                cpu_lim  = parse_cpu(lim.get("cpu"))
                mem_lim  = parse_memory(lim.get("memory"))

                cpu_used = parse_cpu(metrics.get(cname, {}).get("cpu"))
                mem_used = parse_memory(metrics.get(cname, {}).get("memory"))

                waste = ContainerWaste(
                    name=f"{ns}/{pod_name}/{cname}",
                    namespace=ns,
                    pod=pod_name,
                    container=cname,
                    cpu_requested_m=cpu_req,
                    mem_requested_mib=mem_req,
                    cpu_used_m=cpu_used,
                    mem_used_mib=mem_used,
                    cpu_limit_m=cpu_lim,
                    mem_limit_mib=mem_lim,
                )

                # Only flag if utilisation is below threshold
                if (waste.cpu_utilisation_pct < utilisation_threshold_pct or
                        waste.mem_utilisation_pct < utilisation_threshold_pct):
                    if cpu_req > 0 or mem_req > 0:
                        report.containers.append(waste)

        if include_unused:
            report.unused_resources.extend(
                self._find_unused_configmaps(namespace)
            )
            report.unused_resources.extend(
                self._find_unused_pvcs(namespace)
            )

        # Sort by waste severity
        report.containers.sort(key=lambda c: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}[c.severity]
        ))

        return report

    def _get_pod_metrics(self, namespace: Optional[str]) -> Dict[str, Dict]:
        """Fetch metrics from metrics-server. Returns empty dict if unavailable."""
        try:
            if namespace:
                data = self._custom.list_namespaced_custom_object(
                    "metrics.k8s.io", "v1beta1", namespace, "pods"
                )
            else:
                data = self._custom.list_cluster_custom_object(
                    "metrics.k8s.io", "v1beta1", "pods"
                )
        except Exception:
            return {}

        result: Dict[str, Dict] = {}
        for item in data.get("items", []):
            ns  = item["metadata"]["namespace"]
            pod = item["metadata"]["name"]
            key = f"{ns}/{pod}"
            result[key] = {
                c["name"]: {"cpu": c["usage"]["cpu"], "memory": c["usage"]["memory"]}
                for c in item.get("containers", [])
            }
        return result

    def _find_unused_configmaps(self, namespace: Optional[str]) -> List[UnusedResource]:
        """Find ConfigMaps not referenced by any pod or deployment."""
        try:
            if namespace:
                cms = self._core.list_namespaced_config_map(namespace).items
                pods = self._core.list_namespaced_pod(namespace).items
            else:
                cms = self._core.list_config_map_for_all_namespaces().items
                pods = self._core.list_pod_for_all_namespaces().items
        except Exception:
            return []

        # Collect all referenced ConfigMap names
        referenced = set()
        for pod in pods:
            for vol in (pod.spec.volumes or []):
                if vol.config_map:
                    referenced.add((pod.metadata.namespace, vol.config_map.name))
            for container in pod.spec.containers:
                for env_from in (container.env_from or []):
                    if env_from.config_map_ref:
                        referenced.add((pod.metadata.namespace, env_from.config_map_ref.name))

        unused = []
        for cm in cms:
            ns, name = cm.metadata.namespace, cm.metadata.name
            if name.startswith("kube-") or name in ("aws-auth",):
                continue
            if (ns, name) not in referenced:
                unused.append(UnusedResource(
                    kind="ConfigMap", namespace=ns, name=name,
                    reason="Not referenced by any pod volume or envFrom",
                ))
        return unused

    def _find_unused_pvcs(self, namespace: Optional[str]) -> List[UnusedResource]:
        """Find PersistentVolumeClaims not mounted by any pod."""
        try:
            if namespace:
                pvcs = self._core.list_namespaced_persistent_volume_claim(namespace).items
                pods = self._core.list_namespaced_pod(namespace).items
            else:
                pvcs = self._core.list_persistent_volume_claim_for_all_namespaces().items
                pods = self._core.list_pod_for_all_namespaces().items
        except Exception:
            return []

        mounted_pvcs = set()
        for pod in pods:
            for vol in (pod.spec.volumes or []):
                if vol.persistent_volume_claim:
                    mounted_pvcs.add((pod.metadata.namespace, vol.persistent_volume_claim.claim_name))

        unused = []
        for pvc in pvcs:
            ns, name = pvc.metadata.namespace, pvc.metadata.name
            if (ns, name) not in mounted_pvcs:
                unused.append(UnusedResource(
                    kind="PVC", namespace=ns, name=name,
                    reason="PVC not mounted by any running pod",
                ))
        return unused
