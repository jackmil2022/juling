---
name: minimax-multimodal-toolkit
description: Use mmx to generate text, images, video, and speech, and to transcribe audio, via the MiniMax AI platform. Use when the user wants to create media content, chat with MiniMax models, transcribe audio to text, perform web search, or manage MiniMax API resources from the terminal.
---

# MiniMax CLI — 座席技能指南

使用 `mmx` 生成文本、图像、视频、语音、转录音频，并通过 MiniMax AI 平台执行网络搜索。

## 先决条件

```bash
# Install
npm install -g mmx-cli

# Auth (OAuth persists to ~/.mmx/credentials.json, API key persists to ~/.mmx/config.json)
mmx auth login --api-key sk-xxxxx

# Verify active auth source
mmx auth status

# Or pass per-call
mmx text chat --api-key sk-xxxxx --message "Hello"
```

自动检测区域。使用 `--region global` 或 `--region cn` 覆盖。

---

## 代理标志

始终在非交互式（代理/CI）上下文中使用这些标志：

|旗帜|目的|
|---|---|
| `--non-interactive` |缺少参数时快速失败而不是提示 |
| `--quiet` |抑制旋转/进度；标准输出是纯数据 |
| `--output json` |机器可读的 JSON 输出 |
| `--async` |立即返回任务ID（视频生成）|
| `--dry-run` |预览 API 请求而不执行 |
| `--yes` |跳过确认提示 |

---

## 命令

### 文字聊天

聊天完成。默认型号：`MiniMax-M3.1-Flash`。显式 `--model` 或保存的 `default-text-model` 优先。该模型目前需要M Plan或MiniMax Code；对于现收现付密钥，请使用 `--model MiniMax-M3`。默认情况下，通过 `max` 努力即可启用思考。请参阅[型号指南](https://platform.minimax.io/docs/guides/text-generation#agent)。

```bash
mmx text chat --message <text> [flags]
```

|旗帜|类型 |描述 |
|---|---|---|
| `--message <text>` |字符串，**必需**，可重复 |消息文本。以 `role:` 为前缀来设置角色（例如 `"system:You are helpful"`、`"user:Hello"`）|
| `--messages-file <path>` |字符串|带有消息数组的 JSON 文件。使用 `-` 作为标准输入 |
| `--system <text>` |字符串|系统提示|
| `--model <model>` |字符串|型号 ID（默认：`MiniMax-M3.1-Flash`）|
| `--max-tokens <n>` |数量 |最大令牌数（默认：4096）|
| `--temperature <n>` |数量 |采样温度（0.0，1.0]|
| `--top-p <n>` |数量 |细胞核采样阈值 |
| `--stream` |布尔 |流令牌（默认：在 TTY 中打开）|
| `--tool <json-or-path>` |字符串，可重复 |工具定义 JSON 或文件路径 |

```bash
# Single message
mmx text chat --message "user:What is MiniMax?" --output json --quiet

# Multi-turn
mmx text chat \
  --system "You are a coding assistant." \
  --message "user:Write fizzbuzz in Python" \
  --output json

# From file
cat conversation.json | mmx text chat --messages-file - --output json
```

**stdout**：响应文本（文本模式）或完整响应对象（json 模式）。

---

### 图像生成

使用 `MiniMax-H3-Image` 生成或编辑图像（高达 20 MP）。始终通过 `--model MiniMax-H3-Image`。使用`--image`进行图像编辑。

```bash
mmx image generate --model MiniMax-H3-Image --prompt <text> [flags]
```

