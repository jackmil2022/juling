---
name: slide-making-skill
description: "Implement single-slide PowerPoint pages with PptxGenJS. Use when writing or fixing slide JS files: dimensions, positioning, text/image/chart APIs, styling rules, and export expectations for native .pptx output."
---

# PptxGenJS 幻灯片制作技巧

此技能教授如何使用 PptxGenJS (JavaScript) 生成本机 .pptx 幻灯片。

## PptxGenJS 参考

**阅读 [pptxgenjs.md](pptxgenjs.md) 以获取完整的 PptxGenJS API 参考**，包括：
- 设置和基本结构
- 文本和格式
- 列表和项目符号
- 形状和阴影
- 图像和图标
- 幻灯片背景
- 表格和图表

---

## 字体规则

### 字体系列标准

|语言 |默认 |替代方案|
|----------|---------|--------------|
| **中文** | Microsoft YaHei (微软雅黑) | — |
| **英语** |宋体 |格鲁吉亚、卡利布里、坎布里亚、Trebuchet MS |

```javascript
fontFace: "Microsoft YaHei"  // Chinese text
fontFace: "Arial"            // English text (or approved alternative)
```

使用系统安全字体来实现跨平台兼容性。标题/正文可以使用不同的字体（例如 Georgia + Calibri）。

### 正文没有粗体

**纯文本正文和标题/图例文本不得使用粗体。**

- 正文段落、描述→正常体重
- 标题、图例、脚注 → 正常重量
- 仅对标题和标题保留粗体

```javascript
// ✅ Correct
slide.addText("Main Title", { bold: true, fontSize: 36, fontFace: "Arial" });
slide.addText("Body text here.", { bold: false, fontSize: 14, fontFace: "Arial" });

// ❌ Wrong
slide.addText("Body text here.", { bold: true, fontSize: 14 });
```

---

## 调色板规则（强制）

### 严格遵守调色板

**仅使用提供的调色板。请勿创建或修改颜色。**

- 所有颜色必须来自用户提供的调色板
- 不要使用调色板之外的颜色
- 不要修改调色板颜色（亮度、饱和度、混合）
- **唯一例外**：使用 `transparency` 属性 (0-100) 添加透明度

```javascript
// ✅ Correct: Using palette colors
slide.addShape(pres.shapes.RECTANGLE, { fill: { color: theme.primary } });
slide.addText("Title", { color: theme.accent });

// ❌ Wrong: Colors outside palette
slide.addShape(pres.shapes.RECTANGLE, { fill: { color: "1a1a2e" } });
```

### 无渐变

**禁止使用渐变。仅使用纯色。**

```javascript
// ✅ Correct: Solid colors
slide.background = { color: theme.bg };

// ✅ Correct: Solid + transparency for overlay
slide.addShape(pres.shapes.RECTANGLE, { fill: { color: theme.accent, transparency: 50 } });
```

### 无动画

**禁止动画和过渡。** 所有幻灯片必须是静态的。

---

## 页码徽章（必需）

所有幻灯片**除封面外**必须在右下角包含页码徽章。

- **位置**：x：9.3 英寸，y：5.1 英寸
- 仅显示当前号码（例如 `3` 或 `03`），而不是“3/12”
- 使用调色板颜色，保持微妙

### 圆形徽章（默认）

```javascript
slide.addShape(pres.shapes.OVAL, {
  x: 9.3, y: 5.1, w: 0.4, h: 0.4,
  fill: { color: theme.accent }
});
slide.addText("3", {
  x: 9.3, y: 5.1, w: 0.4, h: 0.4,
  fontSize: 12, fontFace: "Arial",
  color: "FFFFFF", bold: true,
  align: "center", valign: "middle"
});
```

### 药丸徽章

```javascript
slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 9.1, y: 5.15, w: 0.6, h: 0.35,
  fill: { color: theme.accent },
  rectRadius: 0.15
});
slide.addText("03", {
  x: 9.1, y: 5.15, w: 0.6, h: 0.35,
  fontSize: 11, fontFace: "Arial",
  color: "FFFFFF", bold: true,
  align: "center", valign: "middle"
});
```

