"""Tests for the argocd_parser module."""

from __future__ import annotations

import json
import pytest

from src.argocd_parser import (
    ArgoApp,
    HealthStatus,
    ResourceStatus,
    SyncStatus,
    get_sync_failure_reasons,
    parse_argocd_app,
    parse_health_status,
    parse_resources,
    parse_sync_status,
)


class TestResourceStatus:
    """Tests for the ResourceStatus dataclass."""

    def test_defaults(self):
        r = ResourceStatus(kind="Deployment", name="web")
        assert r.namespace == ""
        assert r.status == "Unknown"
        assert r.health == "Unknown"
        assert r.is_healthy is False
        assert r.is_synced is False

    def test_healthy_and_synced(self):
        r = ResourceStatus(
            kind="Deployment", name="web", status="Synced", health="Healthy"
        )
        assert r.is_healthy is True
        assert r.is_synced is True

    def test_unhealthy(self):
        r = ResourceStatus(
            kind="Pod", name="web-abc", status="Synced", health="Degraded"
        )
        assert r.is_healthy is False
        assert r.is_synced is True


class TestSyncStatus:
    """Tests for the SyncStatus dataclass."""

    def test_defaults(self):
        s = SyncStatus()
        assert s.status == "Unknown"
        assert s.is_synced is False

    def test_synced(self):
        s = SyncStatus(status="Synced", revision="abc123")
        assert s.is_synced is True
        assert s.revision == "abc123"

    def test_out_of_sync(self):
        s = SyncStatus(status="OutOfSync")
        assert s.is_synced is False


class TestHealthStatus:
    """Tests for the HealthStatus dataclass."""

    def test_defaults(self):
        h = HealthStatus()
        assert h.status == "Unknown"
        assert h.is_healthy is False

    def test_healthy(self):
        h = HealthStatus(status="Healthy")
        assert h.is_healthy is True

    def test_degraded(self):
        h = HealthStatus(status="Degraded", message="CrashLoopBackOff")
        assert h.is_healthy is False
        assert h.message == "CrashLoopBackOff"


class TestArgoApp:
    """Tests for the ArgoApp dataclass."""

    def test_defaults(self):
        app = ArgoApp(name="test-app")
        assert app.namespace == ""
        assert app.project == "default"
        assert app.is_healthy is False
        assert app.is_synced is False
        assert len(app.resources) == 0

    def test_healthy_synced(self):
        app = ArgoApp(
            name="test-app",
            sync=SyncStatus(status="Synced"),
            health=HealthStatus(status="Healthy"),
        )
        assert app.is_healthy is True
        assert app.is_synced is True
        assert len(app.unhealthy_resources) == 0
        assert len(app.unsynced_resources) == 0

    def test_unhealthy_resources(self):
        app = ArgoApp(
            name="test-app",
            resources=[
                ResourceStatus("Deployment", "web", health="Healthy", status="Synced"),
                ResourceStatus("Pod", "web-abc", health="Degraded", status="Synced"),
                ResourceStatus("Service", "svc", health="Healthy", status="OutOfSync"),
            ],
        )
        assert len(app.unhealthy_resources) == 1
        assert app.unhealthy_resources[0].kind == "Pod"
        assert len(app.unsynced_resources) == 1
        assert app.unsynced_resources[0].kind == "Service"

    def test_failed_conditions(self):
        app = ArgoApp(
            name="test-app",
            conditions=[
                {"type": "SyncError", "status": "False", "message": "sync failed"},
                {"type": "SharedResourceWarning", "status": "True", "message": "ok"},
            ],
        )
        assert len(app.failed_conditions) == 1
        assert app.failed_conditions[0]["type"] == "SyncError"

    def test_summary(self):
        app = ArgoApp(
            name="test-app",
            sync=SyncStatus(status="OutOfSync"),
            health=HealthStatus(status="Degraded", message="issues"),
            resources=[
                ResourceStatus("Deployment", "web", health="Healthy", status="Synced"),
                ResourceStatus("Pod", "p1", health="Degraded", status="Synced"),
            ],
        )
        summary = app.summary
        assert summary["name"] == "test-app"
        assert summary["sync_status"] == "OutOfSync"
        assert summary["health_status"] == "Degraded"
        assert summary["total_resources"] == 2
        assert summary["unhealthy_count"] == 1


