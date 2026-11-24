---
name: minimax-music-gen
description: >
  Use when user wants to generate music, songs, or audio tracks. Triggers on any request
  involving music creation, song writing, lyrics generation, audio production, or covers.
  Also triggers when user provides lyrics and wants them turned into a song, or describes
  a mood/scene and wants background music. Supports multilingual triggers — match equivalent
  phrases in any language. Do NOT use for music playback of existing files, music theory
  questions, or music recommendation without generation.
license: MIT
metadata:
  version: "1.1"
  category: creative
---

# MiniMax 音乐生成技能

使用 MiniMax Music API 生成歌曲（声乐或器乐）。支持二次创建
模式：**基本**（一句输入，歌曲输出）和**高级控制**（编辑歌词、精炼
提示，生成前计划）。

## 先决条件

- **mmx CLI**（必需）：音乐生成使用 `mmx` 命令行工具。

**检查是否安装：**
  ```bash
  command -v mmx && mmx --version || echo "mmx not found"
  ```

**安装（需要 Node.js）：**
  ```bash
  npm install -g mmx-cli
  ```

**验证（仅限第一次）：**
  ```bash
  mmx auth login --api-key <your-minimax-api-key>
  ```
API密钥可以从[MiniMax Platform](https://platform.minimaxi.com/)获取。
  凭据保存到 `~/.mmx/credentials.json` 并在会话中保留。

**核实：**
  ```bash
  mmx quota show
  ```

- **音频播放器**（推荐）：本地使用 `mpv`、`ffplay` 或 `afplay`（macOS 内置）
  播放。 `mpv` 因其交互式控件而受到青睐。

## CLI 工具

此技能使用 `mmx` CLI 来生成所有音乐：

- **音乐一代**：`mmx music generate` — 型号：`music-2.6-free`
  - 支持`--lyrics-optimizer`根据提示自动生成歌词
  - 支持 `--instrumental` 乐器曲目
  - 支持 `--lyrics` 用户提供的歌词
  - 结构化参数：`--genre`、`--mood`、`--vocals`、`--instruments`、`--bpm`、`--key`、`--tempo`、`--structure`、`--references`
  
- **盖子**：`mmx music cover` — 型号：`music-cover-free`
  - 通过 `--audio-file <path>` 或 `--audio <url>` 获取参考音频
  - `--prompt`描述目标封面样式

**代理标志**：从代理调用 mmx 时始终添加 `--quiet --non-interactive`。

**管道**：
- 演唱：`User description -> mmx music generate --lyrics-optimizer -> MP3`
- 器乐：`User description -> mmx music generate --instrumental -> MP3`
- 封面：`Source audio + style -> mmx music cover -> MP3`

＃＃ 贮存

所有生成的音乐都保存到 `~/Music/minimax-gen/`。如果没有则创建该目录
存在。文件以时间戳和源自提示的短段命名：
ZZ保留1ZZ

---

## 语言与互动

从用户的第一条消息中检测用户的语言，并以该语言回复第二条消息
整个会议。这适用于所有交互文本、问题、确认和反馈
提示。

**面向用户的文本本地化规则**：
- 向用户显示的所有文本 - 包括预览标签、字段名称、确认、状态
  消息、播放信息、反馈提示、**和提示/描述预览** — 必须
  完全翻译成用户的语言。
- 发送到模型的 **API 提示** 应始终以英文书写以获得最佳效果
  一代品质。但是，在向用户预览提示时，显示本地化的
  使用用户语言的描述而不是原始的英语提示。英文提示
  是一个内部实现细节——用户不需要看到它。
- 以下模板是用英文编写的，仅供参考。在运行时，翻译每个标签
  并将消息转换为用户检测到的语言。

**歌词语言规则**：
- 默认歌词语言=用户的语言。中文用户获取中文歌词；
  英语用户获得英文歌词。
- 仅当用户**明确**请求时才生成不同语言的歌词。
- 当需要不同的歌词语言时，将其自然地嵌入到人声或流派中
  提示中的描述。例如，不要附加“韩语歌词”，而是使用
  “以韩国女歌手为特色”或指定暗示该语言的流派（例如，
  “K-pop”、“J-rock”、“Mandopop”、“Latin pop”）。

---

## 工作流程

### 步骤 0：检测意图

解析用户的消息以确定：

1. **歌曲类别**：人声（带歌词）、器乐（无人声）或翻唱
2. **创建模式偏好**：他们是否提供了详细的要求（高级）或
   休闲单行（基本）？

如果不明确，请使用此决策树询问：

```
Q1: What type of music?
  - Vocal (with lyrics)
  - Instrumental (no vocals)
  - Cover

Q2: Creation mode?
  - Basic — one-line description, auto-generate
  - Advanced — edit lyrics, refine prompt, plan
```

如果用户给出了清晰的台词，例如“给我一首悲伤的钢琴曲”，请跳过问题 -
推断工具+基本模式并继续。

---

### 第 1 步：基本模式

**目标**：用户提供简短的描述，技能自动生成所有内容，然后调用
API。

1. **将描述展开为提示**：将用户的单行文字展开为
   丰富的音乐提示。请参阅本文末尾的 **提示写作指南** 附录
   风格词汇、流派/乐器参考和提示结构的文档。
   **API 提示应始终用英文书写**以获得最佳生成质量，
   无论用户的语言如何。
   
遵循以下模式：
   ```
   A [mood] [BPM optional] [genre] song, featuring [vocal description],
   about [narrative/theme], [atmosphere], [key instruments and production].
   ```

2. **在生成之前向用户显示预览**。翻译所有标签和提示
   描述成用户的语言。英文提示仅在内部使用时
   调用 API — 用户永远不应该看到它。示例模板（英文参考 —
   在运行时本地化所有内容）：

   ```
   About to generate:
   Type: Vocal / Instrumental
   Description: indie folk, melancholy, acoustic guitar, gentle female voice
   Lyrics: Auto-generated (--lyrics-optimizer)
   
   Confirm? (press enter to confirm, or tell me what to change)
   ```

3. **调用mmx**：直接生成音乐。

---

### 步骤 2：高级控制模式

**目标**：用户在生成之前可以完全控制每个参数。

1. **歌词阶段**：
   - 如果用户提供歌词：使用部分标记显示它们的格式，要求编辑。
     最终歌词将通过`--lyrics`传递给mmx。
   - 如果用户有主题但没有歌词：将使用 `--lyrics-optimizer` 自动生成。
   - 支持迭代编辑：“更改第二个合唱”->仅重写该部分。
   - 用户也可以自己写歌词并通过`--lyrics`传递。

2. **提示阶段**：
   - 根据歌词的情绪和内容生成推荐提示。
   - 将其呈现为用户可以添加/删除/修改的可编辑标签。
   - 请参阅 **即时写作指南** 附录了解完整词汇。

3. **提前规划**（可选，提供但不强迫）：
   - 歌曲结构：主歌-副歌-主歌-副歌-桥段-副歌或自定义
   - BPM 建议（在提示中编码为节奏描述符）
   - 参考风格：“类似于 X 风格” -> 映射到提示标签
   - 声音角色描述

4. **最终确认**：显示完整的参数摘要，然后生成。

---

### 第 3 步：致电 mmx

使用 mmx CLI 生成音乐：

**带有自动生成歌词的声音：**
```bash
mmx music generate \
  --prompt "<prompt>" \
  --lyrics-optimizer \
  --genre "<genre>" --mood "<mood>" --vocals "<vocal style>" \
  --instruments "<instruments>" --bpm <bpm> \
  --out ~/Music/minimax-gen/<filename>.mp3 \
  --quiet --non-interactive
```

**人声与用户提供的歌词：**
```bash
mmx music generate \
  --prompt "<prompt>" \
  --lyrics "<lyrics with section markers>" \
  --genre "<genre>" --mood "<mood>" --vocals "<vocal style>" \
  --out ~/Music/minimax-gen/<filename>.mp3 \
  --quiet --non-interactive
```

**器乐（无声乐）：**
```bash
mmx music generate \
  --prompt "<prompt>" \
  --instrumental \
  --genre "<genre>" --mood "<mood>" --instruments "<instruments>" \
  --out ~/Music/minimax-gen/<filename>.mp3 \
  --quiet --non-interactive
```

使用结构化标志（`--genre`、`--mood`、`--vocals`、`--instruments`、`--bpm`、`--key`、
`--tempo`、`--structure`、`--references`、`--avoid`、`--use-case`) 提供 API
细粒度的控制，而不是将所有内容都塞进 `--prompt` 中。

