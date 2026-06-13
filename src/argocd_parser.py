"""ArgoCD application status parser - extracts and structures ArgoCD app data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ResourceStatus:
    """Status of a single Kubernetes resource managed by ArgoCD."""

    kind: str
    name: str
    namespace: str = ""
    status: str = "Unknown"  # Synced, OutOfSync, Missing, Unknown
    health: str = "Unknown"  # Healthy, Degraded, Progressing, Missing, Suspended
    message: str = ""

    @property
    def is_healthy(self) -> bool:
        return self.health == "Healthy"

    @property
    def is_synced(self) -> bool:
        return self.status == "Synced"


@dataclass
class SyncStatus:
    """Overall sync status of an ArgoCD application."""

    status: str = "Unknown"  # Synced, OutOfSync, Unknown
    revision: str = ""
    compared_to: dict[str, Any] = field(default_factory=dict)

    @property
    def is_synced(self) -> bool:
        return self.status == "Synced"


@dataclass
class HealthStatus:
    """Overall health status of an ArgoCD application."""

    status: str = "Unknown"  # Healthy, Degraded, Progressing, Missing, Suspended
    message: str = ""

    @property
    def is_healthy(self) -> bool:
        return self.status == "Healthy"


@dataclass
class ArgoApp:
    """Parsed ArgoCD application status."""

    name: str
    namespace: str = ""
    project: str = "default"
    sync: SyncStatus = field(default_factory=SyncStatus)
    health: HealthStatus = field(default_factory=HealthStatus)
    resources: list[ResourceStatus] = field(default_factory=list)
    conditions: list[dict[str, str]] = field(default_factory=list)
    operation_state: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        return self.health.is_healthy

    @property
    def is_synced(self) -> bool:
        return self.sync.is_synced

    @property
    def unhealthy_resources(self) -> list[ResourceStatus]:
        return [r for r in self.resources if not r.is_healthy]

    @property
    def unsynced_resources(self) -> list[ResourceStatus]:
        return [r for r in self.resources if not r.is_synced]

    @property
    def failed_conditions(self) -> list[dict[str, str]]:
        return [c for c in self.conditions if c.get("status", "").lower() != "true"]

    @property
    def summary(self) -> dict[str, Any]:
        """Return a concise summary of the app status."""
        return {
            "name": self.name,
            "sync_status": self.sync.status,
            "health_status": self.health.status,
            "health_message": self.health.message,
            "total_resources": len(self.resources),
            "unhealthy_count": len(self.unhealthy_resources),
            "unsynced_count": len(self.unsynced_resources),
            "failed_conditions": len(self.failed_conditions),
        }


def parse_health_status(health_data: dict[str, Any]) -> HealthStatus:
    """Parse ArgoCD health status from JSON."""
    return HealthStatus(
        status=health_data.get("status", "Unknown"),
        message=health_data.get("message", ""),
    )


def parse_sync_status(sync_data: dict[str, Any]) -> SyncStatus:
    """Parse ArgoCD sync status from JSON."""
    return SyncStatus(
        status=sync_data.get("status", "Unknown"),
        revision=sync_data.get("revision", ""),
        compared_to=sync_data.get("comparedTo", {}),
    )


def parse_resources(resources_data: list[dict[str, Any]]) -> list[ResourceStatus]:
    """Parse ArgoCD resource statuses from JSON."""
    resources = []
    for res in resources_data:
        health = res.get("health", {})
        status = ResourceStatus(
            kind=res.get("kind", "Unknown"),
            name=res.get("name", "unknown"),
            namespace=res.get("namespace", ""),
            status=res.get("status", "Unknown"),
            health=health.get("status", "Unknown") if isinstance(health, dict) else "Unknown",
            message=health.get("message", "") if isinstance(health, dict) else "",
        )
        resources.append(status)
    return resources


def parse_argocd_app(app_json: str | dict[str, Any]) -> ArgoApp:
    """Parse an ArgoCD application status JSON into an ArgoApp.

    Accepts either a raw JSON string or a pre-parsed dict.
    Compatible with output from `argocd app get <name> -o json` or
    the ArgoCD API `/api/v1/applications/<name>`.
    """
    if isinstance(app_json, str):
        data = json.loads(app_json)
    else:
        data = app_json

    metadata = data.get("metadata", {})
    spec = data.get("spec", {})
    status = data.get("status", {})

    # Parse source information
    source = spec.get("source", {})
    if not source:
        sources = spec.get("sources", [])
        if sources:
            source = sources[0]

    # Parse resources
    resources_data = status.get("resources", [])
    resources = parse_resources(resources_data)

    # Parse operation state
    operation_state = status.get("operationState", {})

    # Parse conditions
    conditions = status.get("conditions", [])

    return ArgoApp(
        name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", ""),
        project=spec.get("project", "default"),
        sync=parse_sync_status(status.get("sync", {})),
        health=parse_health_status(status.get("health", {})),
        resources=resources,
        conditions=conditions,
        operation_state=operation_state,
        source=source,
        raw=data,
    )


def get_sync_failure_reasons(app: ArgoApp) -> list[str]:
    """Extract human-readable reasons for sync failures."""
    reasons = []

    # Check operation state for sync failures
    op = app.operation_state
    if op.get("phase") in ("Failed", "Error"):
        msg = op.get("message", "Unknown error")
        reasons.append(f"Operation {op.get('phase')}: {msg}")

        # Check sync result for individual resource errors
        sync_result = op.get("syncResult", {})
        for res in sync_result.get("resources", []):
            if res.get("status") in ("Failed", "Error"):
                kind = res.get("kind", "?")
                name = res.get("name", "?")
                msg = res.get("message", "no details")
                reasons.append(f"Resource {kind}/{name}: {msg}")

    # Check health issues
    if not app.is_healthy:
        if app.health.message:
            reasons.append(f"Health: {app.health.message}")
        for res in app.unhealthy_resources:
            msg = res.message or "unhealthy"
            reasons.append(f"{res.kind}/{res.name}: {msg}")

    # Check sync issues
    if not app.is_synced:
        reasons.append(f"App is OutOfSync (revision: {app.sync.revision or 'unknown'})")
        for res in app.unsynced_resources:
            reasons.append(f"Resource {res.kind}/{res.name} is {res.status}")

    # Check conditions
    for cond in app.failed_conditions:
        reasons.append(f"Condition: {cond.get('type', '?')} - {cond.get('message', 'failed')}")

    return reasons if reasons else ["No obvious failure detected."]
