#!/usr/bin/env python3
"""扫描剧本包，提取说话人/代词候选，生成专名待确认清单（先扫描、再确认、后翻译的闸门第一步）。

用法（lilitra 仓库根目录）：
  set PY=G:\\11 AI_Models\\manga-tra\\Miniconda3\\python.exe
  %PY% tools\\scan_story_terms.py --runtime-root "F:\\03DMM\\diss lolicon" --scope main ^
      --out-json <报告.json> --out-md <报告.md>

特性：
- 缺失的剧本包自动从 CDN 下载（复用管线 ensure_bundle，缓存在仓库 .cache 下，不污染游戏目录）
- 逐剧本提取结果写入 .cache/scan_lines/*.json，中断后重跑自动续扫
- 未识别说话人可选调用 DeepSeek 生成推荐译法（默认 deepseek-v4-flash，--no-suggest 关闭）
"""
import argparse
import collections
import json
import os
import pathlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import translate_lilyange as T  # noqa: E402

MAIN_RE = re.compile(r"\d{5}")   # 10101-11111（第一部）、20101-20110（第二部）
EVENT_RE = re.compile(r"2\d{5}")  # 200101+ 活动剧情

# 说话人串里出现这些特征，说明很可能是扫描误拼（跨占位符/整句被当成名字），不是真专名
SUSPECT_RE = re.compile(r"[{}「」『』。、！？…♥♪\n]")


def select_bundles(bundles: Dict[str, str], scope: str, ids: List[str]) -> Dict[str, str]:
    if ids:
        wanted = set(ids)
        return {b: f for b, f in bundles.items() if b in wanted}
    if scope == "main":
        return {b: f for b, f in bundles.items() if MAIN_RE.fullmatch(b)}
    if scope == "event":
        return {b: f for b, f in bundles.items() if EVENT_RE.fullmatch(b)}
    return {
        b: f
        for b, f in bundles.items()
        if MAIN_RE.fullmatch(b) or EVENT_RE.fullmatch(b)
    }


def scan_one(
    runtime_root: pathlib.Path, repo_root: pathlib.Path, base: str, filename: str, cache_dir: pathlib.Path
) -> Dict[str, Any]:
    cache_path = cache_dir / f"{base}.json"
    if cache_path.exists():
        try:
            return {"script": base, "lines": json.loads(cache_path.read_text(encoding="utf-8"))}
        except Exception:
            cache_path.unlink(missing_ok=True)
    path = T.ensure_bundle(runtime_root, repo_root, filename)
    lines = T.extract_lines(path)
    slim = [{"speaker": line.get("speaker") or "", "ja": line.get("ja") or ""} for line in lines]
    cache_path.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
    return {"script": base, "lines": slim}


