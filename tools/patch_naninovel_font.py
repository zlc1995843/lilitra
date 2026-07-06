#!/usr/bin/env python3
import argparse
import hashlib
import json
import pathlib
from typing import Any, Dict, List


UI_BUNDLE_GLOB = "naninovel_assets_naninovelui_*.bundle"
UI_BUNDLE_REL = pathlib.Path("web/dok6uc0hyhl8f.cloudfront.net/WebGL")
TARGET_FONT_OBJECT = "MPLUSRounded1c-Bold"


def write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def refresh_translated_index(repo_root: pathlib.Path) -> None:
    files: List[str] = []
    hashes: Dict[str, str] = {}
    roots = [
        repo_root / "translations/api",
        repo_root / "bundles/WebGL",
    ]
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative_path = path.relative_to(repo_root).as_posix()
            files.append(relative_path)
            hashes[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(repo_root / "translated_files.json", {"files": files, "sha256": hashes})


def find_ui_bundle(runtime_root: pathlib.Path) -> pathlib.Path:
    matches = sorted((runtime_root / UI_BUNDLE_REL).glob(UI_BUNDLE_GLOB))
    if not matches:
        raise FileNotFoundError(f"Cannot find {UI_BUNDLE_GLOB} under {runtime_root / UI_BUNDLE_REL}")
    return matches[0]


def patch_font_bundle(source_bundle: pathlib.Path, output_bundle: pathlib.Path, font_path: pathlib.Path, font_name: str) -> int:
    import UnityPy

    font_bytes = font_path.read_bytes()
    env = UnityPy.load(str(source_bundle))
    changed = 0
    for obj in env.objects:
        if obj.type.name != "Font":
            continue
        tree = obj.read_typetree()
        if tree.get("m_Name") != TARGET_FONT_OBJECT:
            continue
        tree["m_FontData"] = font_bytes
        tree["m_FontNames"] = [font_name]
        obj.save_typetree(tree)
        changed += 1
    if not changed:
        raise RuntimeError(f"Font object {TARGET_FONT_OBJECT!r} was not found in {source_bundle.name}")
    output_bundle.parent.mkdir(parents=True, exist_ok=True)
    output_bundle.write_bytes(env.file.save())
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Naninovel UI font for Simplified Chinese display.")
    parser.add_argument("--runtime-root", required=True, type=pathlib.Path)
    parser.add_argument("--font", default=r"C:\Windows\Fonts\NotoSansSC-VF.ttf", type=pathlib.Path)
    parser.add_argument("--font-name", default="Noto Sans SC")
    parser.add_argument("--repo-root", default=pathlib.Path(__file__).resolve().parents[1], type=pathlib.Path)
    args = parser.parse_args()

    if not args.font.exists():
        raise FileNotFoundError(args.font)
    source_bundle = find_ui_bundle(args.runtime_root)
    output_bundle = args.repo_root / "bundles/WebGL" / source_bundle.name
    changed = patch_font_bundle(source_bundle, output_bundle, args.font, args.font_name)
    refresh_translated_index(args.repo_root)
    print(f"patched {changed} font object(s): {source_bundle.name}")
    print(f"output: {output_bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
