"""Check translation files against the Unity manifest and runtime index."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


KANA = re.compile(r"[\u3040-\u30ff]")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Lilyange translation runtime coverage")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", type=Path, help="Write a machine-readable report")
    args = parser.parse_args()
    root = args.root.resolve()

    manifest = read_json(root / "manifest.json")
    index = read_json(root / "translated_files.json")
    listed = set(index.get("files", []))
    hashes = index.get("sha256", {})

    resources = []
    missing_index = []
    missing_local = []
    hash_mismatch = []
    for item in manifest:
        url = item.get("url", "")
        if "/WebGL/" not in url or not url.endswith(".bundle"):
            continue
        relative = "bundles/WebGL/" + url.split("/WebGL/", 1)[1]
        resources.append(relative)
        path = root / relative
        if relative not in listed:
            missing_index.append({"script": item.get("script", ""), "path": relative})
        if not path.exists():
            missing_local.append(relative)
        elif hashes.get(relative) and sha256(path) != hashes[relative]:
            hash_mismatch.append(relative)

    translation_files = set()
    incomplete_json = []
    kana_in_zh = []
    for path in sorted((root / "translations/naninovel/scripts").glob("chara*.json")):
        translation_files.add(path.stem)
        try:
            data = read_json(path)
        except Exception as exc:
            incomplete_json.append({"file": str(path.relative_to(root)), "error": str(exc)})
            continue
        for number, line in enumerate(data.get("lines", [])):
            zh = line.get("zh", "") if isinstance(line, dict) else ""
            if not zh:
                incomplete_json.append({"file": str(path.relative_to(root)), "line": number, "reason": "empty zh"})
            elif KANA.search(zh):
                kana_in_zh.append({"file": str(path.relative_to(root)), "line": number, "text": zh})

    report = {
        "manifest_bundle_count": len(resources),
        "index_bundle_count": sum(p.startswith("bundles/WebGL/") and p.endswith(".bundle") for p in listed),
        "missing_from_index": missing_index,
        "missing_local_files": missing_local,
        "hash_mismatches": hash_mismatch,
        "translation_json_count": len(translation_files),
        "incomplete_translation_lines": incomplete_json,
        "chinese_lines_containing_kana": kana_in_zh,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if missing_index or missing_local or hash_mismatch or incomplete_json else 0


if __name__ == "__main__":
    raise SystemExit(main())