def suggest_terms(api_key: str, model: str, candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """调 DeepSeek 为未识别说话人生成推荐译法；失败返回空 dict。"""
    if not candidates:
        return {}
    payload_terms = [
        {"ja": c["ja"], "count": c["count"], "contexts": [s["ja"] for s in c["samples"]]}
        for c in candidates
    ]
    system_prompt = (
        "你是资深中文视觉小说本地化编辑。下面是某 Galgame 剧本中出现的说话人名（日文），"
        "附出现次数和台词上下文。请为每个名字给出简体中文推荐译法。"
        "规则：真角色名给简洁中文名（可音译）；带敬称（さん/ちゃん/様/くん/先輩等）在译名中体现对应中文称呼；"
        "泛称（如 女性、店員、旁白类）直译；疑似扫描误拼的条目在 note 里标注 suspect。"
        "只返回 JSON：{\"terms\":[{\"ja\":\"原名\",\"zh\":\"推荐译法\",\"note\":\"一句理由\"}]}"
    )
    user_prompt = json.dumps({"speakers": payload_terms}, ensure_ascii=False)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    try:
        requests = T.http_requests()
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=180,
        )
        response.raise_for_status()
        parsed = json.loads(response.json()["choices"][0]["message"]["content"])
        result = {}
        for item in parsed.get("terms", []):
            ja = str(item.get("ja") or "")
            if ja:
                result[ja] = {"zh": str(item.get("zh") or ""), "note": str(item.get("note") or "")}
        return result
    except Exception as exc:  # 推荐失败不阻塞清单
        print(f"suggest_terms failed: {exc}", flush=True)
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--scope", default="main", choices=["main", "event", "all"])
    parser.add_argument("--ids", help="逗号分隔的剧本名，覆盖 --scope")
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--no-suggest", action="store_true")
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()

    runtime_root = pathlib.Path(args.runtime_root)
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    cache_dir = repo_root / ".cache" / "scan_lines"
    cache_dir.mkdir(parents=True, exist_ok=True)

    bundles = T.load_catalog(runtime_root)
    ids = [s.strip() for s in args.ids.split(",")] if args.ids else []
    wanted = select_bundles(bundles, args.scope, ids)
    print(f"scan scope={args.scope} scripts={len(wanted)}", flush=True)

    glossary = T.load_name_glossary(repo_root)

    speaker_count: collections.Counter = collections.Counter()
    speaker_samples: Dict[str, List[Dict[str, str]]] = collections.defaultdict(list)
    pronoun_count: collections.Counter = collections.Counter()
    pronoun_samples: Dict[str, List[Dict[str, str]]] = collections.defaultdict(list)
    script_stats: List[Dict[str, Any]] = []
    failed: List[Dict[str, str]] = []

    def handle(result: Dict[str, Any]) -> None:
        base = result["script"]
        lines = result["lines"]
        script_stats.append({"script": base, "lines": len(lines)})
        for line in lines:
            sp = str(line.get("speaker") or "").strip()
            ja = line.get("ja") or ""
            if sp and not (sp.startswith("{") and sp.endswith("}")):
                speaker_count[sp] += 1
                if len(speaker_samples[sp]) < args.samples:
                    speaker_samples[sp].append({"script": base, "ja": ja[:120]})
            for cand in T.PRONOUN_CANDIDATES:
                if cand in ja:
                    pronoun_count[cand] += 1
                    if len(pronoun_samples[cand]) < 2:
                        pronoun_samples[cand].append({"script": base, "ja": ja[:120]})

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        futures = {
            pool.submit(scan_one, runtime_root, repo_root, base, filename, cache_dir): base
            for base, filename in sorted(wanted.items())
        }
        for future in as_completed(futures):
            base = futures[future]
            done += 1
            try:
                handle(future.result())
                print(f"[{done}/{len(wanted)}] {base} ok", flush=True)
            except Exception as exc:
                failed.append({"script": base, "error": str(exc)})
                print(f"[{done}/{len(wanted)}] {base} FAILED: {exc}", flush=True)

    script_stats.sort(key=lambda s: s["script"])

    def speaker_entry(name: str) -> Dict[str, Any]:
        return {
            "ja": name,
            "count": speaker_count[name],
            "suspect": bool(SUSPECT_RE.search(name)) or len(name) > 24,
            "samples": speaker_samples[name],
        }

    known_speakers = [speaker_entry(s) for s in sorted(speaker_count) if s in glossary]
    unknown_speakers = [speaker_entry(s) for s in sorted(speaker_count, key=lambda s: -speaker_count[s]) if s not in glossary]
    for entry in known_speakers:
        entry["zh"] = glossary[entry["ja"]]

    unknown_pronouns = [
        {"ja": p, "count": c, "samples": pronoun_samples[p]}
        for p, c in sorted(pronoun_count.items(), key=lambda kv: -kv[1])
        if p not in glossary
    ]

    suggestions: Dict[str, Dict[str, str]] = {}
    if not args.no_suggest and unknown_speakers:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if api_key:
            real_candidates = [e for e in unknown_speakers if not e["suspect"]]
            suggestions = suggest_terms(api_key, args.model, real_candidates)
            print(f"suggestions: {len(suggestions)}/{len(real_candidates)}", flush=True)
        else:
            print("DEEPSEEK_API_KEY not set, skip suggestions", flush=True)
    for entry in unknown_speakers:
        sug = suggestions.get(entry["ja"])
        if sug:
            entry["suggested_zh"] = sug.get("zh", "")
            entry["suggest_note"] = sug.get("note", "")

    report = {
        "scope": args.scope,
        "scripts_total": len(wanted),
        "scripts_scanned": len(script_stats),
        "scripts_failed": failed,
        "total_lines": sum(s["lines"] for s in script_stats),
        "script_stats": script_stats,
        "unknown_speakers": unknown_speakers,
        "known_speakers": known_speakers,
        "unknown_pronouns": unknown_pronouns,
    }

    out_json = pathlib.Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md: List[str] = []
    md.append(f"# 剧本专名扫描报告（scope={args.scope}）")
    md.append("")
    md.append(f"- 剧本：{len(script_stats)}/{len(wanted)} 扫描成功，失败 {len(failed)}")
    md.append(f"- 总台词段数：{report['total_lines']}")
    md.append(f"- 未识别说话人：{len(unknown_speakers)}（其中疑似误拼 {sum(1 for e in unknown_speakers if e['suspect'])}）")
    md.append(f"- 未识别代词/称呼：{len(unknown_pronouns)}")
    md.append("")
    md.append("## 待确认：未识别说话人")
    md.append("")
    md.append("| 日文 | 次数 | 推荐译法 | 备注 | 上下文示例 |")
    md.append("| --- | --- | --- | --- | --- |")
    for e in unknown_speakers:
        sample = e["samples"][0] if e["samples"] else {"script": "", "ja": ""}
        ctx = f"{sample['script']}：{sample['ja']}".replace("|", "\\|").replace("\n", " ")
        flag = "⚠️疑似误拼 " if e["suspect"] else ""
        note = (flag + e.get("suggest_note", "")).replace("|", "\\|")
        md.append(f"| {e['ja']} | {e['count']} | {e.get('suggested_zh', '')} | {note} | {ctx} |")
    md.append("")
    md.append("## 待确认：未识别代词/称呼")
    md.append("")
    md.append("| 日文 | 次数 | 上下文示例 |")
    md.append("| --- | --- | --- |")
    for e in unknown_pronouns:
        sample = e["samples"][0] if e["samples"] else {"script": "", "ja": ""}
        ctx = f"{sample['script']}：{sample['ja']}".replace("|", "\\|").replace("\n", " ")
        md.append(f"| {e['ja']} | {e['count']} | {ctx} |")
    md.append("")
    md.append("## 已识别说话人（词库命中，无需处理）")
    md.append("")
    md.append("| 日文 | 中文 | 次数 |")
    md.append("| --- | --- | --- |")
    for e in sorted(known_speakers, key=lambda x: -x["count"]):
        md.append(f"| {e['ja']} | {e.get('zh', '')} | {e['count']} |")
    if failed:
        md.append("")
        md.append("## 扫描失败")
        md.append("")
        for f_ in failed:
            md.append(f"- {f_['script']}: {f_['error']}")
    out_md = pathlib.Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"report: {out_json} / {out_md}", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
