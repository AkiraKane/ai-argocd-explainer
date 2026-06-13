#!/usr/bin/env python3
"""CLI entry point for ai-argocd-explainer."""

from __future__ import annotations

import argparse
import json
import sys

from argocd_parser import ArgoApp, get_sync_failure_reasons, parse_argocd_app
from llm import LLMClient


SYSTEM_PROMPT = (
    "You are a Kubernetes and ArgoCD expert. Given an ArgoCD application status "
    "in JSON and extracted failure reasons, explain what went wrong in plain "
    "English that a developer can understand. Suggest specific steps to fix "
    "the issues. Be concise and actionable."
)


def format_status_text(app: ArgoApp) -> str:
    """Format an ArgoApp as human-readable status text."""
    lines = [
        "=" * 60,
        "  ARGOCD APPLICATION STATUS",
        "=" * 60,
        f"  App:       {app.name}",
        f"  Namespace: {app.namespace or 'N/A'}",
        f"  Project:   {app.project}",
        f"  Sync:      {app.sync.status}",
        f"  Health:    {app.health.status}",
        f"  Revision:  {app.sync.revision or 'N/A'}",
        "=" * 60,
        "",
    ]

    if app.source:
        repo = app.source.get("repoURL", "N/A")
        path = app.source.get("path", app.source.get("chart", "N/A"))
        lines.append(f"  Source: {repo}")
        lines.append(f"  Path:   {path}")
        lines.append("")

    # Resources
    lines.append(f"  RESOURCES ({len(app.resources)}):")
    lines.append("-" * 60)
    for r in app.resources:
        health_icon = "OK" if r.is_healthy else "FAIL"
        sync_icon = "OK" if r.is_synced else "DIFF"
        lines.append(
            f"  [{health_icon}][{sync_icon}] {r.kind}/{r.name}"
        )
        if r.message:
            lines.append(f"           {r.message}")

    # Failure reasons
    if not app.is_healthy or not app.is_synced:
        lines.append("")
        lines.append("  ISSUES DETECTED:")
        lines.append("-" * 60)
        reasons = get_sync_failure_reasons(app)
        for i, reason in enumerate(reasons, 1):
            lines.append(f"  {i}. {reason}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Explain ArgoCD sync failures in plain English using AI."
    )
    parser.add_argument(
        "status_file",
        help="Path to ArgoCD app status JSON file "
        "(use 'argocd app get <name> -o json > app.json')",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Use LLM to generate a plain-English explanation",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output status as JSON instead of text",
    )
    parser.add_argument(
        "--reasons-only",
        action="store_true",
        help="Only output failure reasons, no full status",
    )

    args = parser.parse_args(argv)

    # Read the status file
    try:
        with open(args.status_file, "r") as f:
            status_json = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {args.status_file}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error reading file: {exc}", file=sys.stderr)
        return 1

    # Parse the ArgoCD app status
    try:
        app = parse_argocd_app(status_json)
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"Error parsing ArgoCD status: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps(app.summary, indent=2))
    elif args.reasons_only:
        reasons = get_sync_failure_reasons(app)
        for i, reason in enumerate(reasons, 1):
            print(f"{i}. {reason}")
    else:
        print(format_status_text(app))

    # LLM explanation
    if args.explain:
        llm = LLMClient()
        summary = json.dumps(app.summary, indent=2)
        reasons = get_sync_failure_reasons(app)
        reasons_text = "\n".join(f"- {r}" for r in reasons)

        prompt = (
            f"ArgoCD Application: {app.name}\n\n"
            f"Status Summary:\n{summary}\n\n"
            f"Detected Issues:\n{reasons_text}\n\n"
            "Please explain what went wrong and how to fix it."
        )

        print("\n" + "=" * 60)
        print("  AI EXPLANATION")
        print("=" * 60)
        try:
            explanation = llm.chat(prompt, system=SYSTEM_PROMPT)
            print(explanation)
        except Exception as exc:
            print(f"  LLM unavailable: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
