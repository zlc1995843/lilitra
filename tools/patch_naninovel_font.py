#!/usr/bin/env python3
import argparse
import hashlib
import json
import pathlib
import tempfile
from typing import Any, Dict, List


UI_BUNDLE_GLOB = "naninovel_assets_naninovelui_*.bundle"
UI_BUNDLE_REL = pathlib.Path("web/dok6uc0hyhl8f.cloudfront.net/WebGL")
DEFAULT_TARGET_FONT_OBJECTS = ("MPLUSRounded1c-Bold", "Roboto-Regular")


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


def make_static_font(font_path: pathlib.Path, weight: int) -> pathlib.Path:
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    font = TTFont(str(font_path))
    if "fvar" not in font:
        return font_path

    static_path = pathlib.Path(tempfile.gettempdir()) / f"{font_path.stem}-{weight}-static.ttf"
    font = instantiateVariableFont(font, {"wght": weight}, inplace=False)
    font.save(str(static_path))
    return static_path


def patch_font_bundle(
    source_bundle: pathlib.Path,
    output_bundle: pathlib.Path,
    font_path: pathlib.Path,
    font_name: str,
    target_names: List[str],
) -> int:
    import UnityPy

    font_bytes = font_path.read_bytes()
    env = UnityPy.load(str(source_bundle))
    targets = {name.strip() for name in target_names if name.strip()}
    changed = 0
    for obj in env.objects:
        if obj.type.name != "Font":
            continue
        tree = obj.read_typetree()
        if targets and tree.get("m_Name") not in targets:
            continue
        tree["m_FontData"] = font_bytes
        tree["m_FontNames"] = [font_name]
        obj.save_typetree(tree)
        changed += 1

    tmp_changed = 0
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        if "m_SourceFontFile" not in tree or "m_CharacterTable" not in tree or "m_GlyphTable" not in tree:
            continue
        # Naninovel dialogue uses TextMeshPro, not UnityEngine.Font directly.
        # Keep the existing atlas, but allow TMP to allocate additional dynamic atlases
        # when Simplified Chinese glyphs are requested at runtime.
        if tree.get("m_AtlasPopulationMode") != 1:
            tree["m_AtlasPopulationMode"] = 1
        if tree.get("m_IsMultiAtlasTexturesEnabled") != 1:
            tree["m_IsMultiAtlasTexturesEnabled"] = 1
        creation = tree.get("m_CreationSettings")
        if isinstance(creation, dict):
            creation["characterSetSelectionMode"] = 7
            creation["characterSequence"] = ""
        obj.save_typetree(tree)
        tmp_changed += 1

    if not changed:
        raise RuntimeError(f"No matching Unity Font objects were found in {source_bundle.name}")
    output_bundle.parent.mkdir(parents=True, exist_ok=True)
    output_bundle.write_bytes(env.file.save())
    return changed + tmp_changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Naninovel UI font for Simplified Chinese display.")
    parser.add_argument("--runtime-root", required=True, type=pathlib.Path)
    parser.add_argument("--font", default=r"C:\Windows\Fonts\NotoSansSC-VF.ttf", type=pathlib.Path)
    parser.add_argument("--font-name", default="Noto Sans SC")
    parser.add_argument("--weight", default=500, type=int)
    parser.add_argument(
        "--targets",
        default=",".join(DEFAULT_TARGET_FONT_OBJECTS),
        help="Comma-separated Unity Font object names to replace; use an empty value to replace all.",
    )
    parser.add_argument("--repo-root", default=pathlib.Path(__file__).resolve().parents[1], type=pathlib.Path)
    args = parser.parse_args()

    if not args.font.exists():
        raise FileNotFoundError(args.font)
    font_path = make_static_font(args.font, args.weight)
    source_bundle = find_ui_bundle(args.runtime_root)
    output_bundle = args.repo_root / "bundles/WebGL" / source_bundle.name
    target_names = [name for name in args.targets.split(",")] if args.targets else []
    changed = patch_font_bundle(source_bundle, output_bundle, font_path, args.font_name, target_names)
    refresh_translated_index(args.repo_root)
    print(f"patched {changed} font/TMP object(s): {source_bundle.name}")
    print(f"output: {output_bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
