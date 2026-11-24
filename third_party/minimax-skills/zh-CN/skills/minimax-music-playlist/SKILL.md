---
name: minimax-music-playlist
description: >
  Generate personalized music playlists by analyzing the user's music taste
  and generation feedback history. Triggers
  on any request involving playlist generation, music taste profiling, or personalized
  music recommendations. Supports multilingual triggers — match equivalent phrases in
  any language.
license: MIT
metadata:
  version: "2.0"
  category: creative
---

# MiniMax 音乐播放列表 — 个性化播放列表生成器

扫描用户的音乐品味，构建品味档案，生成个性化音乐
播放列表，并创建专辑封面。该技能是为代理人和直接人员设计的
用户调用——根据上下文调整交互风格。

## 先决条件

- **mmx CLI** — 音乐和图像生成。安装：`npm install -g mmx-cli`。授权：`mmx auth login --api-key <key>`。
- **Python 3** — 用于扫描您即时编写的脚本（仅限 stdlib，无 pip）。
- **音频播放器** — `mpv`、`ffplay` 或 `afplay`（macOS 内置）。

＃＃ 语言

从用户的消息中检测用户的语言。 **所有面向用户的文本必须是
使用与用户提示相同的语言** — 不要混合语言。如果用户
用中文编写，所有输出（简介摘要、主题建议、播放列表计划、
播放信息）必须为全中文。如果是英文，就全英文。

为了获得最佳质量，所有 `mmx` 生成提示都应为英文。
每首歌曲的歌词语言均遵循其流派（K-pop → 韩语、J-pop → 日语等），
不是用户的 UI 语言。

---

## 工作流程

```
1. Scan local music apps → 2. Build taste profile → 3. Plan playlist
→ 4. Generate songs (mmx music) → 5. Generate cover (mmx image) → 6. Play → 7. Save & feedback
```

---

## 第 1 步：收集音乐收听数据

从可用来源收集用户的收听数据。

**支持的来源：**

