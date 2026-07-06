# lilitra

`lilian` 启动器的中文翻译仓库。

启动器开启“中文”后会优先从本仓库的 raw 文件读取翻译内容；如果对应文件不存在，或者内容还没有中文，就继续读取本地日文原文。

## 目录

- `names/characters.json`：角色名表。
- `manifest.json`：从本地 API 与 Unity catalog 生成的剧情资源清单。
- `sources/naninovel/scripts/`：从 Naninovel bundle 提取出的日文文本，方便校对。
- `reviews/naninovel/scripts/`：待确认的翻译校对稿，`.md` 用来看，`.json` 用来改。
- `translations/naninovel/scripts/`：DeepSeek 生成的中文文本记录。
- `translations/api/`：普通 API JSON 的中文覆盖文件。
- `bundles/WebGL/naninovelseparate_assets_naninovel/scripts/`：已写入中文文本、可被启动器直接覆盖读取的剧情 bundle。

