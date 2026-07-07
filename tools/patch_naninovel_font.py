#!/usr/bin/env python3
import argparse
import copy
import hashlib
import json
import os
import pathlib
from typing import Any, Dict, Iterable, List, Set, Tuple


UI_BUNDLE_GLOB = "naninovel_assets_naninovelui_*.bundle"
UI_BUNDLE_REL = pathlib.Path("web/dok6uc0hyhl8f.cloudfront.net/WebGL")
DEFAULT_TARGET_FONT_OBJECTS = ("MPLUSRounded1c-Bold",)
DEFAULT_TMP_FONT_ASSET = "Roboto-Regular SDF"
DEFAULT_POINT_SIZE = 80
DEFAULT_ATLAS_SIZE = 4096
DEFAULT_ATLAS_PADDING = 6
DEFAULT_CHINESE_FONT = r"C:\Windows\Fonts\msyhbd.ttc"
DEFAULT_FONT_NAME = "Microsoft YaHei"
SDF_SPREAD = 8


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


def make_static_font(font_path: pathlib.Path, weight: int, repo_root: pathlib.Path, font_index: int) -> pathlib.Path:
    from fontTools.ttLib import TTFont, TTCollection
    from fontTools.varLib.instancer import instantiateVariableFont

    cache_root = pathlib.Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "lilitra-font-cache"
    if font_path.suffix.lower() == ".ttc":
        static_path = cache_root / f"{font_path.stem}-{font_index}-ttc.ttf"
        if static_path.exists() and static_path.stat().st_mtime >= font_path.stat().st_mtime:
            return static_path
        static_path.parent.mkdir(parents=True, exist_ok=True)
        collection = TTCollection(str(font_path))
        if font_index < 0 or font_index >= len(collection.fonts):
            raise ValueError(f"{font_path} contains {len(collection.fonts)} font(s); font index {font_index} is out of range")
        collection.fonts[font_index].save(str(static_path))
        return static_path

    font = TTFont(str(font_path))
    if "fvar" not in font:
        return font_path

    static_path = cache_root / f"{font_path.stem}-{weight}-static.ttf"
    if static_path.exists() and static_path.stat().st_mtime >= font_path.stat().st_mtime:
        return static_path
    static_path.parent.mkdir(parents=True, exist_ok=True)
    font = instantiateVariableFont(font, {"wght": weight}, inplace=False)
    font.save(str(static_path))
    return static_path


def walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("zh", "name", "character_name") and isinstance(child, str):
                yield child
            else:
                yield from walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_strings(child)


def walk_all_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from walk_all_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_all_strings(child)


def collect_translation_chars(repo_root: pathlib.Path) -> Set[str]:
    chars: Set[str] = set()
    roots = [
        repo_root / "translations/naninovel",
        repo_root / "reviews/naninovel",
        repo_root / "translations/api",
    ]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for text in walk_strings(data):
                chars.update(text)
    chars.update("？！。，、：；（）「」『』…—·♡♥♪　 \n")
    return chars


def make_subset_font(font_path: pathlib.Path, chars: Iterable[str], repo_root: pathlib.Path) -> pathlib.Path:
    from fontTools import subset

    char_text = "".join(sorted({ch for ch in chars if ch}))
    digest = hashlib.sha256((str(font_path) + "\n" + char_text).encode("utf-8")).hexdigest()[:16]
    cache_root = pathlib.Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "lilitra-font-cache"
    subset_path = cache_root / f"{font_path.stem}-{digest}-subset.ttf"
    if subset_path.exists() and subset_path.stat().st_mtime >= font_path.stat().st_mtime:
        return subset_path
    subset_path.parent.mkdir(parents=True, exist_ok=True)

    options = subset.Options()
    options.set(layout_features="*")
    options.set(name_IDs="*")
    options.set(name_legacy=True)
    options.set(name_languages="*")
    options.set(recommended_glyphs=True)
    options.set(notdef_glyph=True)
    options.set(notdef_outline=True)
    font = subset.load_font(str(font_path), options)
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=[ord(ch) for ch in char_text])
    subsetter.subset(font)
    subset.save_font(font, str(subset_path), options)
    return subset_path


