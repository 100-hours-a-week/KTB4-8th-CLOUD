"""Offline V2 configuration/manifest validation; does not require AWS credentials."""
import json
from v2_common import ENVIRONMENTS, ROOT, Error, config_path, load_config, validate_manifest

checked = []
for environment in ENVIRONMENTS:
    directory = ROOT / "deployment/envs" / environment
    if not config_path(environment).exists():
        if directory.exists() and any(directory.glob("*.json")):
            raise Error(f"Manifests exist without deployment/{environment}.json")
        continue
    config = load_config(environment)
    for path in directory.glob("*.json"):
        if path.stem not in config["groups"]:
            raise Error(f"Unknown V2 manifest group: {environment}/{path.stem}")
        validate_manifest(json.loads(path.read_text(encoding="utf-8")), config, path.stem)
    checked.append(environment)
if not checked:
    raise Error("No V2 environment configuration found")
print("V2 configuration and existing manifests are valid: " + ", ".join(checked))
