---
name: buddy-sings
description: >
  Use when user wants their Claude Code pet (/buddy) to sing a song. Triggers on any
  request that combines the concept of their Claude Code buddy, pet, or companion with
  singing or music. Supports multilingual triggers — match equivalent phrases in any
  language.
license: MIT
metadata:
  version: "1.1"
  category: creative
---

# Buddy Sings — 让您的 Claude Code 宠物唱歌

将您的克劳德·科德宠物变成歌手。每只宠物都有独特的声音身份
根据它的名字和个性——同一个宠物听起来总是一样的。

## 先决条件

- **mmx CLI**（音乐生成所需）：

**安装：**
  ```bash
  npm install -g mmx-cli
  ```

**验证（仅限第一次）：**
  ```bash
  mmx auth login --api-key <your-minimax-api-key>
  ```
从 [MiniMax Platform](https://platform.minimaxi.com/) 获取您的 API 密钥。

- **音频播放器**（用于播放 - 至少其中之一）：
  - `mpv`（推荐 - 交互式控制：空格 = 暂停，q = 退出）
  - `ffplay`（来自 FFmpeg）
  - `afplay`（macOS内置）

---

## 工作流程概述

```
Check pet → Build vocal identity → Gather context → Generate music → Play & feedback
```

---

## 语言与互动

从用户的第一条消息中检测用户的语言。用同一种语言回应
整个会议期间。下面的所有例子都是英文的——翻译一下
用其他语言回应时很自然。

**面向用户的文本本地化规则**：
- 向用户显示的所有文本 - 包括宠物信息、语音描述、歌词预览、
  提示预览、播放信息和反馈提示——必须完全翻译成
  用户的语言。
- 发送到模型的 **API 提示** 应始终以英文书写以获得最佳效果
  一代品质。但是，在向用户预览提示时，显示本地化的
  使用用户语言的描述而不是原始的英语提示。英文提示
  是一个内部实现细节——用户不需要看到它。
- 以下模板是用英文编写的，仅供参考。在运行时，翻译每个
  将标签和消息转换为用户检测到的语言。

默认情况下，宠物会用用户的语言唱歌。嵌入歌唱语言
自然地出现在声音描述中（例如，“用日语唱歌”或“用日语唱歌”）
普通话”）而不是附加单独的语言标签。如果用户
明确要求歌词使用不同的语言，请尊重该要求。

---

## 第 1 步：检查是否有宠物

读取 `~/.claude.json` 并查找 `companion` 字段。

如果未找到同伴或该字段为空，则告诉用户：

```
You don't have a pet yet! Type /buddy to adopt one, then come back to let it sing.
```

停在这里等待用户领养宠物。请勿在没有宠物的情况下继续前行。

如果存在同伴，则提取其配置文件：
- `name` — 宠物的名字
- `personality` — 宠物的性格描述

将宠物呈现给用户：

```
Found your pet!
   Name: <name>
   Personality: <personality>
```

---

## 第 2 步：建立声音认同

根据宠物的**名字**和**性格**文字，创造性地设计出独特的
声音身份。无需模板查找——自由诠释个性。

### 如何将个性诠释成声音

阅读个性文本并制作声音属性：

- **音色**：这个个性听起来是什么样的？例如，“几句话”→
  低沉、温暖、刻意； “精力充沛”→ 明亮、有力； “神秘”→呼吸，
  黑暗； “传奇的chonk”→厚重、温暖、舒适
- **歌唱风格**：他们会如何演唱歌曲？例如，“几句话”→
  稀疏的、戏剧性的停顿； “俏皮的”→有弹性的，有节奏的； “诗意” → 流畅、连奏
- **情绪**：什么情绪基调适合？例如，“chill” → 放松、悠闲；
  “激烈”→激烈，有力

构造一个用英语描述声音风格的 `prompt_fragment`，嵌入
歌唱语言自然。例如：

```
Vocal: warm low female voice singing in Mandarin Chinese with cozy thick timbre,
sparse minimalist delivery with dramatic pauses giving each word weight, relaxed
laid-back mood.
```

### 语音缓存

声音身份必须被**缓存**，以便宠物的声音始终相同。

- 缓存文件：`~/.claude/skills/buddy-sings/voices/<name>.json`
- 缓存格式：
  ```json
  {
    "name": "Moth",
    "personality": "A legendary chonk of few words.",
    "prompt_fragment": "Vocal: warm low female voice singing in Mandarin Chinese...",
    "cached_at": "2026-04-07T19:52:15"
  }
  ```

**第一次**：不存在缓存→解释个性→保存到缓存文件。

**后续调用**：读取缓存→直接使用保存的`prompt_fragment`。
不要重新解释——一致性很重要。

**缓存失效**：如果`~/.claude.json`中的`personality`与
已缓存，宠物已更改 - 重新生成并保存新的缓存。

**手动再生**：如果用户说“更改语音”或“重新生成语音”：
删除缓存文件并从头开始重新解释。

### 向用户呈现声音

```
<name>'s unique voice:

Timbre: <timbre description>
Style: <style description>
Mood: <mood description>

Let's pick what <name> should sing about!
```

---

## 步骤 3：理解意图并收集背景

**不要总是呈现模式菜单。** 相反，分析用户的请求
确定需要什么上下文，并自动收集它。

### 自动上下文检测

当用户的请求暗示个人上下文时，**自动**扫描
无需询问相关信息。触发因素包括：

- **基于时间的参考**：“今天”、“本周”、“最近”、“昨天”→ 扫描
  当前对话历史记录和该时期发生的事情的记忆文件
- **个人参考**：“我的工作”、“我的一天”、“我做了什么”→扫描记忆
  和用户活动的对话
- **关系参考**：“我们的故事”、“我们一起做了什么”→ 扫描记忆
  用户和宠物/克劳德之间的共享经验

### 上下文收集（自动，非模式门控）

当需要上下文时，请按顺序扫描这些来源：

1. **当前对话上下文**：查看用户在做什么
   此克劳德代码会话 - 编辑文件、运行命令、讨论主题。
   这是“今天”类型请求的最丰富的来源。

2. **内存文件**：扫描相关内存：
   ```bash
   find ~/.claude/projects/*/memory/ -name "*.md" 2>/dev/null | head -20
   ```
还要检查 `~/.claude/memory/` 是否存在。
   读取找到的文件并提取与用户请求相关的主题。

3. **Git 历史记录**（如果在存储库中）：对于与工作相关的歌曲，请检查最近的提交：
   ```bash
   git log --oneline --since="today" 2>/dev/null | head -10
   ```

使用收集到的上下文来丰富歌词提示——使歌曲变得个性化和
具体到实际发生的事情，而不是通用的。

### 当不需要上下文时

如果用户的请求是一个清晰的独立场景（例如“唱一首雨天的歌”，
“唱摇篮曲”），跳过上下文收集并直接进行音乐生成。

### 当上下文不明确时

仅当您确实无法确定用户想要什么时才要求澄清。
不要显示模式菜单 - 提出一个具体问题：

```
What should <name> sing about?

For example:
  - "Today's work" — I'll check what you've been up to
  - "My pet waiting by the window for me to come home"
  - Or let me pick a random theme?
```

### 回退到随机

如果上下文收集没有发现任何有用的东西（没有内存文件，没有对话
历史，没有 git 日志），回退到基于宠物的随机主题生成
个性：
- 安静/内敛的性格→午夜摇篮曲、温柔的日落、安静的早晨
- 精力充沛的个性→派对即兴演奏、冒险歌曲、胜利进行曲
- 神秘个性→月夜小夜曲、秘密低语、梦幻之旅

告诉用户选择了什么主题。

---

## 步骤 4：生成音乐

将声音特征与所选主题相结合。

1. **构建完整的提示**：提示有两个部分必须同时存在：

**A 部分 — 声音识别（必须首先出现）**：始终以
   缓存`prompt_fragment`。这是最重要的部分——它定义了谁是
   唱歌。将其放在提示的开头，以便 API 对其进行优先级排序。

**B 部分 - 流派/风格/情绪标签**：选择**匹配主题**的标签，而不是
   一个默认设置。根据歌曲的内容有意改变流派。

将提示写成**生动的英语句子**，而不是逗号分隔的标签。
   遵循以下模式：“一首[心情][流派]歌曲，以[声音描述]为特色，
   关于[叙事/主题]、[氛围]、[主要乐器和制作]。`
   将声音描述为一个角色（“带有爵士乐变化的性感男中音”），
   不仅仅是性别。包括一个场景或氛围来锚定这一代人。

**类型匹配指南** — 选择适合主题能量的类型：

|主题能量|推荐类型 |避免 |
   |------------|-----------------|--------|
   |鼓励/激励/欢呼|独立摇滚、合成流行音乐、放克、说唱 |独立民谣，治愈 |
   |日常生活/温暖/陪伴|华语流行音乐、城市流行音乐、巴萨诺瓦 |和上次一样|
   |想念某人/等待|民谣、R&B、低保真 |摇滚、电子舞曲 |
   |幽默/吐槽/抱怨|放克、说唱、斯卡、电子流行 |古典、民谣|
   |深夜/安静|氛围、钢琴曲、低保真、新古典主义 |欢快的电子舞曲 |
   |庆典/成就| EDM、未来贝斯、放克、韩国流行音乐 |缓慢的节奏，忧郁|
   |工作常规|城市流行音乐、合成流行音乐、低保真嘻哈音乐、独立摇滚 |每次都是同一类型 |

**反单调规则**：切勿连续两次使用相同的类型组合。
   在构建提示之前，回想一下之前使用的是什么类型
   一代（如果本次会议中有的话）并选择不同的东西。

**提示结构**——写成生动的英语句子，而不是逗号分隔的标签：
   ```
   <vocal prompt_fragment>. A <genre> song with <mood> mood, featuring <instruments>,
   at a <tempo> tempo, evoking <scene>.
   ```

**不同的例子**：
   ```
   # Encouragement for the workday
   A deep warm androgynous voice with cozy delivery. An energetic synth-pop track
   with a fiery, uplifting mood, driven by pulsing synthesizers and electronic drums
   at a fast tempo, capturing the rush of a morning commute.

   # Waiting for the owner to come home
   A deep warm androgynous voice with cozy delivery. A warm city pop song with sweet,
   tender feelings, featuring electric piano and groovy bass at a mid-tempo pace,
   set on a sunny afternoon windowsill waiting for someone to come home.

   # Complaining about overtime
   A deep warm androgynous voice with cozy delivery. A playful funk track with a
   humorous, laid-back vibe, featuring slap bass and brass at a groovy mid-tempo,
   capturing the absurdity of working late in a dim office.

   # Late-night companionship
   A deep warm androgynous voice with cozy delivery. A calm lo-fi hip-hop piece with
   a healing, dreamy atmosphere, featuring sampled piano and soft electronic drums
   at a slow tempo, evoking a quiet late-night desk with warm lamp light.
   ```

2. **生成歌词**：使用`--lyrics-optimizer`自动生成歌词，或者编写歌词
   当你需要控制视角时，你自己。

**重要——观点和个性驱动的歌词**：

宠物是歌手，所以歌词必须以**宠物的第一人称写成
   视角**（“我”=宠物，“你”=所有者/用户）。宠物正在唱歌
   业主。例如：
   - “我坐在门口等你回家”（宠物视角）
   - “醒来吧，我亲爱的人类”（宠物向主人唱歌）
   - 不是“我揉揉困倦的眼睛”（主人的观点 - 错误）
   - 不是“然后你醒了，我的小飞蛾”（主人谈论宠物 - 错误）

宠物的个性应该决定歌词的语气和词语选择：
   - “寥寥数语” → 简短、有影响力的台词、最少的填充物
   - “俏皮” → 押韵、活泼的措辞、有趣的双关语
   - “诗意” → 隐喻丰富，意象流畅
   - “激烈”→直接、有力的宣言

宠物的名字可能会出现在歌词中（例如，在副歌部分），但
   叙事声音始终是宠物说话/唱歌。

**当视角很重要时**：自己写歌词并通过 `--lyrics` 传递。
   **当视角不重要时**：为了方便起见，使用 `--lyrics-optimizer`。

3. **预览（必须显示完整内容）**：在生成之前，向用户展示
   **完整的歌词**和**完整的提示** - 没有缩写，没有`...`，没有摘要。
   这是乐趣的一部分——用户想要先阅读并欣赏歌词
   听到他们唱歌。

API 提示始终以英语构建（以获得最佳生成质量）。
   当以非英语语言回复时，请显示以下内容的**本地化描述**
   为了便于阅读，以用户语言进行提示。英文提示是
   内部实现细节——不向用户显示。全部翻译
   标签（歌手、主题、描述、确认等）转换为用户的语言。

模板（英文参考 — 在运行时本地化所有标签）：

   ```
   About to generate:
   Singer: <name>
   Theme: <theme>

   Lyrics:
   [verse]
   <full verse lyrics here>

   [chorus]
   <full chorus lyrics here>

   ... (show ALL sections in full)

   Description: <localized description of the song style and mood>

   Confirm? (press enter to confirm, or tell me what to change)
   ```

**切勿截断或缩写**预览中的歌词或提示。
   用户应该准确地看到将发送到 API 的内容。

4. **调用音乐生成**：

**带有自动生成的歌词（视角不重要）：**
   ```bash
   mmx music generate \
     --prompt "<full combined prompt>" \
     --lyrics-optimizer \
     --out ~/Music/minimax-gen/<name>_sings_<YYYYMMDD_HHMMSS>.mp3 \
     --quiet --non-interactive
   ```

**附自写歌词（视角控制）：**
   ```bash
   mmx music generate \
     --prompt "<full combined prompt>" \
     --lyrics "<lyrics with correct pet perspective>" \
     --out ~/Music/minimax-gen/<name>_sings_<YYYYMMDD_HHMMSS>.mp3 \
     --quiet --non-interactive
   ```

---

## 第 5 步：播放和反馈

### 跨平台播放

检测可用的音频播放器并播放生成的文件：

```bash
if command -v mpv >/dev/null 2>&1; then
  mpv --no-video ~/Music/minimax-gen/<filename>.mp3
elif command -v ffplay >/dev/null 2>&1; then
  ffplay -nodisp -autoexit ~/Music/minimax-gen/<filename>.mp3
elif command -v afplay >/dev/null 2>&1; then
  afplay ~/Music/minimax-gen/<filename>.mp3
else
  echo "No audio player found. Your song is saved at: ~/Music/minimax-gen/<filename>.mp3"
fi
```

开始播放后，告诉用户文件正在播放以及文件的保存位置。
不显示播放控件（例如键盘快捷键）——它们在此不起作用
环境，因为播放器在后台运行。

如果没有找到播放器，则显示文件路径并建议安装 mpv。

＃＃＃ 反馈

播放后，请求反馈（本地化所有文本）：

```
How was <name>'s performance?

1. Amazing! Keep it!
2. Try a different theme / style
3. Fine-tune the lyrics and regenerate
4. Try another random one
```

---

## 边缘情况

|情况|行动|
|------------|--------|
|没有 `~/.claude.json` |告诉用户先运行`/buddy` |
|同伴字段为空 |相同 — `/buddy` 指南 |
| mmx CLI 未安装 |打印：“您需要安装mmx CLI：`npm install -g mmx-cli && mmx auth login`”|
|找不到音频播放器 |显示文件路径并建议安装 mpv |
|未找到内存文件 |建议自定义主题或随机模式 |
|用户想要改变宠物的声音 |删除缓存，重新诠释个性|
|用户想要特定的类型 |让他们覆盖 - 将他们的流派附加到提示中 |

---

## 注释

- 声音身份仅基于**姓名+个性**。无物种/稀有度
  模板映射。
- 语音被缓存并在会话之间保持一致。相同的宠物=相同的声音。
- 歌词应始终是**原创** — 切勿复制受版权保护的歌词。
- 宠物的个性决定了**声音**（它们的声音）和
  **歌词**（他们说什么以及他们怎么说）。
- 所有生成的文件都转到`~/Music/minimax-gen/`，其中包含宠物名称
  文件名。