def disable_font_change_configuration(tree: Dict[str, Any]) -> bool:
    configs = tree.get("fontChangeConfiguration")
    if not isinstance(configs, list):
        return False
    changed = False
    for config in configs:
        if not isinstance(config, dict):
            continue
        if config.get("AllowFontChange") != 0:
            config["AllowFontChange"] = 0
            changed = True
    return changed


def set_pptr_path_id(value: Any, path_id: int) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("m_PathID") == path_id:
        return False
    value["m_FileID"] = 0
    value["m_PathID"] = path_id
    return True


def replace_legacy_text_font(tree: Dict[str, Any], font_path_id: int) -> bool:
    changed = False
    font_data = tree.get("m_FontData")
    if isinstance(font_data, dict):
        changed = set_pptr_path_id(font_data.get("m_Font"), font_path_id) or changed
    changed = set_pptr_path_id(tree.get("m_Font"), font_path_id) or changed
    return changed


def get_glyph_id_map(font_path: pathlib.Path) -> Dict[int, int]:
    from fontTools.ttLib import TTFont

    font = TTFont(str(font_path))
    cmap: Dict[int, str] = {}
    for table in font["cmap"].tables:
        cmap.update(table.cmap)
    result: Dict[int, int] = {}
    for codepoint, glyph_name in cmap.items():
        result[codepoint] = font.getGlyphID(glyph_name)
    return result


def glyph_rect(x: int, y: int, width: int, height: int) -> Dict[str, int]:
    return {"m_X": x, "m_Y": y, "m_Width": width, "m_Height": height}


def glyph_metrics(width: float, height: float, bearing_x: float, bearing_y: float, advance: float) -> Dict[str, float]:
    return {
        "m_Width": float(width),
        "m_Height": float(height),
        "m_HorizontalBearingX": float(bearing_x),
        "m_HorizontalBearingY": float(bearing_y),
        "m_HorizontalAdvance": float(advance),
    }


def render_sdf_glyph(font: Any, char: str, padding: int) -> Tuple[Any, Dict[str, float]]:
    import numpy as np
    from PIL import Image, ImageDraw
    from scipy import ndimage

    bbox = font.getbbox(char)
    baseline_bbox = font.getbbox(char, anchor="ls")
    if not bbox or not baseline_bbox:
        advance = float(font.getlength(char))
        return Image.new("L", (0, 0), 0), glyph_metrics(0, 0, 0, 0, advance)

    left, top, right, bottom = bbox
    bl_left, bl_top, bl_right, bl_bottom = baseline_bbox
    width = max(0, int(round(right - left)))
    height = max(0, int(round(bottom - top)))
    advance = float(font.getlength(char))
    if width == 0 or height == 0:
        return Image.new("L", (0, 0), 0), glyph_metrics(0, 0, 0, 0, advance)

    image = Image.new("L", (width + padding * 2, height + padding * 2), 0)
    draw = ImageDraw.Draw(image)
    draw.text((padding - left, padding - top), char, font=font, fill=255)
    mask = np.asarray(image, dtype=np.uint8) > 32
    if mask.any():
        inside = ndimage.distance_transform_edt(mask)
        outside = ndimage.distance_transform_edt(~mask)
        signed = inside - outside
        sdf = np.clip(128 + signed * (128 / SDF_SPREAD), 0, 255).astype(np.uint8)
        image = Image.fromarray(sdf, "L")
    metrics = glyph_metrics(
        float(bl_right - bl_left),
        float(bl_bottom - bl_top),
        float(bl_left),
        float(-bl_top),
        advance,
    )
    return image, metrics


