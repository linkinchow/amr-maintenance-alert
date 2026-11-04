#!/usr/bin/env python3
"""Probe single- and multi-subscription scopes with disabled, actionless rules."""
import argparse
import json
from datetime import datetime, timezone
from azure_helpers import RG, BASE, AzError, az, load_config, rest, rule_url, rule_body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.parse_args()
    config = load_config()
    hub = config["hub"]
    spoke = next(s for s in config["subscriptions"] if s != hub)
    existing = az(hub, "monitor", "activity-log", "alert", "list", "--resource-group", RG)
    names = {r["name"].lower() for r in existing}
    results = []
    for version in ("2020-10-01", "2026-01-01"):
        for mode in ("single", "multiple"):
            name = f"probe-amr-{mode}-{version}"
            if name.lower() in names:
                raise RuntimeError(f"Probe name already exists: {name}; not overwriting")
            scopes = [f"/subscriptions/{hub}"]
            if mode == "multiple":
                scopes.append(f"/subscriptions/{spoke}")
            body = rule_body(scopes)
            record = {"utc": datetime.now(timezone.utc).isoformat(), "apiVersion": version,
                      "mode": mode, "name": name, "request": body}
            try:
                created = rest(hub, "put", rule_url(hub, name, version), body)
            except AzError as exc:
                record.update(accepted=False, error=str(exc))
            else:
                read = rest(hub, "get", rule_url(hub, name, version))
                assert read["properties"]["enabled"] is False
                assert read["properties"]["actions"]["actionGroups"] == []
                assert read.get("tags", {}).get("scenario") == "amr-maintenance-alerts"
                record.update(accepted=True, response=created)
                rest(hub, "delete", rule_url(hub, name, version))
                record["temporaryRuleDeleted"] = True
            results.append(record)
            print(json.dumps({k:v for k,v in record.items() if k not in ("request","response")}, indent=2))
    path = BASE / "docs" / "scope-probe-results.json"
    path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    for version in ("2020-10-01", "2026-01-01"):
        single = next(r for r in results if r["apiVersion"] == version and r["mode"] == "single")
        multi = next(r for r in results if r["apiVersion"] == version and r["mode"] == "multiple")
        if not single["accepted"] or (not multi["accepted"] and "ScopeIsInvalid" not in multi["error"]):
            raise RuntimeError("Inconclusive scope test; examine provider response before proceeding")


if __name__ == "__main__":
    main()