class TestParseHealthStatus:
    """Tests for parse_health_status."""

    def test_parse(self):
        h = parse_health_status({"status": "Healthy", "message": "all good"})
        assert h.status == "Healthy"
        assert h.message == "all good"

    def test_empty(self):
        h = parse_health_status({})
        assert h.status == "Unknown"
        assert h.message == ""


class TestParseSyncStatus:
    """Tests for parse_sync_status."""

    def test_parse(self):
        s = parse_sync_status({"status": "Synced", "revision": "abc123"})
        assert s.status == "Synced"
        assert s.revision == "abc123"

    def test_with_compared_to(self):
        s = parse_sync_status({
            "status": "OutOfSync",
            "comparedTo": {"source": {"repoURL": "https://example.com"}},
        })
        assert s.status == "OutOfSync"
        assert "source" in s.compared_to


class TestParseResources:
    """Tests for parse_resources."""

    def test_parse_single(self):
        data = [
            {
                "kind": "Deployment",
                "name": "web",
                "namespace": "default",
                "status": "Synced",
                "health": {"status": "Healthy", "message": ""},
            }
        ]
        resources = parse_resources(data)
        assert len(resources) == 1
        assert resources[0].kind == "Deployment"
        assert resources[0].health == "Healthy"

    def test_parse_multiple(self):
        data = [
            {"kind": "Deployment", "name": "web", "health": {"status": "Healthy"}},
            {"kind": "Service", "name": "svc", "health": {"status": "Healthy"}},
            {"kind": "Pod", "name": "p1", "health": {"status": "Degraded"}},
        ]
        resources = parse_resources(data)
        assert len(resources) == 3
        assert resources[2].health == "Degraded"

    def test_empty_list(self):
        resources = parse_resources([])
        assert len(resources) == 0

    def test_missing_health(self):
        data = [{"kind": "Deployment", "name": "web"}]
        resources = parse_resources(data)
        assert resources[0].health == "Unknown"


class TestParseArgocdApp:
    """Tests for parse_argocd_app."""

    def test_full_app_json(self):
        app_data = {
            "metadata": {"name": "my-app", "namespace": "argocd"},
            "spec": {
                "project": "default",
                "source": {
                    "repoURL": "https://github.com/example/repo",
                    "path": "k8s",
                },
            },
            "status": {
                "sync": {"status": "OutOfSync", "revision": "abc123"},
                "health": {"status": "Degraded", "message": "CrashLoopBackOff"},
                "resources": [
                    {
                        "kind": "Deployment",
                        "name": "web",
                        "status": "OutOfSync",
                        "health": {"status": "Degraded"},
                    }
                ],
                "conditions": [
                    {"type": "SyncError", "status": "False", "message": "sync failed"}
                ],
                "operationState": {
                    "phase": "Failed",
                    "message": "one or more objects failed to apply",
                },
            },
        }
        app = parse_argocd_app(app_data)
        assert app.name == "my-app"
        assert app.namespace == "argocd"
        assert app.project == "default"
        assert app.sync.status == "OutOfSync"
        assert app.sync.revision == "abc123"
        assert app.health.status == "Degraded"
        assert len(app.resources) == 1
        assert app.resources[0].kind == "Deployment"
        assert len(app.conditions) == 1
        assert app.operation_state["phase"] == "Failed"
        assert app.source["repoURL"] == "https://github.com/example/repo"

    def test_json_string_input(self):
        app_data = {
            "metadata": {"name": "test"},
            "spec": {},
            "status": {
                "sync": {"status": "Synced"},
                "health": {"status": "Healthy"},
                "resources": [],
            },
        }
        app = parse_argocd_app(json.dumps(app_data))
        assert app.name == "test"
        assert app.is_synced is True
        assert app.is_healthy is True

    def test_healthy_app(self):
        app_data = {
            "metadata": {"name": "prod-app"},
            "spec": {"project": "production"},
            "status": {
                "sync": {"status": "Synced", "revision": "def456"},
                "health": {"status": "Healthy"},
                "resources": [
                    {"kind": "Deployment", "name": "api", "status": "Synced",
                     "health": {"status": "Healthy"}},
                    {"kind": "Service", "name": "api-svc", "status": "Synced",
                     "health": {"status": "Healthy"}},
                ],
            },
        }
        app = parse_argocd_app(app_data)
        assert app.is_healthy is True
        assert app.is_synced is True
        assert len(app.unhealthy_resources) == 0

    def test_empty_status(self):
        app = parse_argocd_app({"metadata": {}, "spec": {}, "status": {}})
        assert app.name == "unknown"
        assert app.sync.status == "Unknown"
        assert app.health.status == "Unknown"
        assert len(app.resources) == 0

    def test_multi_source(self):
        """Test parsing with spec.sources (array) instead of spec.source."""
        app_data = {
            "metadata": {"name": "multi"},
            "spec": {
                "sources": [
                    {"repoURL": "https://github.com/example/repo1", "path": "base"},
                    {"repoURL": "https://github.com/example/repo2", "path": "overlay"},
                ],
            },
            "status": {
                "sync": {"status": "Synced"},
                "health": {"status": "Healthy"},
            },
        }
        app = parse_argocd_app(app_data)
        assert app.source["repoURL"] == "https://github.com/example/repo1"


