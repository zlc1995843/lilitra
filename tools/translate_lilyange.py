#!/usr/bin/env python3
import argparse
import hashlib
import copy
import json
import os
import pathlib
import re
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple


CLOUDFRONT_SCRIPT_BASE = (
    "https://dok6uc0hyhl8f.cloudfront.net/"
    "WebGL/naninovelseparate_assets_naninovel/scripts/"
)
CATALOG_REL = pathlib.Path(
    "web/dok6uc0hyhl8f.cloudfront.net/WebGL/catalog_0.0.1.json"
)
STORY_INDEX_REL = pathlib.Path("web/api/lilyange.saikyo.biz/character_story_index")
CHARACTER_INDEX_REL = pathlib.Path("web/api/lilyange.saikyo.biz/character_index")
CHARACTER_BOOK_INDEX_REL = pathlib.Path("web/api/lilyange.saikyo.biz/character_book_index")
MISSION_INDEX_DIR_REL = pathlib.Path("web/api/char/lilyange.saikyo.biz")
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


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def http_requests() -> Any:
    import requests

    return requests


def markdown_cell(text: Any) -> str:
    value = "" if text is None else str(text)
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def merge_name(names: Dict[int, str], char_id: Any, name: Any) -> None:
    try:
        key = int(char_id)
    except (TypeError, ValueError):
        return
    if isinstance(name, str) and name and not names.get(key):
        names[key] = name


def clean_character_name(name: str) -> str:
    return name.strip()


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def to_game_display_text(text: str) -> str:
    return text or ""


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


def load_character_names(runtime_root: pathlib.Path) -> Dict[int, str]:
    names: Dict[int, str] = {}
    sources = [
        (CHARACTER_BOOK_INDEX_REL, ["characters_book"]),
        (CHARACTER_INDEX_REL, ["character_index_canvas", "user_character_list"]),
        (STORY_INDEX_REL, ["character_list"]),
    ]
    for rel_path, list_path in sources:
        path = runtime_root / rel_path
        if not path.exists():
            continue
        try:
            data = read_json(path)
        except Exception:
            continue
        node: Any = data
        for key in list_path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if not isinstance(node, list):
            continue
        for item in node:
            if not isinstance(item, dict):
                continue
            merge_name(names, item.get("id") or item.get("character_id") or item.get("m_character_id"), item.get("chara_name") or item.get("name"))
    mission_dir = runtime_root / MISSION_INDEX_DIR_REL
    if mission_dir.exists():
        for path in sorted(mission_dir.glob("mission_index*.json")):
            match = re.fullmatch(r"mission_index(\d+)\.json", path.name)
            if not match:
                continue
            char_id = int(match.group(1))
            if names.get(char_id):
                continue
            try:
                data = read_json(path)
            except Exception:
                continue
            for mission in data.get("chara_list") or []:
                if not isinstance(mission, dict):
                    continue
                mission_name = mission.get("name")
                if not isinstance(mission_name, str):
                    continue
                bracket = re.search(r"【(.+?)】", mission_name)
                if not bracket:
                    continue
                name = clean_character_name(bracket.group(1))
                if name:
                    merge_name(names, char_id, name)
                    break
    return names


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
    existing = load_name_rows(repo_root)
    for item in manifest:
        char_id = int(item["character_id"])
        if char_id not in names and item.get("character_name"):
            names[char_id] = item["character_name"]
    rows = [
        {
            "id": char_id,
            "ja": names.get(char_id, ""),
            "zh": existing.get(char_id, {}).get("zh", ""),
            "note": existing.get(char_id, {}).get("note", ""),
        }
        for char_id in sorted(names)
    ]
    write_json(repo_root / "names/characters.json", rows)
    write_name_markdown(repo_root / "names/characters.md", rows)


def load_name_rows(repo_root: pathlib.Path) -> Dict[int, Dict[str, str]]:
    path = repo_root / "names/characters.json"
    if not path.exists():
        return {}
    try:
        data = read_json(path)
    except Exception:
        return {}
    rows: Dict[int, Dict[str, str]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            char_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        rows[char_id] = {
            "ja": str(item.get("ja") or ""),
            "zh": str(item.get("zh") or ""),
            "note": str(item.get("note") or ""),
        }
    return rows


def load_name_glossary(repo_root: pathlib.Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in load_name_rows(repo_root).values():
        ja = item.get("ja", "")
        zh = item.get("zh", "")
        if ja and zh:
            result[ja] = zh
    return result


def load_name_by_id(repo_root: pathlib.Path) -> Dict[int, str]:
    result: Dict[int, str] = {}
    for char_id, item in load_name_rows(repo_root).items():
        if item.get("zh"):
            result[char_id] = item["zh"]
    return result


def write_name_markdown(path: pathlib.Path, rows: List[Dict[str, Any]]) -> None:
    lines = [
        "# Character Name Glossary",
        "",
        "`zh` 是剧情翻译会优先使用的人名；不确定时先留空，游戏文本会保留日文名。",
        "",
        "| id | ja | zh | note |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(row.get("id")),
                    markdown_cell(row.get("ja")),
                    markdown_cell(row.get("zh")),
                    markdown_cell(row.get("note")),
                ]
            )
            + " |"
        )
    write_text(path, "\n".join(lines) + "\n")


