#!/usr/bin/env python3
import argparse
import copy
import json
import os
import pathlib
import re
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
import UnityPy


CLOUDFRONT_SCRIPT_BASE = (
    "https://dok6uc0hyhl8f.cloudfront.net/"
    "WebGL/naninovelseparate_assets_naninovel/scripts/"
)
CATALOG_REL = pathlib.Path(
    "web/dok6uc0hyhl8f.cloudfront.net/WebGL/catalog_0.0.1.json"
)
STORY_INDEX_REL = pathlib.Path("web/api/lilyange.saikyo.biz/character_story_index")
SCRIPT_LOCAL_REL = pathlib.Path(
    "web/dok6uc0hyhl8f.cloudfront.net/WebGL/"
    "naninovelseparate_assets_naninovel/scripts"
)
ADV_NAME_ZH = {
    101: "\u7ea6\u4f1a\u5267\u60c5\u2460",
    201: "H\u5267\u60c5\u2460",
    202: "H\u5267\u60c5\u2461",
    204: "\u8ffd\u52a0\u5267\u60c5\u2460",
}
ADV_NAME_JA = {
    101: "\u30c7\u30fc\u30c8\u30b9\u30c8\u30fc\u30ea\u30fc\u2460",
    201: "H\u30b9\u30c8\u30fc\u30ea\u30fc\u2460",
    202: "H\u30b9\u30c8\u30fc\u30ea\u30fc\u2461",
    204: "\u8ffd\u52a0\u30b9\u30c8\u30fc\u30ea\u30fc\u2460",
}
JP_STORY_NAME_TO_ZH = {
    "\u30c7\u30fc\u30c8\u30b9\u30c8\u30fc\u30ea\u30fc\u2460": "\u7ea6\u4f1a\u5267\u60c5\u2460",
    "H\u30b9\u30c8\u30fc\u30ea\u30fc\u2460": "H\u5267\u60c5\u2460",
    "H\u30b9\u30c8\u30fc\u30ea\u30fc\u2461": "H\u5267\u60c5\u2461",
    "\u8ffd\u52a0\u30b9\u30c8\u30fc\u30ea\u30fc\u2460": "\u8ffd\u52a0\u5267\u60c5\u2460",
}


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def bundle_base(filename: str) -> str:
    stem = filename[:-7] if filename.endswith(".bundle") else filename
    parts = stem.split("_")
    if parts and re.fullmatch(r"[0-9a-f]{32}", parts[-1]):
        return "_".join(parts[:-1])
    return stem


def load_catalog(runtime_root: pathlib.Path) -> Dict[str, str]:
    catalog_path = runtime_root / CATALOG_REL
    catalog = read_json(catalog_path)
    text = json.dumps(catalog, ensure_ascii=False)
    filenames = re.findall(
        r"WebGL/naninovelseparate_assets_naninovel/scripts/([^\"\\\\/]+?\.bundle)",
        text,
    )
    result: Dict[str, str] = {}
    for filename in filenames:
        result[bundle_base(filename)] = filename
    return result


def load_story_index(runtime_root: pathlib.Path) -> Tuple[Dict[str, Any], Dict[int, str], List[Dict[str, Any]]]:
    path = runtime_root / STORY_INDEX_REL
    data = read_json(path)
    characters = data.get("character_list") or data.get("data", {}).get("character_list") or []
    names: Dict[int, str] = {}
    stories: List[Dict[str, Any]] = []
    for character in characters:
        try:
            char_id = int(character.get("id"))
        except (TypeError, ValueError):
            continue
        name = character.get("chara_name") or character.get("name") or ""
        if name:
            names[char_id] = name
        for story in character.get("story") or []:
            try:
                adv_id = int(story.get("adv_id"))
            except (TypeError, ValueError):
                continue
            stories.append(
                {
                    "character_id": char_id,
                    "character_name": name,
                    "adv_id": adv_id,
                    "story_name": story.get("story_name") or ADV_NAME_JA.get(adv_id, ""),
                    "source": "api",
                }
            )
    return data, names, stories