---

## 主题对象契约（强制）

编译脚本传递带有这些**精确键**的主题对象：

|关键|目的|示例|
|-----|---------|---------|
| `theme.primary` |最深的颜色，标题| `"22223b"` |
| `theme.secondary` |深色口音，正文 | `"4a4e69"` |
| `theme.accent` |中音口音| `"9a8c98"` |
| `theme.light` |浅色口音 | `"c9ada7"` |
| `theme.bg` |背景颜色| `"f2e9e4"` |

**切勿使用其他密钥名称**，例如 `background`、`text`、`muted`、`darkest`、`lightest`。

---

## 子代理输出格式

每个子代理输出一个**完整的、可运行的JS文件**：

```javascript
// slide-01.js
const pptxgen = require("pptxgenjs");

const slideConfig = {
  type: 'cover',
  index: 1,
  title: 'Presentation Title'
};

// ⚠️ MUST be synchronous (not async)
function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: theme.bg };

  slide.addText(slideConfig.title, {
    x: 0.5, y: 2, w: 9, h: 1.2,
    fontSize: 48, fontFace: "Arial",  // English text uses Arial
    color: theme.primary, bold: true, align: "center"
  });

  return slide;
}

// Standalone preview - use slide-specific filename (slide-XX-preview.pptx)
if (require.main === module) {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_16x9';
  const theme = {
    primary: "22223b",
    secondary: "4a4e69",
    accent: "9a8c98",
    light: "c9ada7",
    bg: "f2e9e4"
  };
  createSlide(pres, theme);
  // Replace XX with actual slide index (01, 02, etc.) to avoid conflicts
  pres.writeFile({ fileName: "slide-01-preview.pptx" });
}

module.exports = { createSlide, slideConfig };
```

---

## 关键陷阱

### 切勿在 createSlide() 中使用 async/await

```javascript
// ❌ WRONG - compile.js won't await
async function createSlide(pres, theme) { ... }

// ✅ CORRECT
function createSlide(pres, theme) { ... }
```

### 切勿将“#”与十六进制颜色一起使用

```javascript
color: "FF0000"      // ✅ CORRECT
color: "#FF0000"     // ❌ CORRUPTS FILE
```

### 永远不要在十六进制字符串中编码不透明度

```javascript
shadow: { color: "00000020" }              // ❌ CORRUPTS FILE
shadow: { color: "000000", opacity: 0.12 } // ✅ CORRECT
```

### 防止标题中的文本换行

```javascript
// ✅ Use fit:'shrink' for long titles
slide.addText("Long Title Here", {
  x: 0.5, y: 2, w: 9, h: 1,
  fontSize: 48, fit: "shrink"
});
```

---

## 快速参考

- **尺寸**：10" × 5.625" (LAYOUT_16x9)
- **颜色**：6 个字符的十六进制，不带 #（例如，`"FF0000"`）
- **英文字体**：Arial（默认），或批准的替代字体
- **中文字体**：微软雅黑
- **页面徽章位置**：x：9.3 英寸，y：5.1 英寸

---

## 质量检查（必填）

**假设存在问题。你的工作就是找到他们。**

你的第一次渲染几乎从来都不正确。将 QA 视为 bug 搜寻，而不是确认步骤。如果您在第一次检查时发现零问题，则说明您检查得不够仔细。

### 内容质量检查

```bash
python -m markitdown slide-XX-preview.pptx
```

检查是否有内容缺失、拼写错误、顺序错误。

**检查剩余的占位符文本：**

```bash
python -m markitdown slide-XX-preview.pptx | grep -iE "xxxx|lorem|ipsum|placeholder"
```

如果 grep 返回结果，请在声明成功之前修复它们。

### 验证循环

1. 生成幻灯片 → 使用 `python -m markitdown slide-XX-preview.pptx` 提取文本 → 审阅内容
2. **列出发现的问题**（如果没有发现，请更仔细地再次查看）
3.修复问题
4. **重新验证** — 一项修复通常会产生另一个问题
5. 重复直到验证没有发现新问题

**在至少完成一个修复和验证周期之前，不要宣布成功。**

---