def build_static_tmp_tables(
    font_path: pathlib.Path,
    chars: Iterable[str],
    point_size: int,
    atlas_size: int,
    padding: int,
) -> Tuple[bytes, List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, int]], List[Dict[str, int]], Dict[str, float]]:
    import numpy as np
    from PIL import Image, ImageFont

    font = ImageFont.truetype(str(font_path), point_size)
    glyph_ids = get_glyph_id_map(font_path)

    atlas = Image.new("L", (atlas_size, atlas_size), 0)
    glyph_table: Dict[int, Dict[str, Any]] = {}
    character_table: List[Dict[str, Any]] = []
    used_rects: List[Dict[str, int]] = []

    x = 0
    y = 0
    row_height = 0

    sorted_chars = sorted({ch for ch in chars if ch and ch not in "\r\n"}, key=lambda c: (ord(c), c))
    for char in sorted_chars:
        codepoint = ord(char)
        glyph_id = glyph_ids.get(codepoint)
        if glyph_id is None:
            continue
        if glyph_id not in glyph_table:
            sdf, metrics = render_sdf_glyph(font, char, padding)
            rect_width, rect_height = sdf.size
            if rect_width > 0 and rect_height > 0:
                if x + rect_width > atlas_size:
                    x = 0
                    y += row_height + 1
                    row_height = 0
                if y + rect_height > atlas_size:
                    raise RuntimeError(f"TMP atlas is too small for generated glyphs; failed at U+{codepoint:04X}")
                top_y = atlas_size - y - rect_height
                atlas.paste(sdf, (x, top_y))
                rect = glyph_rect(x, y, rect_width, rect_height)
                used_rects.append(rect)
                x += rect_width + 1
                row_height = max(row_height, rect_height)
            else:
                rect = glyph_rect(0, 0, 0, 0)
            glyph_table[glyph_id] = {
                "m_Index": glyph_id,
                "m_Metrics": metrics,
                "m_GlyphRect": rect,
                "m_Scale": 1.0,
                "m_AtlasIndex": 0,
            }
        character_table.append({
            "m_ElementType": 1,
            "m_Unicode": codepoint,
            "m_GlyphIndex": glyph_id,
            "m_Scale": 1.0,
        })

    ascent, descent = font.getmetrics()
    face_info = {
        "m_PointSize": int(point_size),
        "m_LineHeight": float(ascent + descent),
        "m_AscentLine": float(ascent),
        "m_DescentLine": float(-descent),
    }
    free_rects = [glyph_rect(0, min(atlas_size, y + row_height + 1), atlas_size, max(0, atlas_size - (y + row_height + 1)))]
    atlas_bytes = np.asarray(atlas, dtype=np.uint8)[::-1, :].tobytes()
    return atlas_bytes, list(glyph_table.values()), character_table, used_rects, free_rects, face_info


def get_pptr_path_id(value: Any) -> int:
    if isinstance(value, dict):
        path_id = value.get("m_PathID")
        return int(path_id) if isinstance(path_id, int) else 0
    return 0


def get_texture_data(texture_tree: Dict[str, Any]) -> bytes:
    data = texture_tree.get("image data") or b""
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, str):
        return data.encode("latin1")
    return bytes(data)


def set_material_float(material_tree: Dict[str, Any], name: str, value: float) -> bool:
    saved = material_tree.get("m_SavedProperties")
    if not isinstance(saved, dict):
        return False
    floats = saved.get("m_Floats")
    if not isinstance(floats, list):
        return False
    changed = False
    for index, item in enumerate(floats):
        if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] == name:
            if item[1] != value:
                floats[index] = [item[0], value]
                changed = True
    return changed


def material_uses_texture(material_tree: Dict[str, Any], texture_ids: Set[int]) -> bool:
    saved = material_tree.get("m_SavedProperties")
    if not isinstance(saved, dict):
        return False
    tex_envs = saved.get("m_TexEnvs")
    if not isinstance(tex_envs, list):
        return False
    for item in tex_envs:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        env = item[1]
        if not isinstance(env, dict):
            continue
        texture = env.get("m_Texture")
        if get_pptr_path_id(texture) in texture_ids:
            return True
    return False