def build_story_manifest(
    stories: List[Dict[str, Any]], names: Dict[int, str], bundles: Dict[str, str]
) -> List[Dict[str, Any]]:
    manifest: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for story in stories:
        char_id = int(story["character_id"])
        adv_id = int(story["adv_id"])
        base = f"chara{char_id}_{adv_id}"
        filename = bundles.get(base)
        if not filename:
            continue
        manifest[(char_id, adv_id)] = {
            "script": base,
            "bundle": filename,
            "url": CLOUDFRONT_SCRIPT_BASE + filename,
            "character_id": char_id,
            "character_name": story.get("character_name") or names.get(char_id, ""),
            "adv_id": adv_id,
            "story_name": story.get("story_name") or ADV_NAME_JA.get(adv_id, ""),
            "source": story.get("source") or "api",
        }

    for base, filename in bundles.items():
        match = re.fullmatch(r"chara(\d+)_(\d+)", base)
        if not match:
            continue
        char_id = int(match.group(1))
        adv_id = int(match.group(2))
        key = (char_id, adv_id)
        if key in manifest:
            continue
        manifest[key] = {
            "script": base,
            "bundle": filename,
            "url": CLOUDFRONT_SCRIPT_BASE + filename,
            "character_id": char_id,
            "character_name": names.get(char_id, ""),
            "adv_id": adv_id,
            "story_name": ADV_NAME_JA.get(adv_id, ""),
            "source": "catalog",
        }
    return [manifest[key] for key in sorted(manifest)]


def write_name_table(repo_root: pathlib.Path, names: Dict[int, str], manifest: List[Dict[str, Any]]) -> None:
    for item in manifest:
        char_id = int(item["character_id"])
        if char_id not in names and item.get("character_name"):
            names[char_id] = item["character_name"]
    rows = [
        {
            "id": char_id,
            "ja": names.get(char_id, ""),
            "zh": "",
            "note": "",
        }
        for char_id in sorted(names)
    ]
    write_json(repo_root / "names/characters.json", rows)


def generate_api_translation(repo_root: pathlib.Path, story_index: Dict[str, Any]) -> None:
    data = copy.deepcopy(story_index)
    characters = data.get("character_list") or data.get("data", {}).get("character_list") or []
    for character in characters:
        for story in character.get("story") or []:
            name = story.get("story_name")
            if name in JP_STORY_NAME_TO_ZH:
                story["story_name"] = JP_STORY_NAME_TO_ZH[name]
    write_json(
        repo_root / "translations/api/lilyange.saikyo.biz/character_story_index.json",
        data,
    )


def remote_content_length(url: str) -> Optional[int]:
    try:
        response = requests.head(url, timeout=20, allow_redirects=True)
        if response.status_code == 200 and response.headers.get("Content-Length"):
            return int(response.headers["Content-Length"])
    except Exception:
        return None
    return None


def download_file(url: str, destination: pathlib.Path, retries: int = 3) -> pathlib.Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected_size = remote_content_length(url)
    for attempt in range(1, retries + 1):
        tmp = destination.with_suffix(destination.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()
        try:
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or expected_size or 0)
                with tmp.open("wb") as fh:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            fh.write(chunk)
            size = tmp.stat().st_size
            if size <= 0:
                tmp.unlink(missing_ok=True)
                raise RuntimeError("downloaded file is empty")
            if total and size != total:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"downloaded {size} bytes, expected {total}")
            tmp.replace(destination)
            return destination
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            if attempt >= retries:
                raise
            print(f"download failed ({attempt}/{retries}): {url}: {exc}")
            time.sleep(2 * attempt)
    return destination


def ensure_bundle(runtime_root: pathlib.Path, repo_root: pathlib.Path, filename: str) -> pathlib.Path:
    local = runtime_root / SCRIPT_LOCAL_REL / filename
    url = CLOUDFRONT_SCRIPT_BASE + filename
    expected = remote_content_length(url)
    if local.exists() and local.stat().st_size > 0:
        if expected is None or local.stat().st_size == expected:
            return local
    cache = repo_root / ".cache/original_bundles" / filename
    if cache.exists() and cache.stat().st_size > 0:
        if expected is None or cache.stat().st_size == expected:
            return cache
    return download_file(url, cache)


