---
name: vision-analysis
description: >
  Analyze, describe, and extract information from images using the MiniMax vision MCP tool.
  Use when: user shares an image file path or URL (any message containing .jpg, .jpeg, .png,
  .gif, .webp, .bmp, or .svg file extension) or uses any of these words/phrases near an image:
  "analyze", "analyse", "describe", "explain", "understand", "look at", "review",
  "extract text", "OCR", "what is in", "what's in", "read this image", "see this image",
  "tell me about", "explain this", "interpret this", in connection with an image, screenshot,
  diagram, chart, mockup, wireframe, or photo.
  Also triggers for: UI mockup review, wireframe analysis, design critique, data extraction
  from charts, object detection, person/animal/activity identification.
  Triggers: any message with an image file extension (jpg, jpeg, png, gif, webp, bmp, svg),
  or any request to analyze/describ/understand/review/extract text from an image, screenshot,
  diagram, chart, photo, mockup, or wireframe.
license: MIT
metadata:
  version: "1.0"
  category: ai-vision
  sources:
    - MiniMax Token Plan MCP (understand_image tool)
---

# 视觉分析

使用 MiniMax 代币计划中提供的 MiniMax `MiniMax_understand_image` MCP 工具分析图像。

## 先决条件

- 具有有效 `MINIMAX_API_KEY` 的 MiniMax 代币计划订阅
- 配置了 MiniMax MCP（可用 `MiniMax_understand_image` 工具）

### 如果未配置 MCP 工具

**步骤 1：** 代理应从以下位置获取设置指令：
**ZZ保留0ZZ

**第2步：**检测用户的环境（OpenCode、Cursor、Claude Code等）并输出所需的确切命令。常见示例：

**OpenCode** — 添加到 `~/.config/opencode/opencode.json` 或 `package.json`：
```json
{
  "mcp": {
    "MiniMax": {
      "type": "local",
      "command": ["uvx", "minimax-coding-plan-mcp", "-y"],
      "environment": {
        "MINIMAX_API_KEY": "YOUR_TOKEN_PLAN_KEY",
        "MINIMAX_API_HOST": "https://api.minimaxi.com"
      },
      "enabled": true
    }
  }
}
```

**克劳德代码**：
```bash
claude mcp add -s user MiniMax --env MINIMAX_API_KEY=your-key --env MINIMAX_API_HOST=https://api.minimaxi.com -- uvx minimax-coding-plan-mcp -y
```

**光标** — 添加到 MCP 设置：
```json
{
  "mcpServers": {
    "MiniMax": {
      "command": "uvx",
      "args": ["minimax-coding-plan-mcp"],
      "env": {
        "MINIMAX_API_KEY": "your-key",
        "MINIMAX_API_HOST": "https://api.minimaxi.com"
      }
    }
  }
}
```

**步骤 3：** 配置后，告诉用户重新启动应用程序并使用 `/mcp` 进行验证。

**重要提示：** 如果用户没有 MiniMax 令牌计划订阅，请告知他们 `understand_image` 工具需要订阅 - 它不能与免费或其他层 API 密钥一起使用。

## 分析模式

|模式|何时使用 |即时策略|
|---|---|---|
| `describe` |一般图像理解 |求详细说明 |
| `ocr` |从屏幕截图、文档中提取文本 |要求逐字提取所有文本 |
| `ui-review` | UI 模型、线框图、设计文件 |寻求设计评论和建议 |
| `chart-data` |图表、图形、数据可视化 |要求提取数据点和趋势 |
| `object-detect` |识别物体、人、活动 |要求列出并找到所有元素 |

## 工作流程

### 第 1 步：自动检测图像

当消息包含图像文件路径或带有扩展名的 URL 时，该技能会自动触发：
`.jpg`、`.jpeg`、`.png`、`.gif`、`.webp`、`.bmp`、`.svg`

从消息中提取图像路径。

### 步骤2：选择分析模式并调用MCP工具

使用带有特定于模式的提示的 `MiniMax_understand_image` 工具：

**描述：**
```
Provide a detailed description of this image. Include: main subject, setting/background,
colors/style, any text visible, notable objects, and overall composition.
```

**OCR：**
```
Extract all text visible in this image verbatim. Preserve structure and formatting
(headers, lists, columns). If no text is found, say so.
```

**用户界面评论：**
```
You are a UI/UX design reviewer. Analyze this interface mockup or design. Provide:
(1) Strengths — what works well, (2) Issues — usability or design problems,
(3) Specific, actionable suggestions for improvement. Be constructive and detailed.
```

**图表数据：**
```
Extract all data from this chart or graph. List: chart title, axis labels, all
data points/series with values if readable, and a brief summary of the trend.
```

**物体检测：**
```
List all distinct objects, people, and activities you can identify. For each,
describe what it is and its approximate location in the image.
```

### 第 3 步：展示结果

清晰返回分析。对于 `describe`，请使用可读的散文。对于 `ocr`，保留结构。对于 `ui-review`，请使用结构化批评格式。

## 输出格式示例

对于描述模式：
```
## Image Description

[Detailed description of the image contents...]
```

对于ocr模式：
```
## Extracted Text

[Preserved text structure from the image]
```

对于 ui-review 模式：
```
## UI Design Review

### Strengths
- ...

### Issues
- ...

### Suggestions
- ...
```

## 注释

- 支持最大 20MB 的图像（JPEG、PNG、GIF、WebP）
- 如果 MiniMax MCP 配置了文件访问，则本地文件路径有效
- `MiniMax_understand_image`工具由`minimax-coding-plan-mcp`包提供
