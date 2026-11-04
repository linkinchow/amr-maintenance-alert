#!/usr/bin/env python3
"""Write git-ignored main.parameters.local.json (location, monitored subscriptions) from config.local.json."""
import json
from azure_helpers import BASE, load_config


def parameters(config):
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {"location": {"value": config["location"]},
                       "subscriptions": {"value": [{"id": sid, "name": name} for sid, name in config["subscriptions"].items()]}},
    }


def main():
    path = BASE / "main.parameters.local.json"
    path.write_text(json.dumps(parameters(load_config()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path.name}; it contains environment IDs and must not be committed")


if __name__ == "__main__":
    main()
