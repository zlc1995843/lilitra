# lilitra

`lilian` 启动器的中文翻译仓库。

启动器开启“中文”后会优先从本仓库的 raw 文件读取翻译内容；如果对应文件不存在，或者内容还没有中文，就继续读取本地日文原文。

## 目录

- `names/characters.json`：角色名表。
- `manifest.json`：从本地 API 与 Unity catalog 生成的剧情资源清单。
- `sources/naninovel/scripts/`：从 Naninovel bundle 提取出的日文文本，方便校对。
- `translations/naninovel/scripts/`：DeepSeek 生成的中文文本记录。
- `translations/api/`：普通 API JSON 的中文覆盖文件。
- `bundles/WebGL/naninovelseparate_assets_naninovel/scripts/`：已写入中文文本、可被启动器直接覆盖读取的剧情 bundle。

## 更新翻译

先设置 DeepSeek key：

```powershell
$env:DEEPSEEK_API_KEY="你的 key"
```

然后运行：

```powershell
python -X utf8 tools/translate_lilyange.py --runtime-root "F:\03DMM\diss lolicon" --limit 1
```

常用参数：

- `--ids 1001,1002`：只处理指定角色。
- `--adv 101,201,202`：只处理指定剧情类型。
- `--limit 10`：限制本次处理的 bundle 数量，方便分批跑。
- `--skip-existing`：已有中文翻译和中文 bundle 时跳过。
- `--no-translate`：只生成名字表、清单和 API 覆盖文件，不调用 DeepSeek。

翻译风格要求：保留日式语气，中文自然但不改剧情信息。
