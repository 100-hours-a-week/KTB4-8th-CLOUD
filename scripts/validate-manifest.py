#!/usr/bin/env python3
import argparse
from pathlib import Path
from release import load, validate_manifest, render_compose, ROOT

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--structure-only", action="store_true")
    parser.add_argument("--manifest", type=Path, default=ROOT / "deployment/production-manifest.json")
    args = parser.parse_args()
    manifest = load(args.manifest)
    validate_manifest(manifest, structure_only=args.structure_only)
    render_compose(ROOT, manifest, "000000000000")
    print("Structure valid (placeholders permitted)" if args.structure_only else "Release configuration valid")