|旗帜|类型 |描述 |
|---|---|---|
| `--prompt <text>` |字符串，**必需** |图片说明|
| `--model <model>` |字符串|使用`MiniMax-H3-Image` |
| `--image <path-or-url>` |字符串，可重复 | 1–16 参考图像 → 图像编辑 (`/v1/images/edits`)。顺序 = 图片 1、2、... |
| `--aspect-ratio <X:Y>` |字符串| `auto`（默认）或 X:Y（整数 1–300）在 1:3 和 3:1 之间 |
| `--area <level>` |字符串| `1K`、`2K`、`4K`（默认）|
| `--size <WxH>` |字符串| `auto` 或例如`2720x1536`；面积 655,360–20,000,000 像素，比例 1:3–3:1。不适用于 `--aspect-ratio`/`--area` |
| `--n <count>` |数量 | 1–10（默认值：1）|
| `--output-format <fmt>` |字符串| `jpg`（默认）、`png`、`webp` |
| `--output-compression <q>` |数量 | 0–100（默认 95），仅限 jpg/webp |
| `--no-prompt-enhance` |布尔 |仅文本到图像；需要 `--size` 或混凝土 `--aspect-ratio` |
| `--response-format <format>` |字符串| `url`（默认）或 `base64`。 Base64 绕过 CDN 下载 |
| `--out-dir <dir>` |字符串|将图像下载到目录 |
| `--out-prefix <prefix>` |字符串|文件名前缀（默认：`image`）|
| `--out <path>` |字符串|将单个图像保存到精确路径 |
| `--aigc-watermark` |布尔 |嵌入人工智能生成的内容水印 |

H3-Image 是同步的并且**非幂等** — 不要仅仅因为命令速度慢而重新运行命令；每次运行都会计费。部分失败以 JSON 输出中的 `failed_count`/`failures` 退出 0（即使使用 `--quiet`，失败也会打印到 stderr）。使用 `--response-format base64`，总面积 `n` × W × H 对于 png 限制为 20 MP，对于 jpg/webp 限制为 80 MP（`size auto` 计算 `--area` 级别，例如 4K = 4096×4096）。

```bash
mmx image generate --model MiniMax-H3-Image --prompt "A cat on a windowsill" --aspect-ratio 16:9 --area 2K --output json --quiet
mmx image generate --model MiniMax-H3-Image --prompt "Put the hat from Picture 2 on the person in Picture 1" --image person.jpg --image hat.png --out result.jpg --quiet
mmx image generate --model MiniMax-H3-Image --prompt "Logo" --n 3 --out-dir ./gen/ --quiet
# stdout: saved file paths (one per line)
```

---

### 视频生成

生成视频。默认模型：`MiniMax-Hailuo-2.3`（或 `MiniMax-Hailuo-2.3-Fast` 用于带有 `--image` 的快速模式）。这是一个异步任务——默认情况下它会轮询直到完成。