|来源 |方法|数据格式|
|--------|--------|-------------|
|苹果音乐| `osascript` 查询Music.app（官方AppleScript接口）|曲目名称、艺术家、专辑、流派、播放次数 |
| Spotify |用户通过 [Spotify 隐私设置](https://www.spotify.com/account/privacy/) | 导出自己的数据ZIP 中的 JSON 文件 (`Streaming_History_Audio_*.json`) |
|手动输入|用户直接描述他们的口味 |自由文本 |

**Spotify 数据导出流程：**
Spotify 不会在本地存储有用的数据。要包含 Spotify 收听历史记录，
首先检查用户是否已经有 Spotify 数据导出：

1. 搜索现有导出：`find ~ -maxdepth 4 -name "my_spotify_data.zip" -o -name "Streaming_History_Audio_*.json" 2>/dev/null`
2. 如果找到，询问用户是否要使用
3.如果是ZIP，解压并找到`Spotify Extended Streaming History/Streaming_History_Audio_*.json`
4.如果没有找到，请打开Spotify隐私页面：`open https://www.spotify.com/account/privacy/`
5. 告诉用户登录，滚动到“下载您的数据”，然后单击“请求数据”
6. 暂时跳过 Spotify，继续使用其他来源——告诉用户他们可以
   数据导出到达后（通常是几天）重新运行播放列表技能

**Spotify 数据格式：**
导出包含 `Streaming_History_Audio_YYYY.json` 文件（每年一个），每个
是监听事件的 JSON 数组。要提取的关键字段：
- `master_metadata_album_artist_name` — 艺术家姓名
- `master_metadata_track_name` — 曲目名称
- `master_metadata_album_album_name` — 专辑名称
- `ms_played` — 播放持续时间（以毫秒为单位）（用作权重：更长 = 信号更强）
- `ts` — 时间戳

过滤掉 `ms_played < 30000` 的条目（少于 30 秒，可能被跳过）。
请勿使用或存储 `ip_addr` 或其他敏感字段。

**从每个来源中提取什么：**
- 曲目名称 + 艺术家姓名（主要信号）
- 播放列表名称和成员资格（例如，名为“繁体中文”的播放列表会告诉您流派偏好）
- 播放计数或流媒体持续时间（如果可用）（经常播放的曲目的权重更高）
- 场景/情绪标签（如果有）

**方法：**
1.检查Apple Music是否可用（尝试`osascript`查询）
2.询问用户是否有Spotify数据导出ZIP提供
3. 如果没有可用的来源，请用户手动描述他们的口味

**隐私规则：** 切勿向用户显示原始曲目列表。仅显示汇总统计数据。

---

## 第 2 步：建立品味档案

根据扫描的数据，建立一个口味档案，涵盖：

- **流派分布** — 用户听什么风格（例如，J-pop 20%、R&B 15%、Classical 10%）
- **情绪倾向** — 情绪基调偏好（忧郁、精力充沛、平静、浪漫等）
- **声音偏好** — 男性与女性声音比例
- **节奏偏好** — 慢速/中速/乐观/快速分布
- **语言分布** — zh、en、ja、ko 等。
- **顶级艺术家** - 最受聆听的艺术家

**如何从艺术家姓名推断流派/情绪：**
大多数原始数据只有艺术家+曲目名称，没有流派标签。为了丰富这一点：
1. 在 `<SKILL_DIR>/data/artist_genre_map.json` 的本地映射表中查找艺术家
   — 此表涵盖了 20,000 名流行艺术家，具有预先映射的流派、声音类型和语言
2.对于不在映射表中的艺术家，查询MusicBrainz API：
   ZZ保留1ZZ
   — 从响应中提取流派标签；遵守速率限制（1 请求/秒）
   — 将结果缓存到 `<SKILL_DIR>/data/artist_cache.json` 以避免重新查询
3.如果MusicBrainz没有返回结果，则跳过该艺术家

**配置文件缓存：**
- 将配置文件保存到`<SKILL_DIR>/data/taste_profile.json`
- 如果存在少于 7 天的配置文件，请重复使用它（提供重新扫描选项）
- 如果较旧或丢失，请重建

**向用户显示摘要：**
```
Your Music Profile:
  Sources: Apple Music 230 | Spotify 140
  Genres: J-pop 20% | R&B 15% | Classical 10% | Indie Pop 9%
  Moods: Melancholic 25% | Calm 20% | Romantic 18%
  Vocals: Female 65% | Male 35%
  Top artists: Faye Wong, Ryuichi Sakamoto, Taylor Swift, Jay Chou, Taeko Onuki
```

如果由具有明确参数的代理调用，请跳过确认并继续。
如果由用户直接调用，请在继续之前询问配置文件是否正确。

---

## 第 3 步：计划播放列表

**在生成之前询问用户主题/场景。**这就是
工作流程中的交互步骤。所有其他步骤均自主运行。

如果调用中已提供主题（例如，代理或用户
说“生成一个深夜寒冷的播放列表”），直接使用它并跳过该问题。
否则，请询问：

```
What theme would you like for your playlist? Here are some suggestions:

- "Late night chill" — relaxing slow songs
- "Commute" — upbeat and energizing
- "Rainy day" — melancholic & cozy
- "Surprise me" — random based on your taste

Or tell me your own vibe!
```

一旦用户选择了一个主题，就会自动进行生成、封面、
播放和保存——无需进一步确认。

确定播放列表参数：
- **主题/情绪** — 来自用户输入，或默认为个人资料中的最高情绪
- **歌曲数** — 来自用户输入，或默认为 5
- **流派组合** — 按个人资料加权，具有多样性

**每首歌的歌词语言**遵循流派：

|类型 |歌词语言 |
|--------|----------------|
|韩国流行音乐、韩国 R&B/民谣 |韩语 |
| J-pop、城市流行、J-rock |日语 |
|华语流行、中国流行、华语流行 |中文 |
|西方流行/独立/摇滚/爵士/R&B |英语 |
|拉丁流行音乐、巴萨诺瓦 |西班牙语/葡萄牙语 |
|器乐、低保真、环境 |没有歌词（`--instrumental`）|

通过语音描述将语言自然地嵌入到 mmx 提示中：
- 好：`"A melancholy Chinese R&B ballad with a gentle introspective male voice, electric piano, bass, slow tempo"`
- 坏：`"R&B ballad, melancholy... sung in Chinese"`

**生成前显示播放列表计划。**用两行显示每首歌曲：
第一行显示流派、情绪和声音/语言标签；第二行显示
这首歌的简短描述。 **所有面向用户的文本（计划、描述、心情、
标签）必须与用户提示的语言相同。** 仅实际的 `--prompt`
传递给 `mmx` 的应该是英文——这是内部的，不应该显示给
用户。例子：

```
Playlist Plan: Late Night Chill (5 songs)

1. Neo-soul R&B — introspective  English/male vocal
   A mellow neo-soul R&B ballad with warm baritone, electric piano, smooth bass

2. Lo-fi hip-hop — dreamy  Instrumental
   Dreamy lo-fi with sampled piano, vinyl crackle, soft electronic drums

3. Smooth jazz — romantic  English/female vocal
   Silky female voice, saxophone, piano, romantic starlit night

4. Indie folk — melancholic  English/male vocal
   Tender male voice, acoustic guitar, harmonica, quiet solitude

5. Ambient electronic — calm  Instrumental
   Soft synth pads, gentle arpeggios, dreamy atmosphere
```

显示计划后，直接进行生成——无需确认。
用户已经选择了主题；该计划的显示是为了透明度，而不是为了批准。

---

## 步骤 4：生成歌曲

使用 `mmx music generate` 创建所有歌曲。 **同时生成**（最多 5 个并行）。

```bash
# Example: 5 songs in parallel
mmx music generate --prompt "<english_prompt_1>" --lyrics-optimizer \
  --out ~/Music/minimax-gen/playlists/<name>/01_desc.mp3 --quiet --non-interactive &
mmx music generate --prompt "<english_prompt_2>" --instrumental \
  --out ~/Music/minimax-gen/playlists/<name>/02_desc.mp3 --quiet --non-interactive &
# ... more songs ...
wait
```

**关键标志：**
- `--lyrics-optimizer` — 根据提示自动生成歌词（用于声乐曲目）
- `--instrumental` — 没有人声
- `--vocals "<description>"` — 声音风格（例如“温暖的中国男中音”）
- `--genre`、`--mood`、`--tempo`、`--instruments` — 细粒度控制
- `--quiet --non-interactive` — 抑制批处理模式的交互式输出
- `--out <path>` — 保存到文件

**文件命名：** `<NN>_<short_desc>.mp3`（例如，`01_rnb_midnight.mp3`）

**输出目录：** `~/Music/minimax-gen/playlists/<playlist_name>/`

如果歌曲失败，请在跳过之前**重试一次**。记录错误并继续其余部分。

---

## 步骤 5：生成专辑封面

**与歌曲同时生成专辑封面**（步骤 4），而不是之后。
与歌曲生成调用并行启动 `mmx image generate` 调用。

制作反映播放列表主题、情绪和流派组合的提示。图像
感觉应该像一张专辑封面——艺术性的、令人回味的，而不是字面上的。

```bash
mmx image generate \
  --prompt "<cover description based on playlist theme and mood>" \
  --aspect-ratio 1:1 \
  --out-dir ~/Music/minimax-gen/playlists/<playlist_name>/ \
  --out-prefix cover \
  --quiet
```

**及时指导：**
- 抽象/艺术风格最适合专辑封面
- 参考主导情绪和流派（例如，“梦幻般的深夜城市景观、霓虹灯反射、低保真美学”）
- 请勿在图像提示中包含文本或歌曲标题
- 长宽比应为 1:1（正方形，标准专辑封面）

---

## 第 6 步：回放

检测可用的播放器并按顺序播放播放列表：

|玩家|命令 |控制|
|--------|---------|----------|
|多用途车 | `mpv --no-video <file>` | `q` 跳过，空格暂停，箭头寻找 |
| ffplay | `ffplay -nodisp -autoexit <file>` | `q` 跳过 |
| AFPLAY | `afplay <file>` | Ctrl+C 跳过 |

按文件名顺序播放播放列表目录中的所有 `.mp3` 文件。
仅播放此会话中生成的歌曲 - 如果目录中有旧文件
从以前的运行中，首先清除它们或按已知文件名进行过滤。
如果没有找到播放器，则仅显示文件路径。

---

## 步骤 7：保存并反馈

将播放列表元数据保存到 `<playlist_dir>/playlist.json`：
```json
{
  "name": "Late Night Chill",
  "theme": "late night chill",
  "created_at": "2026-04-11T22:00:00",
  "song_count": 5,
  "cover": "cover_001.png",
  "songs": [
    {"index": 1, "filename": "01_rnb_midnight.mp3", "prompt": "...", "rating": null}
  ]
}
```

如果用户在场，请请求反馈（每首歌曲或整体）。更新
品味档案的反馈部分包含喜欢/不喜欢的类型和提示
改进未来的播放列表。

---

## 重播播放列表

如果要求播放上一个播放列表：`ls ~/Music/minimax-gen/playlists/`，则显示
可用的，然后播放所选的一个。

---

## 注释

- **代理与用户调用**：主题/场景问题（步骤 3）是单一的
  互动接触点。如果调用中已提供主题，
  跳过这个问题。其他一切都自主运行。
- **无硬编码脚本**：根据需要即时编写扫描/分析脚本。
  仅使用 Python stdlib。缓存结果以避免冗余工作。
- **技能目录**：`<SKILL_DIR>` = 包含此 SKILL.md 文件的目录。
  数据/缓存文件位于 `<SKILL_DIR>/data/` 中。
- **所有 mmx 均以英语提示**，以获得最佳生成质量。