class TestGetSyncFailureReasons:
    """Tests for get_sync_failure_reasons."""

    def test_no_failures(self):
        app = ArgoApp(
            name="healthy",
            sync=SyncStatus(status="Synced"),
            health=HealthStatus(status="Healthy"),
        )
        reasons = get_sync_failure_reasons(app)
        assert reasons == ["No obvious failure detected."]

    def test_operation_failed(self):
        app = ArgoApp(
            name="failed",
            sync=SyncStatus(status="OutOfSync"),
            health=HealthStatus(status="Degraded"),
            operation_state={
                "phase": "Failed",
                "message": "one or more objects failed",
                "syncResult": {
                    "resources": [
                        {
                            "kind": "Deployment",
                            "name": "web",
                            "status": "Failed",
                            "message": "field is immutable",
                        }
                    ]
                },
            },
        )
        reasons = get_sync_failure_reasons(app)
        assert len(reasons) >= 2
        assert any("Failed" in r for r in reasons)
        assert any("Deployment/web" in r for r in reasons)

    def test_health_issues(self):
        app = ArgoApp(
            name="unhealthy",
            sync=SyncStatus(status="Synced"),
            health=HealthStatus(status="Degraded", message="1 pod crashing"),
            resources=[
                ResourceStatus("Pod", "web-abc", health="Degraded", message="CrashLoopBackOff"),
            ],
        )
        reasons = get_sync_failure_reasons(app)
        assert any("1 pod crashing" in r for r in reasons)
        assert any("CrashLoopBackOff" in r for r in reasons)

    def test_out_of_sync(self):
        app = ArgoApp(
            name="out-of-sync",
            sync=SyncStatus(status="OutOfSync", revision="abc123"),
            health=HealthStatus(status="Healthy"),
            resources=[
                ResourceStatus("ConfigMap", "cfg", status="OutOfSync", health="Healthy"),
            ],
        )
        reasons = get_sync_failure_reasons(app)
        assert any("OutOfSync" in r for r in reasons)
        assert any("abc123" in r for r in reasons)

    def test_conditions(self):
        app = ArgoApp(
            name="cond-app",
            sync=SyncStatus(status="Synced"),
            health=HealthStatus(status="Healthy"),
            conditions=[
                {"type": "SharedResourceWarning", "status": "False", "message": "shared ns"},
            ],
        )
        reasons = get_sync_failure_reasons(app)
        assert any("SharedResourceWarning" in r for r in reasons)

    def test_operation_error_phase(self):
        app = ArgoApp(
            name="error-app",
            operation_state={"phase": "Error", "message": "connection refused"},
        )
        reasons = get_sync_failure_reasons(app)
        assert any("Error" in r for r in reasons)
        assert any("connection refused" in r for r in reasons)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