def build_augmented_tmp_tables(
    font_path: pathlib.Path,
    chars: Iterable[str],
    point_size: int,
    atlas_size: int,
    padding: int,
    base_font_tree: Dict[str, Any],
    base_texture_tree: Dict[str, Any],
) -> Tuple[bytes, List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, int]], List[Dict[str, int]]]:
    import numpy as np
    from PIL import Image, ImageFont

    base_width = int(base_texture_tree.get("m_Width") or 0)
    base_height = int(base_texture_tree.get("m_Height") or 0)
    base_data = get_texture_data(base_texture_tree)
    if base_width <= 0 or base_height <= 0 or len(base_data) < base_width * base_height:
        raise RuntimeError("Cannot read the original TMP atlas texture.")
    if atlas_size < base_width or atlas_size < base_height:
        raise RuntimeError("The target TMP atlas must be at least as large as the original atlas.")

    base_array = np.frombuffer(base_data[:base_width * base_height], dtype=np.uint8).reshape((base_height, base_width))
    atlas = Image.new("L", (atlas_size, atlas_size), 0)
    atlas.paste(Image.fromarray(base_array, "L"), (0, 0))

    font = ImageFont.truetype(str(font_path), point_size)
    glyph_table: List[Dict[str, Any]] = copy.deepcopy(base_font_tree.get("m_GlyphTable") or [])
    character_table: List[Dict[str, Any]] = copy.deepcopy(base_font_tree.get("m_CharacterTable") or [])
    used_rects: List[Dict[str, int]] = copy.deepcopy(base_font_tree.get("m_UsedGlyphRects") or [])

    existing_codepoints = {
        item.get("m_Unicode")
        for item in character_table
        if isinstance(item, dict) and isinstance(item.get("m_Unicode"), int)
    }
    used_glyph_indices = {
        item.get("m_Index")
        for item in glyph_table
        if isinstance(item, dict) and isinstance(item.get("m_Index"), int)
    }
    next_glyph_index = (max(used_glyph_indices) if used_glyph_indices else 0) + 1
    while next_glyph_index in used_glyph_indices:
        next_glyph_index += 1

    x = 0
    y = base_height + 1
    row_height = 0
    for char in sorted({ch for ch in chars if ch and ch not in "\r\n"}, key=lambda c: (ord(c), c)):
        codepoint = ord(char)
        if codepoint in existing_codepoints:
            continue
        sdf, metrics = render_sdf_glyph(font, char, padding)
        rect_width, rect_height = sdf.size
        if rect_width > 0 and rect_height > 0:
            if x + rect_width > atlas_size:
                x = 0
                y += row_height + 1
                row_height = 0
            if y + rect_height > atlas_size:
                raise RuntimeError(f"TMP atlas is too small for generated glyphs; failed at U+{codepoint:04X}")
            atlas.paste(sdf, (x, y))
            rect = glyph_rect(x, y, rect_width, rect_height)
            used_rects.append(rect)
            x += rect_width + 1
            row_height = max(row_height, rect_height)
        else:
            rect = glyph_rect(0, 0, 0, 0)

        glyph_table.append({
            "m_Index": next_glyph_index,
            "m_Metrics": metrics,
            "m_GlyphRect": rect,
            "m_Scale": 1.0,
            "m_AtlasIndex": 0,
        })
        character_table.append({
            "m_ElementType": 1,
            "m_Unicode": codepoint,
            "m_GlyphIndex": next_glyph_index,
            "m_Scale": 1.0,
        })
        existing_codepoints.add(codepoint)
        used_glyph_indices.add(next_glyph_index)
        next_glyph_index += 1

    glyph_table.sort(key=lambda item: item.get("m_Index", 0))
    character_table.sort(key=lambda item: item.get("m_Unicode", 0))
    free_y = min(atlas_size, y + row_height + 1)
    free_rects = [glyph_rect(0, free_y, atlas_size, max(0, atlas_size - free_y))]
    return np.asarray(atlas, dtype=np.uint8).tobytes(), glyph_table, character_table, used_rects, free_rects