等待时显示进度指示器。一般生成需要 30-120 秒。

---

### 第 4 步：回放

生成后，检测可用的音频播放器并播放文件。

**检测玩家：**
```bash
command -v mpv || command -v ffplay || command -v afplay
```

**根据检测到的玩家进行游戏（按优先顺序）：**

|玩家|命令 |控制|
|--------|---------|----------|
| `mpv`（首选）| `mpv --no-video ~/Music/minimax-gen/<filename>.mp3` |空格 = 暂停/恢复，q = 退出，左/右 = 查找 |
| `ffplay` | `ffplay -nodisp -autoexit ~/Music/minimax-gen/<filename>.mp3` | q = 退出 |
| `afplay` (macOS) | `afplay ~/Music/minimax-gen/<filename>.mp3` | Ctrl+C = 停止 |
|没有找到 |请勿尝试播放 |仅显示文件路径 |

开始播放后，告诉用户（本地化所有文本）：

```
Now playing: <filename>.mp3
Saved to: ~/Music/minimax-gen/<filename>.mp3
```

不显示播放控件（例如键盘快捷键）——它们在此不起作用
环境，因为播放器在后台运行。

如果没有找到玩家（本地化所有文本）：

```
No audio player detected.
File saved to: ~/Music/minimax-gen/<filename>.mp3
Tip: Install mpv for the best playback experience (brew install mpv).
```

