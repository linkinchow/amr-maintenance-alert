#!/usr/bin/env python3
"""Azure CLI helper: every operation explicitly selects a subscription."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

RG = "rg-amr-alerts"
SCENARIO = "amr-maintenance-alerts"
BASE = Path(__file__).resolve().parents[1]
# Placeholder subscription used by committed samples; replay maps it to the real hub.
SAMPLE_SUBSCRIPTION = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def load_config():
    """Read environment IDs from config.local.json (git-ignored) or $AMR_CONFIG."""
    path = Path(os.environ.get("AMR_CONFIG") or BASE / "config.local.json")
    if not path.is_file():
        raise RuntimeError(f"Missing {path}; copy config.example.json to config.local.json and fill in real IDs")
    config = json.loads(path.read_text(encoding="utf-8"))
    subscriptions = {sid.lower(): name for sid, name in config["subscriptions"].items()}
    hub = config["hubSubscriptionId"].lower()
    if hub not in subscriptions or SAMPLE_SUBSCRIPTION in subscriptions:
        raise RuntimeError("hubSubscriptionId must be listed in subscriptions; replace example placeholders")
    return {"tenant": config["tenantId"].lower(), "hub": hub, "subscriptions": subscriptions,
            "location": config.get("location", "australiaeast")}


class AzError(RuntimeError):
    pass


def az(subscription, *args):
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is required")
    command = [executable]
    # The CLI is Python: force UTF-8 so Chinese text in workflow definitions is not written in the Windows code page.
    env = dict(os.environ, MSYS_NO_PATHCONV="1", PYTHONIOENCODING="utf-8")
    if os.name == "nt" and Path(executable).suffix.lower() in (".cmd", ".bat"):
        # Bypass the MSI launcher: cmd.exe would interpret URL ampersands as commands.
        python = Path(executable).resolve().parents[1] / "python.exe"
        if not python.is_file():
            raise RuntimeError("Cannot find Azure CLI Python; use the MSI CLI or run on Linux")
        # -I ignores PYTHONIOENCODING, so request UTF-8 mode explicitly.
        command = [str(python), "-X", "utf8", "-IBm", "azure.cli"]
        env["AZ_INSTALLER"] = "MSI"
    result = subprocess.run(
        [*command, *args, "--subscription", subscription, "--only-show-errors", "--output", "json"],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=240,
    )
    if result.returncode:
        raise AzError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def rest(subscription, method, url, body=None):
    args = ["rest", "--method", method, "--url", url]
    if body is None:
        return az(subscription, *args)
    # File JSON avoids Windows shell quote conversion; never use for secret payloads.
    with tempfile.TemporaryDirectory(prefix="amr-request-") as temp:
        path = Path(temp) / "request.json"
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return az(subscription, *args, "--body", "@" + str(path))


def action_group_id(subscription, rg=RG, name="ag-amr-maintenance-feishu"):
    return f"/subscriptions/{subscription}/resourceGroups/{rg}/providers/Microsoft.Insights/actionGroups/{name}"


def rule_url(subscription, name, version="2020-10-01", rg=RG):
    return (f"https://management.azure.com/subscriptions/{subscription}/resourceGroups/{rg}"
            f"/providers/Microsoft.Insights/activityLogAlerts/{name}?api-version={version}")


def rule_body(scopes, action_group=None, enabled=False):
    return {
        "location": "global", "tags": {"scenario": SCENARIO, "managedBy": "azure-demo"},
        "properties": {
            "enabled": enabled, "scopes": scopes,
            "description": "AMR ResourceHealth InProgress/Resolved events; not advance maintenance notice.",
            "condition": {"allOf": [
                {"field": "category", "equals": "ResourceHealth"},
                {"field": "resourceType", "equals": "Microsoft.Cache/redisEnterprise"},
                {"anyOf": [
                    {"field": "operationName", "equals": "Microsoft.Resourcehealth/healthevent/InProgress/action"},
                    {"field": "operationName", "equals": "Microsoft.Resourcehealth/healthevent/Resolved/action"},
                ]},
            ]},
            "actions": {"actionGroups": [{"actionGroupId": action_group}] if action_group else []},
        },
    }