def patch_font_bundle(
    source_bundle: pathlib.Path,
    output_bundle: pathlib.Path,
    font_path: pathlib.Path,
    font_name: str,
    target_names: List[str],
    repo_root: pathlib.Path,
    static_tmp: bool,
    tmp_font_asset: str,
    point_size: int,
    atlas_size: int,
    atlas_padding: int,
) -> int:
    import UnityPy

    env = UnityPy.load(str(source_bundle))
    font_bytes = font_path.read_bytes()
    targets = {name.strip() for name in target_names if name.strip()}
    changed = 0
    primary_font_path_id = 0
    for obj in env.objects:
        if obj.type.name != "Font":
            continue
        tree = obj.read_typetree()
        if targets and tree.get("m_Name") not in targets:
            continue
        if primary_font_path_id == 0:
            primary_font_path_id = obj.path_id
        tree["m_FontData"] = font_bytes
        tree["m_FontNames"] = [font_name]
        obj.save_typetree(tree)
        changed += 1
    if primary_font_path_id == 0:
        raise RuntimeError(f"No matching Unity Font objects were found in {source_bundle.name}")

    font_config_changed = 0
    text_font_changed = 0
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        if replace_legacy_text_font(tree, primary_font_path_id):
            text_font_changed += 1
            obj.save_typetree(tree)
            continue
        if disable_font_change_configuration(tree):
            obj.save_typetree(tree)
            font_config_changed += 1

    tmp_changed = 0
    tmp_atlas_ids: Set[int] = set()
    static_payload = None
    if static_tmp:
        static_chars = collect_translation_chars(repo_root)
        static_chars.update(chr(codepoint) for codepoint in range(0x20, 0x7F))
        static_chars.update(chr(codepoint) for codepoint in range(0x3040, 0x3100))
        base_tmp_tree = None
        base_atlas_tree = None
        base_atlas_id = 0
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            tree = obj.read_typetree()
            if tree.get("m_Name") != tmp_font_asset or "m_CharacterTable" not in tree:
                continue
            base_tmp_tree = copy.deepcopy(tree)
            for item in tree.get("m_CharacterTable") or []:
                codepoint = item.get("m_Unicode")
                if isinstance(codepoint, int) and codepoint > 0:
                    static_chars.add(chr(codepoint))
            atlas_refs = tree.get("m_AtlasTextures") or []
            if atlas_refs:
                base_atlas_id = get_pptr_path_id(atlas_refs[0])
            break
        if base_tmp_tree is None or not base_atlas_id:
            raise RuntimeError(f"Cannot find TMP font asset {tmp_font_asset}")
        for obj in env.objects:
            if obj.type.name != "Texture2D" or obj.path_id != base_atlas_id:
                continue
            base_atlas_tree = copy.deepcopy(obj.read_typetree())
            break
        if base_atlas_tree is None:
            raise RuntimeError(f"Cannot find TMP atlas texture for {tmp_font_asset}")
        tmp_atlas_ids.add(base_atlas_id)
        static_payload = build_augmented_tmp_tables(
            font_path,
            static_chars,
            point_size,
            atlas_size,
            atlas_padding,
            base_tmp_tree,
            base_atlas_tree,
        )

    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        if "m_SourceFontFile" not in tree or "m_CharacterTable" not in tree or "m_GlyphTable" not in tree:
            continue
        if static_tmp and tree.get("m_Name") == tmp_font_asset:
            atlas_bytes, glyph_table, character_table, used_rects, free_rects = static_payload
            tree["m_AtlasPopulationMode"] = 0
            tree["m_IsMultiAtlasTexturesEnabled"] = 0
            if "m_ClearDynamicDataOnBuild" in tree:
                tree["m_ClearDynamicDataOnBuild"] = 0
            tree["m_GlyphTable"] = glyph_table
            tree["m_CharacterTable"] = character_table
            tree["m_UsedGlyphRects"] = used_rects
            tree["m_FreeGlyphRects"] = free_rects
            tree["m_AtlasWidth"] = atlas_size
            tree["m_AtlasHeight"] = atlas_size
            creation = tree.get("m_CreationSettings")
            if isinstance(creation, dict):
                creation["padding"] = atlas_padding
                creation["atlasWidth"] = atlas_size
                creation["atlasHeight"] = atlas_size
            for texture_ref in tree.get("m_AtlasTextures") or []:
                if isinstance(texture_ref, dict):
                    tmp_atlas_ids.add(texture_ref.get("m_PathID"))
            obj.save_typetree(tree)
            tmp_changed += 1
            continue
        # Keep non-target TMP assets dynamic so secondary TMP text can still resolve
        # Simplified Chinese glyphs if the game switches printers at runtime.
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

    atlas_changed = 0
    if static_tmp and static_payload:
        atlas_bytes = static_payload[0]
        for obj in env.objects:
            if obj.type.name != "Texture2D" or obj.path_id not in tmp_atlas_ids:
                continue
            tree = obj.read_typetree()
            tree["m_Width"] = atlas_size
            tree["m_Height"] = atlas_size
            tree["m_CompleteImageSize"] = len(atlas_bytes)
            tree["m_MipCount"] = 1
            tree["m_TextureFormat"] = 1
            tree["image data"] = atlas_bytes
            stream_data = tree.get("m_StreamData")
            if isinstance(stream_data, dict):
                stream_data["offset"] = 0
                stream_data["size"] = 0
                stream_data["path"] = ""
            obj.save_typetree(tree)
            atlas_changed += 1

        for obj in env.objects:
            if obj.type.name != "Material":
                continue
            tree = obj.read_typetree()
            if not material_uses_texture(tree, tmp_atlas_ids):
                continue
            changed_material = False
            changed_material = set_material_float(tree, "_TextureWidth", float(atlas_size)) or changed_material
            changed_material = set_material_float(tree, "_TextureHeight", float(atlas_size)) or changed_material
            if changed_material:
                obj.save_typetree(tree)
                atlas_changed += 1

    if not changed and not tmp_changed and not atlas_changed and not font_config_changed and not text_font_changed:
        raise RuntimeError(f"No matching Unity Font objects were found in {source_bundle.name}")
    output_bundle.parent.mkdir(parents=True, exist_ok=True)
    output_bundle.write_bytes(env.file.save())
    return changed + tmp_changed + atlas_changed + font_config_changed + text_font_changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Naninovel UI font for Simplified Chinese display.")
    parser.add_argument("--runtime-root", required=True, type=pathlib.Path)
    parser.add_argument("--font", default=DEFAULT_CHINESE_FONT, type=pathlib.Path)
    parser.add_argument("--font-name", default=DEFAULT_FONT_NAME)
    parser.add_argument("--font-index", default=0, type=int, help="Font index when --font points to a TTC collection.")
    parser.add_argument("--weight", default=500, type=int)
    parser.add_argument("--static-tmp", action="store_true", help="Bake translated glyphs directly into the TextMeshPro atlas.")
    parser.add_argument("--tmp-font-asset", default=DEFAULT_TMP_FONT_ASSET)
    parser.add_argument("--point-size", default=DEFAULT_POINT_SIZE, type=int)
    parser.add_argument("--atlas-size", default=DEFAULT_ATLAS_SIZE, type=int)
    parser.add_argument("--atlas-padding", default=DEFAULT_ATLAS_PADDING, type=int)
    parser.add_argument(
        "--targets",
        default=",".join(DEFAULT_TARGET_FONT_OBJECTS),
        help="Comma-separated Unity Font object names to replace; use an empty value to replace all.",
    )
    parser.add_argument("--repo-root", default=pathlib.Path(__file__).resolve().parents[1], type=pathlib.Path)
    args = parser.parse_args()

    if not args.font.exists():
        raise FileNotFoundError(args.font)
    font_path = make_static_font(args.font, args.weight, args.repo_root, args.font_index)
    source_bundle = find_ui_bundle(args.runtime_root)
    output_bundle = args.repo_root / "bundles/WebGL" / source_bundle.name
    target_names = [name for name in args.targets.split(",")] if args.targets else []
    changed = patch_font_bundle(
        source_bundle,
        output_bundle,
        font_path,
        args.font_name,
        target_names,
        args.repo_root,
        args.static_tmp,
        args.tmp_font_asset,
        args.point_size,
        args.atlas_size,
        args.atlas_padding,
    )
    refresh_translated_index(args.repo_root)
    print(f"patched {changed} font/TMP object(s): {source_bundle.name}")
    print(f"output: {output_bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