def call_deepseek_names(
    api_key: str,
    model: str,
    rows: List[Dict[str, Any]],
    retries: int = 3,
) -> Dict[int, str]:
    url = "https://api.deepseek.com/chat/completions"
    input_rows = [
        {
            "id": item["id"],
            "ja_hex": to_codepoints(item["ja"]),
        }
        for item in rows
    ]
    system_prompt = (
        "You are creating a Simplified Chinese character-name glossary for a Japanese visual novel. "
        "Decode ja_hex first. Transliterate katakana names into natural Chinese names, keep Japanese kanji names as readable Simplified Chinese, "
        "and translate costume labels such as 水着 into Chinese while preserving parentheses. "
        "Keep the result short. Do not include explanations or notes. Return JSON only."
    )
    user_prompt = (
        "Translate each character name. Return exactly this schema: "
        "{\"names\":[{\"id\":1001,\"zh\":\"Chinese name\"}]}.\n"
        + json.dumps({"names": input_rows}, ensure_ascii=True)
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    for attempt in range(1, retries + 1):
        try:
            requests = http_requests()
            response = requests.post(url, headers=headers, json=payload, timeout=180)
            response.raise_for_status()
            parsed = json.loads(response.json()["choices"][0]["message"]["content"])
            result: Dict[int, str] = {}
            for item in parsed.get("names", []):
                try:
                    char_id = int(item.get("id"))
                except (TypeError, ValueError):
                    continue
                zh = item.get("zh")
                if isinstance(zh, str) and zh.strip():
                    result[char_id] = clean_character_name(zh)
            if result:
                return result
            raise RuntimeError("empty name translation result")
        except Exception as exc:
            if attempt >= retries:
                raise
            print(f"DeepSeek name retry {attempt}/{retries}: {exc}", flush=True)
            time.sleep(3 * attempt)
    return {}


def translate_name_table(repo_root: pathlib.Path, api_key: str, model: str, chunk_size: int) -> None:
    path = repo_root / "names/characters.json"
    rows = read_json(path)
    pending = [row for row in rows if row.get("ja") and not row.get("zh")]
    for start in range(0, len(pending), chunk_size):
        chunk = pending[start : start + chunk_size]
        translated = call_deepseek_names(api_key, model, chunk)
        for row in rows:
            char_id = row.get("id")
            if char_id in translated and not row.get("zh"):
                row["zh"] = translated[char_id]
        print(f"translated names {min(start + len(chunk), len(pending))}/{len(pending)}", flush=True)
    write_json(path, rows)
    write_name_markdown(repo_root / "names/characters.md", rows)


def generate_api_translation(repo_root: pathlib.Path, story_index: Dict[str, Any], name_by_id: Dict[int, str]) -> None:
    data = copy.deepcopy(story_index)
    characters = data.get("character_list") or data.get("data", {}).get("character_list") or []
    for character in characters:
        try:
            char_id = int(character.get("id") or character.get("character_id") or character.get("m_character_id"))
        except (TypeError, ValueError):
            char_id = 0
        if char_id and name_by_id.get(char_id):
            character["chara_name"] = name_by_id[char_id]
        for story in character.get("story") or []:
            name = story.get("story_name")
            if name in JP_STORY_NAME_TO_ZH:
                story["story_name"] = JP_STORY_NAME_TO_ZH[name]
    write_json(
        repo_root / "translations/api/lilyange.saikyo.biz/character_story_index.json",
        data,
    )


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


def remote_content_length(url: str) -> Optional[int]:
    try:
        requests = http_requests()
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
            requests = http_requests()
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


def replace_name_value(node: Any, name_glossary: Dict[str, str]) -> bool:
    if not isinstance(node, dict):
        return False
    value = node.get("value")
    replacement = name_glossary.get(value) if isinstance(value, str) else None
    if replacement and replacement != value:
        node["value"] = replacement
        return True
    return False


def replace_display_names(data: Dict[str, Any], name_glossary: Dict[str, str]) -> int:
    if not name_glossary:
        return 0
    changed = 0
    for field in ("AuthorId", "Speaker"):
        if replace_name_value(data.get(field), name_glossary):
            changed += 1
    return changed


def command_spot(data: Dict[str, Any]) -> Dict[str, Any]:
    spot = data.get("playbackSpot")
    return spot if isinstance(spot, dict) else {}


def load_unity_bundle(bundle_path: pathlib.Path) -> Any:
    import UnityPy

    return UnityPy.load(str(bundle_path))


def extract_lines(bundle_path: pathlib.Path) -> List[Dict[str, Any]]:
    env = load_unity_bundle(bundle_path)
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


def patch_bundle(
    source_bundle: pathlib.Path,
    output_bundle: pathlib.Path,
    translations: Dict[str, str],
    name_glossary: Optional[Dict[str, str]] = None,
) -> int:
    env = load_unity_bundle(source_bundle)
    changed = 0
    name_changed = 0
    name_glossary = name_glossary or {}
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
            if replace_display_names(data, name_glossary):
                name_changed += 1
                object_changed = True
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
                data["Text"]["value"] = to_game_display_text(translated)
                changed += 1
                object_changed = True
        if object_changed:
            obj.save_typetree(tree)
    if changed or name_changed:
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


def from_review_translation(path: pathlib.Path) -> Dict[str, str]:
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


def save_review(path: pathlib.Path, story: Dict[str, Any], source_lines: List[Dict[str, Any]], zh_map: Dict[str, str]) -> None:
    rows = []
    for line in source_lines:
        item = {
            "key": line["key"],
            "speaker": line.get("speaker", ""),
            "ja": line["ja"],
            "zh": zh_map.get(line["key"], ""),
            "note": "",
        }
        rows.append(item)
    write_json(
        path,
        {
            "script": story["script"],
            "character_id": story.get("character_id"),
            "character_name": story.get("character_name", ""),
            "adv_id": story.get("adv_id"),
            "story_name": story.get("story_name", ""),
            "status": "draft",
            "review_note": "Edit zh until it reads naturally, then run translate_lilyange.py with --apply-review.",
            "lines": rows,
        },
    )
    save_review_markdown(path.with_suffix(".md"), story, rows)


def save_review_markdown(path: pathlib.Path, story: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    title_parts = [
        str(story.get("script") or path.stem),
        str(story.get("character_name") or ""),
        str(story.get("story_name") or ""),
    ]
    title = " / ".join(part for part in title_parts if part)
    lines = [
        f"# {title}",
        "",
        "确认顺序：先看 zh 是否像自然中文；需要改时改同名 JSON 文件里的 zh 字段，然后再执行 --apply-review。",
        "",
        "| key | speaker | ja | zh | note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(row.get("key")),
                    markdown_cell(row.get("speaker")),
                    markdown_cell(row.get("ja")),
                    markdown_cell(row.get("zh")),
                    markdown_cell(row.get("note")),
                ]
            )
            + " |"
        )
    write_text(path, "\n".join(lines) + "\n")


