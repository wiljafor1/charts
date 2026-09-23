"""Render real Helm templates and assert operational invariants; no cluster writes."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "standard"
BASE = {"image": {"repository": "registry.example.com/test/app", "tag": "1.2.3"}}


def render(values=None, *, files=(), crds=True, success=True):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base.json"
        custom = Path(tmp) / "custom.json"
        base.write_text(json.dumps(BASE))
        custom.write_text(json.dumps(values or {}))
        args = ["helm", "template", "sample", str(CHART), "-n", "apps", "--kube-version", "1.36.4", "-f", str(base)]
        if crds:
            args += ["--api-versions", "monitoring.coreos.com/v1/ServiceMonitor"]
        for file in files:
            args += ["-f", str(ROOT / file)]
        args += ["-f", str(custom)]
        result = subprocess.run(args, text=True, capture_output=True, check=False)
    if not success:
        if result.returncode == 0:
            raise AssertionError("Invalid values unexpectedly rendered successfully")
        return result.stderr
    if result.returncode:
        raise AssertionError(result.stderr)
    docs = [d for d in yaml.safe_load_all(result.stdout) if d]
    return {d["kind"]: d for d in docs}


def pod(docs):
    return docs["Deployment"]["spec"]["template"]["spec"]


class StandardChartTests(unittest.TestCase):
    def test_default_budget_and_private_exposure(self):
        docs = render()
        self.assertEqual(set(docs), {"Deployment", "Service", "ServiceAccount"})
        dep = docs["Deployment"]
        app = pod(docs)["containers"][0]
        self.assertEqual(app["resources"]["requests"], {"cpu": "100m", "memory": "128Mi", "ephemeral-storage": "64Mi"})
        self.assertEqual(app["resources"]["limits"]["memory"], "256Mi")
        self.assertEqual(dep["spec"]["replicas"], 1)
        self.assertEqual(dep["spec"]["strategy"]["rollingUpdate"]["maxSurge"], 0)
        self.assertEqual(docs["Service"]["spec"]["type"], "ClusterIP")
        self.assertFalse(pod(docs)["automountServiceAccountToken"])
        self.assertTrue(app["securityContext"]["readOnlyRootFilesystem"])
        self.assertNotIn("livenessProbe", app)
        self.assertEqual(app["startupProbe"]["tcpSocket"], {"port": "http"})
        self.assertNotIn("enabled", app["startupProbe"])
        self.assertNotIn("type", app["startupProbe"])

    def test_api_and_tls_overlay_routes_to_correct_service(self):
        docs = render(files=["examples/api.values.yaml", "examples/traefik-tls.values.yaml"])
        app = pod(docs)["containers"][0]
        self.assertEqual(app["readinessProbe"]["httpGet"]["path"], "/readyz")
        self.assertNotIn("tcpSocket", app["readinessProbe"])
        self.assertEqual(app["env"][0]["valueFrom"]["secretKeyRef"]["name"], "api-secrets")
        self.assertNotIn("Secret", docs)
        ing = docs["Ingress"]["spec"]
        backend = ing["rules"][0]["http"]["paths"][0]["backend"]["service"]
        self.assertEqual(backend["name"], docs["Service"]["metadata"]["name"])
        self.assertEqual(backend["port"]["name"], "http")
        self.assertEqual(ing["tls"][0]["secretName"], "app-tls")

    def test_worker_has_no_service_or_network_probes(self):
        docs = render(files=["examples/worker.values.yaml"])
        self.assertEqual(set(docs), {"Deployment", "ServiceAccount"})
        app = pod(docs)["containers"][0]
        for name in ["startupProbe", "readinessProbe", "livenessProbe"]:
            self.assertNotIn(name, app)
        self.assertEqual(app["command"], ["/app/worker"])

    def test_hpa_owns_replicas_and_pdb_selects_same_pods(self):
        docs = render(files=["examples/autoscaling.values.yaml"])
        self.assertNotIn("replicas", docs["Deployment"]["spec"])
        self.assertEqual(docs["HorizontalPodAutoscaler"]["spec"]["maxReplicas"], 3)
        self.assertEqual(docs["PodDisruptionBudget"]["spec"]["selector"], docs["Deployment"]["spec"]["selector"])
        self.assertEqual(docs["HorizontalPodAutoscaler"]["spec"]["scaleTargetRef"]["name"], docs["Deployment"]["metadata"]["name"])
        self.assertEqual(docs["Deployment"]["spec"]["strategy"]["rollingUpdate"]["maxSurge"], 1)

    def test_memory_only_hpa_and_zero_pdb_budget(self):
        docs = render({"autoscaling": {"enabled": True, "targetCPUUtilizationPercentage": None, "targetMemoryUtilizationPercentage": 75}, "pdb": {"enabled": True, "minAvailable": 0, "maxUnavailable": None}})
        self.assertEqual([m["resource"]["name"] for m in docs["HorizontalPodAutoscaler"]["spec"]["metrics"]], ["memory"])
        self.assertEqual(docs["PodDisruptionBudget"]["spec"]["minAvailable"], 0)
        self.assertNotIn("maxUnavailable", docs["PodDisruptionBudget"]["spec"])

    def test_single_writer_pvc_avoids_overlap_and_is_retained(self):
        docs = render(files=["examples/persistence.values.yaml"])
        self.assertEqual(docs["Deployment"]["spec"]["strategy"], {"type": "Recreate"})
        pvc = docs["PersistentVolumeClaim"]
        self.assertEqual(pvc["metadata"]["annotations"]["helm.sh/resource-policy"], "keep")
        self.assertNotIn("storageClassName", pvc["spec"])
        volume = next(v for v in pod(docs)["volumes"] if v["name"] == "data")
        self.assertEqual(volume["persistentVolumeClaim"]["claimName"], pvc["metadata"]["name"])

    def test_existing_pvc_and_service_account_are_reused(self):
        docs = render({"persistence": {"enabled": True, "existingClaim": "app-data"}, "serviceAccount": {"create": False, "name": "app-identity"}})
        self.assertNotIn("PersistentVolumeClaim", docs)
        self.assertNotIn("ServiceAccount", docs)
        self.assertEqual(pod(docs)["serviceAccountName"], "app-identity")
        self.assertEqual(next(v for v in pod(docs)["volumes"] if v["name"] == "data")["persistentVolumeClaim"]["claimName"], "app-data")

    def test_rwx_persistence_supports_replicas_and_explicit_storage_class(self):
        docs = render({"replicaCount": 2, "persistence": {"enabled": True, "accessModes": ["ReadWriteMany"], "storageClass": "shared", "retain": False}})
        self.assertEqual(docs["Deployment"]["spec"]["strategy"]["type"], "RollingUpdate")
        self.assertEqual(docs["PersistentVolumeClaim"]["spec"]["storageClassName"], "shared")
        self.assertNotIn("annotations", docs["PersistentVolumeClaim"]["metadata"])
        no_class = render({"persistence": {"enabled": True, "storageClass": "-"}})
        self.assertEqual(no_class["PersistentVolumeClaim"]["spec"]["storageClassName"], "")

    def test_config_change_triggers_rollout_and_secret_reference_is_preserved(self):
        first = render({"configMap": {"enabled": True, "data": {"MODE": "one"}}})
        second = render({"configMap": {"enabled": True, "data": {"MODE": "two"}}})
        annotation = lambda d: d["Deployment"]["spec"]["template"]["metadata"]["annotations"]["checksum/config"]
        self.assertNotEqual(annotation(first), annotation(second))
        self.assertEqual(len(annotation(first)), len(hashlib.sha256().hexdigest()))
        self.assertEqual(pod(first)["containers"][0]["envFrom"][0]["configMapRef"]["name"], first["ConfigMap"]["metadata"]["name"])

    def test_custom_labels_cannot_break_selectors_and_long_names_keep_suffix(self):
        docs = render({"fullnameOverride": "a" * 63, "commonLabels": {"app.kubernetes.io/name": "wrong"}, "podLabels": {"app.kubernetes.io/instance": "wrong"}, "configMap": {"enabled": True}})
        labels = docs["Deployment"]["spec"]["template"]["metadata"]["labels"]
        for key, value in docs["Service"]["spec"]["selector"].items():
            self.assertEqual(labels[key], value)
        name = docs["ConfigMap"]["metadata"]["name"]
        self.assertLessEqual(len(name), 63)
        self.assertTrue(name.endswith("-config"))

    def test_digest_and_no_optional_volumes(self):
        digest = "sha256:" + "a" * 64
        docs = render({"image": {"digest": digest}, "tmpVolume": {"enabled": False}})
        self.assertEqual(pod(docs)["containers"][0]["image"], BASE["image"]["repository"] + "@" + digest)
        self.assertNotIn("volumes", pod(docs))
        self.assertNotIn("volumeMounts", pod(docs)["containers"][0])

    def test_servicemonitor_uses_named_service_port_and_release_namespace(self):
        docs = render({"service": {"extraPorts": [{"name": "metrics", "port": 9090, "targetPort": 9090}]}, "serviceMonitor": {"enabled": True, "port": "metrics", "labels": {"release": "monitoring"}}})
        monitor = docs["ServiceMonitor"]
        self.assertEqual(monitor["spec"]["endpoints"][0]["port"], "metrics")
        self.assertEqual(monitor["spec"]["namespaceSelector"]["matchNames"], ["apps"])
        self.assertEqual(monitor["metadata"]["labels"]["release"], "monitoring")
        self.assertEqual(monitor["spec"]["selector"], {"matchLabels": docs["Service"]["spec"]["selector"]})

    def test_extra_config_volume_and_exec_probe(self):
        docs = render({"extraVolumes": [{"name": "config", "configMap": {"name": "shared-config"}}], "extraVolumeMounts": [{"name": "config", "mountPath": "/etc/app", "readOnly": True}], "readinessProbe": {"type": "exec", "exec": {"command": ["/app/healthcheck"]}}})
        self.assertEqual(pod(docs)["containers"][0]["readinessProbe"]["exec"]["command"], ["/app/healthcheck"])
        self.assertNotIn("tcpSocket", pod(docs)["containers"][0]["readinessProbe"])

    def test_invalid_combinations_fail_before_install(self):
        invalid = [
            {"image": {"repository": ""}},
            {"image": {"tag": "", "digest": ""}},
            {"resources": {"limits": {"memory": None}}},
            {"resources": {"requests": {"cpu": "0"}}},
            {"resoruces": {}},
            {"service": {"enabled": False}, "ingress": {"enabled": True, "hosts": [{"host": "example.com", "paths": [{"path": "/", "pathType": "Prefix"}]}]}},
            {"ingress": {"enabled": True}},
            {"autoscaling": {"enabled": True, "minReplicas": 3, "maxReplicas": 2}},
            {"autoscaling": {"enabled": True, "targetCPUUtilizationPercentage": None, "targetMemoryUtilizationPercentage": None}},
            {"pdb": {"enabled": True}},
            {"pdb": {"enabled": True, "minAvailable": 1, "maxUnavailable": 1}},
            {"persistence": {"enabled": True}, "replicaCount": 2},
            {"persistence": {"enabled": True}, "autoscaling": {"enabled": True}},
            {"serviceMonitor": {"enabled": True, "port": "missing"}},
            {"serviceMonitor": {"enabled": True, "interval": "1m", "scrapeTimeout": "61s"}},
            {"strategy": {"rollingUpdate": {"maxSurge": "0%", "maxUnavailable": 0}}},
            {"serviceMonitor": {"enabled": True}, "service": {"enabled": False}},
            {"service": {"extraPorts": [{"name": "http", "port": 9090, "targetPort": 9090}]}},
            {"configMap": {"data": {"PORT": 8080}}},
            {"env": [{"name": "VALUE", "value": 123}]},
            {"env": [{"name": "VALUE", "value": "x", "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}}}]},
            {"livenessProbe": {"enabled": True}},
            {"extraVolumes": [{"name": "tmp", "emptyDir": {}}]},
            {"extraVolumeMounts": [{"name": "missing", "mountPath": "/etc/app"}]},
        ]
        for values in invalid:
            with self.subTest(values=values):
                render(values, success=False)

    def test_monitor_renders_offline_without_api_discovery(self):
        docs = render({"serviceMonitor": {"enabled": True}}, crds=False)
        self.assertEqual(docs["ServiceMonitor"]["apiVersion"], "monitoring.coreos.com/v1")


if __name__ == "__main__":
    unittest.main()