对于 `MiniMax-H3` — 文本到视频、第一帧/最后一帧、多模式参考图像/视频/音频生成、提示构建和故障处理 — 请改用专用的 [mmx-h3-video Skill](https://github.com/MiniMax-AI/cli/blob/main/skill/h3-video/SKILL.md)。

```bash
mmx video generate --prompt <text> [flags]
```

|旗帜|类型 |描述 |
|---|---|---|
| `--prompt <text>` |字符串，**必需** |视频说明|
| `--model <model>` |字符串| `MiniMax-Hailuo-2.3`（默认）或 `MiniMax-Hailuo-2.3-Fast` |
| `--image <path-or-url>` |字符串|图像转视频的输入图像 |
| `--last-frame <path-or-url>` |字符串|用于帧插值的可选结束图像（与 `--image` 一起使用）|
| `--callback-url <url>` |字符串|用于补全的 Webhook URL |
| `--download <path>` |字符串|将视频保存到特定文件 |
| `--async` |布尔 |立即返回任务ID |
| `--no-wait` |布尔 |与`--async`相同|
| `--poll-interval <seconds>` |数量 |轮询间隔（默认：5）|

```bash
# Non-blocking: get task ID
mmx video generate --prompt "A robot." --async --quiet
# stdout: {"taskId":"..."}

# Blocking: wait and get file path
mmx video generate --prompt "Ocean waves." --download ocean.mp4 --quiet
# stdout: ocean.mp4
```

###视频任务获取

查询视频生成任务的状态。

```bash
mmx video task get --task-id <id> [--output json]
```

###视频下载

按任务 ID 下载已完成的视频。

```bash
mmx video download --file-id <id> [--out <path>]
```

---

### 语音合成

文本转语音。默认型号：`speech-2.8-hd`。最多 10k 个字符。

```bash
mmx speech synthesize --text <text> [flags]
```

|旗帜|类型 |描述 |
|---|---|---|
| `--text <text>` |字符串|要合成的文本 |
| `--text-file <path>` |字符串|从文件中读取文本。使用 `-` 作为标准输入 |
| `--model <model>` |字符串| `speech-2.8-hd`（默认）、`speech-2.6`、`speech-02` |
| `--voice <id>` |字符串|语音ID（默认：`English_expressive_narrator`）|
| `--speed <n>` |数量 |速度倍增器|
| `--volume <n>` |数量 |音量级别|
| `--pitch <n>` |数量 |音高调节 |
| `--format <fmt>` |字符串|音频格式（默认：`mp3`）|
| `--sample-rate <hz>` |数量 |采样率（默认：32000）|
| `--bitrate <bps>` |数量 |比特率（默认：128000）|
| `--channels <n>` |数量 |音频通道（默认：1）|
| `--language <code>` |字符串|语言提升 |
| `--subtitles` |布尔 |下载字幕并将其保存为 `.srt` 文件（与 `--out` 音频文件一起）。 API 必须支持所选模型的字幕。
| `--pronunciation <from/to>` |字符串，可重复 |自定义发音 |
| `--sound-effect <effect>` |字符串|添加音效 |
| `--out <path>` |字符串|将音频保存到文件 |
| `--stream` |布尔 |将原始音频流式传输到标准输出 |

```bash
mmx speech synthesize --text "Hello world" --out hello.mp3 --quiet
# stdout: hello.mp3

mmx speech synthesize --text "Hello" --subtitles --out hello.mp3
# saves hello.mp3 + hello.srt (SRT subtitle file)

echo "Breaking news." | mmx speech synthesize --text-file - --out news.mp3
```

---

### 语音转录

语音到文本。默认型号：`asr-1.0`。接受 wav、aiff、flac、m4a、mp3、aac、opus 和
ogg 文件最大为 50 MB，时间为 500 秒。

```bash
mmx speech transcribe --file <path> [flags]
```

|旗帜|类型 |描述 |
|---|---|---|
| `--file <path>` |字符串|要转录的音频文件（必需；也可以作为位置参数接受）|
| `--model <model>` |字符串| `asr-1.0`（默认）|
| `--response-format <fmt>` |字符串| `json`（默认）、`verbose_json`、`srt`、`vtt` |
| `--language <code>` |字符串| BCP-47 语言提示（`zh`、`en`、`ja`，...）。省略自动/混合语言检测 |
| `--timestamp-level <level>` |字符串| `sentence`（默认）或`word`；适用于`verbose_json` / `srt` / `vtt` |
| `--stream` |布尔 |将增量文本流式传输到标准输出。需要 `--response-format json` |
| `--out <path>` |字符串|将结果写入文件而不是 stdout |

```bash
mmx speech transcribe --file meeting.mp3
# stdout: transcript text

mmx speech transcribe --file call.mp3 --language zh --output json
# stdout: {"text":"...","duration":12.3,"trace_id":"..."}

mmx speech transcribe --file talk.mp3 --response-format verbose_json --timestamp-level word --output json
# stdout: adds n_speakers and word-level segments

mmx speech transcribe --file talk.mp3 --response-format srt --out talk.srt
# saves talk.srt; stdout: {"saved":".../talk.srt"}

mmx speech transcribe --file long.mp3 --stream
# stdout: text as it is recognized (add --output text when piping)
```

注意事项：
- `mmx speech recognize` 是 `mmx speech transcribe` 的别名。
- `--stream`不能与`--out`组合使用；而是重定向标准输出。
- `--stream` 仅在文本输出模式下打印增量。非终端的标准输出默认为
  `json`（与此 CLI 中的其他地方一样），它将流式文本累积到一个 JSON 中
  结果 - 将 `--output text` 传递给管道流文本，例如
  `mmx speech transcribe --file long.mp3 --stream --output text > transcript.txt`。
- `srt` / `vtt` 结果是字幕文档，并逐字打印或保存。
- 如果没有 `--out`，`--output json` 将打印 `json` / `verbose_json` 的完整 API 响应。
  纯文本输出仅打印文字记录，因此添加 `--output json` 来读取 `n_speakers`
  和`segments`。
- 在没有 API 最终事件的情况下结束的流会在 stderr 上引发警告，因为
  转录本可能会被截断。
- 输入验证（缺少文件、不受支持的格式、超过 50 MB、带有非 json 的 `--stream`
  格式）在上传任何内容之前失败； API 在 500 秒内保持权威
  限制和编解码器支持。

---

### 愿景描述

通过 VLM 理解图像。提供 `--image` 或 `--file-id` 之一，而不是两者都提供。

```bash
mmx vision describe (--image <path-or-url> | --file-id <id>) [flags]
```

|旗帜|类型 |描述 |
|---|---|---|
| `--image <path-or-url>` |字符串|本地路径或 URL（自动 Base64 编码）|
| `--file-id <id>` |字符串|预上传文件ID（跳过base64）|
| `--prompt <text>` |字符串|关于图像的问题（默认：`"Describe the image."`）|

```bash
mmx vision describe --image photo.jpg --prompt "What breed?" --output json
```

**stdout**：描述文本（文本模式）或完整响应（json 模式）。

---

### 搜索查询

通过 MiniMax 进行网络搜索。

```bash
mmx search query --q <query>
```

|旗帜|类型 |描述 |
|---|---|---|
| `--q <query>` |字符串，**必需** |搜索查询 |

```bash
mmx search query --q "MiniMax AI" --output json --quiet
```

---

###配额展示

显示令牌计划使用情况和剩余配额。

```bash
mmx quota show [--output json]
```

---

## 工具架构导出

将所有命令导出为 Anthropic/OpenAI 兼容的 JSON 工具模式：

```bash
# All tool-worthy commands (excludes auth/config/update)
mmx config export-schema

# Single command
mmx config export-schema --command "video generate"
```

使用它可以动态地将 mmx 命令注册为代理框架中的工具。

---

## 退出代码

|代码|意义|
|---|---|
| 0 |成功|
| 1 |一般错误 |
| 2 |使用错误（错误标志、缺少参数）|
| 3 |身份验证错误 |
| 4 |超出配额 |
| 5 |超时|
| 10 | 10内容过滤器已触发 |

---

## 管道图案

```bash
# stdout is always clean data — safe to pipe
mmx text chat --message "Hi" --output json | jq '.content'

# stderr has progress/spinners — discard if needed
mmx video generate --prompt "Waves" 2>/dev/null

# Chain: generate image → describe it
URL=$(mmx image generate --model MiniMax-H3-Image --prompt "A sunset" --quiet)
mmx vision describe --image "$URL" --quiet

# Async video workflow
TASK=$(mmx video generate --prompt "A robot" --async --quiet | jq -r '.taskId')
mmx video task get --task-id "$TASK" --output json
mmx video download --task-id "$TASK" --out robot.mp4
```

---

## 配置优先级

CLI 标志 → 环境变量 → `~/.mmx/config.json` → 默认值。

```bash
# Persistent config
mmx config set --key region --value cn
mmx config show

# Environment
export MINIMAX_API_KEY=sk-xxxxx
export MINIMAX_REGION=cn
```

### 默认模型配置

设置每种模式的默认值，这样您就不需要每次都需要 `--model`：

```bash
# Set defaults
mmx config set --key default-text-model --value MiniMax-M3.1-Flash
mmx config set --key default-speech-model --value speech-2.8-hd
mmx config set --key default-video-model --value MiniMax-Hailuo-2.3

# Use without --model
mmx text chat --message "Hello"
mmx speech synthesize --text "Hello" --out hello.mp3
mmx video generate --prompt "Ocean waves"

# --model still overrides per-call
mmx text chat --model MiniMax-M3.1-Flash --message "Hello"
```

**分辨率优先级**：`--model` 标志 > 配置默认值 > 硬编码后备。