def command_text(data: Dict[str, Any]) -> Optional[str]:
    text_node = data.get("Text")
    if isinstance(text_node, dict) and text_node.get("hasValue") and isinstance(text_node.get("value"), str):
        return text_node.get("value")
    return None


def command_speaker(data: Dict[str, Any]) -> str:
    speaker_node = data.get("Speaker")
    if isinstance(speaker_node, dict) and isinstance(speaker_node.get("value"), str):
        return speaker_node.get("value") or ""
    return ""


def command_spot(data: Dict[str, Any]) -> Dict[str, Any]:
    spot = data.get("playbackSpot")
    return spot if isinstance(spot, dict) else {}


def extract_lines(bundle_path: pathlib.Path) -> List[Dict[str, Any]]:
    env = UnityPy.load(str(bundle_path))
    lines: List[Dict[str, Any]] = []
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        refs = tree.get("references", {}).get("RefIds", [])
        hash_by_index: Dict[int, str] = {}
        for ref in refs:
            data = ref.get("data")
            if not isinstance(data, dict):
                continue
            if "lineIndex" in data and "lineHash" in data:
                try:
                    hash_by_index[int(data["lineIndex"])] = data.get("lineHash") or ""
                except (TypeError, ValueError):
                    pass
        for ref in refs:
            data = ref.get("data")
            if not isinstance(data, dict):
                continue
            text = command_text(data)
            if not text:
                continue
            spot = command_spot(data)
            try:
                line_index = int(spot.get("lineIndex"))
                inline_index = int(spot.get("inlineIndex") or 0)
            except (TypeError, ValueError):
                continue
            lines.append(
                {
                    "key": f"{line_index}.{inline_index}",
                    "line_index": line_index,
                    "inline_index": inline_index,
                    "line_hash": hash_by_index.get(line_index, ""),
                    "speaker": command_speaker(data),
                    "ja": text,
                    "zh": "",
                }
            )
    lines.sort(key=lambda item: (item["line_index"], item["inline_index"]))
    return lines


def patch_bundle(source_bundle: pathlib.Path, output_bundle: pathlib.Path, translations: Dict[str, str]) -> int:
    env = UnityPy.load(str(source_bundle))
    changed = 0
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        refs = tree.get("references", {}).get("RefIds", [])
        object_changed = False
        for ref in refs:
            data = ref.get("data")
            if not isinstance(data, dict):
                continue
            text = command_text(data)
            if not text:
                continue
            spot = command_spot(data)
            try:
                line_index = int(spot.get("lineIndex"))
                inline_index = int(spot.get("inlineIndex") or 0)
            except (TypeError, ValueError):
                continue
            key = f"{line_index}.{inline_index}"
            translated = translations.get(key)
            if translated and has_cjk(translated):
                data["Text"]["value"] = translated
                changed += 1
                object_changed = True
        if object_changed:
            obj.save_typetree(tree)
    if changed:
        output_bundle.parent.mkdir(parents=True, exist_ok=True)
        output_bundle.write_bytes(env.file.save())
    return changed


def to_codepoints(text: str) -> str:
    return " ".join(f"{ord(ch):04X}" for ch in text)


