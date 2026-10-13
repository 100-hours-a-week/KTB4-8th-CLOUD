"""Offline V2 configuration/manifest validation; does not require AWS credentials."""
import json
from v2_common import ROOT, Error, load_config, validate_manifest

config = load_config()
for path in (ROOT / "deployment/envs/v2-dev").glob("*.json"):
    if path.stem not in config["groups"]:
        raise Error("Unknown V2 manifest group: " + path.stem)
    validate_manifest(json.loads(path.read_text(encoding="utf-8")), config, path.stem)
print("V2 configuration and existing manifests are valid")