def call_deepseek(
    api_key: str,
    model: str,
    chunk: List[Dict[str, Any]],
    name_glossary: Dict[str, str],
    retries: int = 3,
) -> Dict[str, str]:
    url = "https://api.deepseek.com/chat/completions"
    input_rows = [
        {
            "key": item["key"],
            "speaker_hex": to_codepoints(item.get("speaker") or ""),
            "speaker_zh": name_glossary.get(item.get("speaker") or "", ""),
            "text_hex": to_codepoints(item["ja"]),
        }
        for item in chunk
    ]
    combined_text = "\n".join((item.get("speaker") or "") + "\n" + item["ja"] for item in chunk)
    relevant_names = [
        {"ja_hex": to_codepoints(ja), "zh": zh}
        for ja, zh in sorted(name_glossary.items())
        if ja and zh and ja in combined_text
    ]
    system_prompt = (
        "你是资深中文视觉小说本地化编辑，不是逐词翻译器。"
        "最终译文必须像中文原创台词，中文流畅度优先于保留日文语序。"
        "可以在不改变剧情事实的前提下重组句子、补足中文自然主语、合并重复语气词、改掉日式倒装。"
        "保留角色的调侃、撒娇、迟疑和情绪温度，但不要硬套日文表达。"
        "使用简体中文口语，短句，适合游戏文本框。"
        "必须严格使用 name_glossary 里给出的中文人名。"
        "保留 UI 命令、占位符、数字、括号和符号。"
        "避免机器翻译腔，例如“这里倒是挺老实的”“才嘴硬”“说了那种话却”这类日式中文。"
        "例：ふふっ、あれだけ言っておきながら……ここは正直っすね♥ 不要译成“呵呵，刚才还嘴硬……这里倒是挺老实的嘛♥”，"
        "应润色成“哼哼，嘴上说得那么厉害，身体倒是很诚实嘛♥”这类自然中文。"
        "输入文本是用空格分隔的 Unicode 十六进制码位；先解码再翻译。只返回 JSON。"
    )
    user_prompt = (
        "把每一行润色成本地化后的简体中文。不要逐字硬翻，优先让中文读起来顺。严格返回这个 schema："
        "{\"lines\":[{\"key\":\"same key\",\"zh\":\"Chinese translation\"}]}.\n"
        + json.dumps({"name_glossary": relevant_names, "lines": input_rows}, ensure_ascii=True)
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.35,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    for attempt in range(1, retries + 1):
        try:
            requests = http_requests()
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
            print(f"DeepSeek retry {attempt}/{retries}: {exc}", flush=True)
            time.sleep(3 * attempt)
    return {}


def translate_lines(
    source_lines: List[Dict[str, Any]],
    existing: Dict[str, str],
    name_glossary: Dict[str, str],
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
        translated = call_deepseek(api_key, model, chunk, name_glossary)
        result.update(translated)
        print(f"translated {min(start + len(chunk), len(pending))}/{len(pending)} lines", flush=True)
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
    parser.add_argument("--review-only", action="store_true")
    parser.add_argument("--apply-review", action="store_true")
    parser.add_argument("--auto-apply", action="store_true")
    parser.add_argument("--force-retranslate", action="store_true")
    parser.add_argument("--translate-names", action="store_true")
    args = parser.parse_args()

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    runtime_root = pathlib.Path(args.runtime_root)
    char_filter = parse_int_set(args.ids)
    adv_filter = parse_int_set(args.adv)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    story_index, names, stories = load_story_index(runtime_root)
    for char_id, name in load_character_names(runtime_root).items():
        if name and not names.get(char_id):
            names[char_id] = name
    bundles = load_catalog(runtime_root)
    full_manifest = build_story_manifest(stories, names, bundles)

    write_name_table(repo_root, names, full_manifest)
    if args.translate_names:
        if not api_key:
            print("DEEPSEEK_API_KEY is not set; generated name table without Chinese names.", file=sys.stderr)
            return 2
        translate_name_table(repo_root, api_key, args.model, args.chunk_size)
    name_by_id = load_name_by_id(repo_root)
    name_glossary = load_name_glossary(repo_root)
    write_json(repo_root / "manifest.json", full_manifest)
    generate_api_translation(repo_root, story_index, name_by_id)
    refresh_translated_index(repo_root)

    if args.metadata_only:
        return 0

    manifest = list(full_manifest)
    if char_filter is not None:
        manifest = [item for item in manifest if int(item["character_id"]) in char_filter]
    if adv_filter is not None:
        manifest = [item for item in manifest if int(item["adv_id"]) in adv_filter]
    if args.limit is not None:
        manifest = manifest[: args.limit]

    review_only = args.review_only or (not args.auto_apply and not args.apply_review and not args.no_translate)

    if not args.no_translate and not args.apply_review and not api_key:
        print("DEEPSEEK_API_KEY is not set; generated metadata only.", file=sys.stderr)
        return 2

    for index, item in enumerate(manifest, 1):
        script = item["script"]
        filename = item["bundle"]
        print(f"[{index}/{len(manifest)}] {script} {item.get('character_name', '')} {item.get('story_name', '')}")
        bundle_out = repo_root / "bundles/WebGL/naninovelseparate_assets_naninovel/scripts" / filename
        translation_path = repo_root / "translations/naninovel/scripts" / f"{script}.json"
        review_path = repo_root / "reviews/naninovel/scripts" / f"{script}.json"
        if args.skip_existing and bundle_out.exists() and from_existing_translation(translation_path):
            print("skip existing")
            continue
        source_bundle = ensure_bundle(runtime_root, repo_root, filename)
        source_lines = extract_lines(source_bundle)
        write_json(repo_root / "sources/naninovel/scripts" / f"{script}.json", {"lines": source_lines})
        if args.no_translate:
            existing = from_review_translation(review_path) or from_existing_translation(translation_path)
            save_translation(translation_path, source_lines, existing)
            continue

        if args.apply_review:
            zh_map = from_review_translation(review_path)
            if not zh_map:
                print(f"review file has no Chinese lines: {review_path}", file=sys.stderr)
                return 3
            save_translation(translation_path, source_lines, zh_map)
            changed = patch_bundle(source_bundle, bundle_out, zh_map, name_glossary)
            print(f"patched {changed}/{len(source_lines)} lines from review")
            refresh_translated_index(repo_root)
            continue

        existing = {} if args.force_retranslate else from_review_translation(review_path)
        zh_map = translate_lines(source_lines, existing, name_glossary, api_key, args.model, args.chunk_size)
        save_review(review_path, item, source_lines, zh_map)
        print(f"review draft: {review_path}")
        if review_only:
            continue

        save_translation(translation_path, source_lines, zh_map)
        changed = patch_bundle(source_bundle, bundle_out, zh_map, name_glossary)
        print(f"patched {changed}/{len(source_lines)} lines")
        refresh_translated_index(repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