---

### 第 5 步：反馈和迭代

播放完毕后，请求反馈：

```
How was this song?
  1. Love it, keep it!
  2. Not quite, adjust and regenerate
  3. Fine-tune lyrics/style then regenerate
  4. Don't want it, start over
```

根据反馈：
- **满意**：完成。再次提及文件路径。
- **调整和重新生成**：询问要更改什么（提示？歌词？风格？），应用编辑，
  重新运行生成。保留带有 `_v1` 后缀的旧文件以进行比较。
- **微调**：进入高级控制模式并预先填充当前参数。
- **删除并重新启动**：删除文件，返回步骤0。

---

## 封面模式

根据参考音频生成歌曲的翻唱版本。型号：`music-cover-free`。

**参考音频要求**：mp3、wav、flac — 持续时间 6 秒至 6 分钟，最大 50MB。
如果未提供歌词，则会通过 ASR 自动提取原始歌词。

### 工作流程

当用户选择封面模式时：
1. 请求源音频 — 本地文件路径或 URL
2. 询问目标翻唱风格（例如“原声翻唱、精简、亲密的声音”）
3. 可选择要求自定义歌词或歌词文件

### 命令

**从本地文件覆盖：**
```bash
mmx music cover \
  --prompt "<cover style description>" \
  --audio-file <source.mp3> \
  --out ~/Music/minimax-gen/<filename>.mp3 \
  --quiet --non-interactive
```

**封面来自网址：**
```bash
mmx music cover \
  --prompt "<cover style description>" \
  --audio <source_url> \
  --out ~/Music/minimax-gen/<filename>.mp3 \
  --quiet --non-interactive
```

**带有自定义歌词（文本）：**
```bash
mmx music cover \
  --prompt "<style>" \
  --audio-file <source.mp3> \
  --lyrics "<custom lyrics>" \
  --out ~/Music/minimax-gen/<filename>.mp3 \
  --quiet --non-interactive
```

**带有自定义歌词（文件）：**
```bash
mmx music cover \
  --prompt "<style>" \
  --audio-file <source.mp3> \
  --lyrics-file <lyrics.txt> \
  --out ~/Music/minimax-gen/<filename>.mp3 \
  --quiet --non-interactive
```

### 可选标志

|旗帜|描述 |
|------|-------------|
| `--seed <number>` |随机种子 0-1000000 可重现结果 |
| `--channel <n>` | `1`（单声道）或 `2`（立体声，默认）|
| `--format <fmt>` | `mp3`（默认）、`wav`、`pcm` |
| `--sample-rate <hz>` |采样率（默认：44100）|
| `--bitrate <bps>` |比特率（默认：256000）|

### 生成后
继续正常播放和反馈流程（步骤 4 和 5）。

---

## 错误处理

|错误 |行动|
|--------|--------|
|未找到 mmx | `npm install -g mmx-cli` |
| mmx 身份验证错误（退出代码 3）| `mmx auth login` |
|超出配额（退出代码 4）|报告配额限制，建议等待或升级 |
| API 超时（退出代码 5）|重试一次，然后报告失败 |
|内容过滤器（退出代码 10）|调整提示以避免过滤内容 |
|歌词格式无效 |自动修复部分标记，警告用户 |
|找不到音频播放器 |保存文件并告诉用户路径，建议安装mpv |
|网络错误 |显示错误详细信息，建议检查连接 |

---

## 重要提示

- **绝不复制受版权保护的歌词。** 翻唱时，一定要写原创歌词
  受到歌曲主题的启发。向用户解释这一点。
- **提示语言**：API 提示最适合使用英文标签。还有中文标签
  可以接受。混合就可以了。
- **歌词中的部分标记**：API 识别 `[verse]`、`[chorus]`、`[bridge]`、
  `[outro]`、`[intro]`。提供 `--lyrics` 时始终包含它们。
- **文件管理**：如果`~/Music/minimax-gen/`有超过50个文件，建议清理
  开始新会话时。
- **结构化参数**：优先使用 `--genre`、`--mood`、`--vocals`、`--instruments`、
  `--bpm` 等将所有内容嵌入 `--prompt` 中。这为 API 提供了更好的控制。
- **歌词语言通过风格**：当用户想要特定语言的歌词时，表达
  通过声音描述或流派（例如“日本女歌手”、“华语流行音乐”）
  民谣”）而不是在提示中附加语言指令。

---

## 附录：提示写作指南

请参阅 [references/prompt_guide.md](references/prompt_guide.md) 获取完整的提示编写指南，
包括流派/声乐/乐器参考和 BPM 表。