def from_existing_translation(path: pathlib.Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = read_json(path)
    except Exception:
        return {}
    result: Dict[str, str] = {}
    for item in data.get("lines", []):
        key = str(item.get("key") or "")
        zh = item.get("zh")
        if key and isinstance(zh, str) and has_cjk(zh):
            result[key] = zh
    return result


def save_translation(path: pathlib.Path, source_lines: List[Dict[str, Any]], zh_map: Dict[str, str]) -> None:
    rows = []
    for line in source_lines:
        item = dict(line)
        if zh_map.get(line["key"]):
            item["zh"] = zh_map[line["key"]]
        rows.append(item)
    write_json(path, {"lines": rows})


def call_deepseek(
    api_key: str,
    model: str,
    chunk: List[Dict[str, Any]],
    retries: int = 3,
) -> Dict[str, str]:
    url = "https://api.deepseek.com/chat/completions"
    input_rows = [
        {
            "key": item["key"],
            "speaker_hex": to_codepoints(item.get("speaker") or ""),
            "text_hex": to_codepoints(item["ja"]),
        }
        for item in chunk
    ]
    system_prompt = (
        "You translate Japanese visual novel dialogue into Simplified Chinese. "
        "Keep Japanese tone, honorific nuance, softness, hesitation, and line breaks where natural. "
        "Do not add explanations. Preserve placeholders, commands, numbers, symbols, and names unless a provided name has an obvious Chinese form. "
        "Input text is Unicode code points in hex separated by spaces. Decode it first. "
        "Return JSON only."
    )
    user_prompt = (
        "Translate each item. Return exactly this schema: "
        "{\"lines\":[{\"key\":\"same key\",\"zh\":\"Chinese translation\"}]}.\n"
        + json.dumps({"lines": input_rows}, ensure_ascii=True)
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.25,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=180)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            result = {}
            for item in parsed.get("lines", []):
                key = str(item.get("key") or "")
                zh = item.get("zh")
                if key and isinstance(zh, str) and zh.strip():
                    result[key] = zh.strip()
            if result:
                return result
            raise RuntimeError("empty translation result")
        except Exception as exc:
            if attempt >= retries:
                raise
            print(f"DeepSeek retry {attempt}/{retries}: {exc}")
            time.sleep(3 * attempt)
    return {}


def translate_lines(
    source_lines: List[Dict[str, Any]],
    existing: Dict[str, str],
    api_key: str,
    model: str,
    chunk_size: int,
) -> Dict[str, str]:
    result = dict(existing)
    pending = [line for line in source_lines if not result.get(line["key"])]
    for start in range(0, len(pending), chunk_size):
        chunk = pending[start : start + chunk_size]
        if not chunk:
            continue
        translated = call_deepseek(api_key, model, chunk)
        result.update(translated)
        print(f"translated {min(start + len(chunk), len(pending))}/{len(pending)} lines")
    return result


def parse_int_set(value: Optional[str]) -> Optional[set]:
    if not value:
        return None
    result = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            result.add(int(part))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--ids", help="comma separated character ids")
    parser.add_argument("--adv", help="comma separated adv ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--chunk-size", type=int, default=50)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--no-translate", action="store_true")
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    runtime_root = pathlib.Path(args.runtime_root)
    char_filter = parse_int_set(args.ids)
    adv_filter = parse_int_set(args.adv)

    story_index, names, stories = load_story_index(runtime_root)
    bundles = load_catalog(runtime_root)
    full_manifest = build_story_manifest(stories, names, bundles)

    write_name_table(repo_root, names, full_manifest)
    write_json(repo_root / "manifest.json", full_manifest)
    generate_api_translation(repo_root, story_index)

    if args.metadata_only:
        return 0

    manifest = list(full_manifest)
    if char_filter is not None:
        manifest = [item for item in manifest if int(item["character_id"]) in char_filter]
    if adv_filter is not None:
        manifest = [item for item in manifest if int(item["adv_id"]) in adv_filter]
    if args.limit is not None:
        manifest = manifest[: args.limit]

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not args.no_translate and not api_key:
        print("DEEPSEEK_API_KEY is not set; generated metadata only.", file=sys.stderr)
        return 2

    for index, item in enumerate(manifest, 1):
        script = item["script"]
        filename = item["bundle"]
        print(f"[{index}/{len(manifest)}] {script} {item.get('character_name', '')} {item.get('story_name', '')}")
        bundle_out = repo_root / "bundles/WebGL/naninovelseparate_assets_naninovel/scripts" / filename
        translation_path = repo_root / "translations/naninovel/scripts" / f"{script}.json"
        if args.skip_existing and bundle_out.exists() and from_existing_translation(translation_path):
            print("skip existing")
            continue
        source_bundle = ensure_bundle(runtime_root, repo_root, filename)
        source_lines = extract_lines(source_bundle)
        write_json(repo_root / "sources/naninovel/scripts" / f"{script}.json", {"lines": source_lines})
        existing = from_existing_translation(translation_path)
        if args.no_translate:
            save_translation(translation_path, source_lines, existing)
            continue
        zh_map = translate_lines(source_lines, existing, api_key, args.model, args.chunk_size)
        save_translation(translation_path, source_lines, zh_map)
        changed = patch_bundle(source_bundle, bundle_out, zh_map)
        print(f"patched {changed}/{len(source_lines)} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
