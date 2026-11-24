---
name: ppt-orchestra-skill
description: "Plan and orchestrate multi-slide PowerPoint creation from scratch. Use before generating a full deck with subagents: classify each slide type, enforce visual variety, set typography/spacing rules, and run text-based QA to catch content issues."
license: Proprietary. LICENSE.txt has complete terms
---

# 幻灯片页面类型（标准）

对于逐张幻灯片生成（每张幻灯片一个 JS 文件），将**每张幻灯片**分类为这 5 种页面类型中的**恰好一种**。这可以保持结构一致并防止“随机布局漂移”。

1. **封面**
   - **用途**：开场+音调设置
   - **内容**：大标题、副标题/演示者、日期/场合、强烈的背景/主题
2. **目录**
   - **用于**：导航 + 期望设置（3-5 个部分）
   - **内容**：部分列表（可选图标/页码）
3. **部分分隔符**
   - **用于**：主要部分之间的清晰过渡
   - **内容**：节号 + 标题（+ 可选的 1-2 行介绍）
4. **内容页面**（选择一个子类型）
   - **文本**：项目符号/引号/短段落（仍添加图标/形状）
   - **混合媒体**：两列/半出血图像+文本覆盖
   - **数据可视化**：图表 + 1-3 个关键要点 + **来源**
   - **比较**：并排列/卡（A 与 B，优点/缺点）
   - **时间表/流程**：带有箭头的步骤、旅程、阶段
   - **图像展示**：英雄图像、图库或视觉优先布局
5. **摘要/结束页**
   - **用于**：总结+行动
   - **内容**：关键要点、CTA/后续步骤、联系方式/QR、谢谢

**布局选项：**
- 两栏（左侧为文字，右侧为插图）
- 图标+文本行（彩色圆圈中的图标，粗体标题，下面的说明）
- 2x2 或 2x3 网格（一侧为图像，另一侧为内容块网格）
- 带有内容叠加的半出血图像（完整的左侧或右侧）

**数据显示：**
- 大统计标注（大数字 60-72pt，下面带有小标签）
- 比较栏（之前/之后、优点/缺点、并排选项）
- 时间线或流程（编号步骤、箭头）

**视觉修饰：**
- 部分标题旁边的小彩色圆圈中的图标
- 关键统计数据或标语的斜体重音文本

### 版式

**选择有趣的字体配对** - 不要默认为 Arial。选择具有个性的标题字体，并将其与干净的正文字体配对。

|标题字体 |正文字体|
|------------|------------|
|格鲁吉亚 |卡利布里 |
|宋体黑 |宋体 |
|卡利布里 |卡利布里光|
|坎布里亚|卡利布里 |
|投石机 MS |卡利布里 |
|影响 |宋体 |
|帕拉蒂诺 |加拉蒙 |
|康索拉斯 |卡利布里 |

|元素|尺寸|
|---------|------|
|幻灯片标题 | 36-44pt 粗体 |
|节标题| 20-24pt 粗体 |
|正文 | 14-16 分 |
|字幕| 10-12 点静音 |

### 间距

- 0.5" 最小边距
- 内容块之间 0.3-0.5"
- 留出喘息空间——不要填满每一寸

### 避免（常见错误）

- **不要重复相同的布局** - 在幻灯片中改变列、卡片和标注
- **不要将正文居中** — 左对齐段落和列表；仅中心标题
- **不要吝惜大小对比** — 标题需要 36pt+ 才能从 14-16pt 正文中脱颖而出
- **不要默认为蓝色** — 选择反映特定主题的颜色
- **不要随机混合间距** — 选择 0.3 英寸或 0.5 英寸间隙并一致使用
- **不要设计一张幻灯片而让其余部分保持简单** - 完全承诺或保持简单
- **不要创建纯文本幻灯片** — 添加图像、图标、图表或视觉元素；避免简单的标题+项目符号
- **不要忘记文本框填充** - 将线条或形状与文本边缘对齐时，在文本框上设置 `margin: 0` 或偏移形状以考虑填充
- **不要使用低对比度元素** - 图标和文本需要与背景形成强烈对比；避免在浅色背景上使用浅色文本或在深色背景上使用深色文本
- **切勿在标题下使用重音线** - 这是人工智能生成幻灯片的标志；使用空白或背景颜色代替

## 编译幻灯片

在`slides/`中生成所有幻灯片JS文件后，创建`slides/compile.js`将它们编译成单个PPTX：

```javascript
// slides/compile.js
const pptxgen = require('pptxgenjs');
const pres = new pptxgen();
pres.layout = 'LAYOUT_16x9';

const theme = {
  primary: "22223b",    // dark color for backgrounds/text
  secondary: "4a4e69",  // secondary accent
  accent: "9a8c98",     // highlight color
  light: "c9ada7",      // light accent
  bg: "f2e9e4"          // background color
};

for (let i = 1; i <= 12; i++) {  // adjust count as needed
  const num = String(i).padStart(2, '0');
  const slideModule = require(`./slide-${num}.js`);
  slideModule.createSlide(pres, theme);
}

pres.writeFile({ fileName: './output/presentation.pptx' });
```

运行：`cd slides && node compile.js`

---

## 质量检查（必填）

**假设存在问题。你的工作就是找到他们。**

你的第一次渲染几乎从来都不正确。将 QA 视为 bug 搜寻，而不是确认步骤。如果您在第一次检查时发现零问题，则说明您检查得不够仔细。

### 内容质量检查

```bash
python -m markitdown output.pptx
```

检查是否有内容缺失、拼写错误、顺序错误。

**使用模板时，检查剩余的占位符文本：**

```bash
python -m markitdown output.pptx | grep -iE "xxxx|lorem|ipsum|this.*(page|slide).*layout"
```

如果 grep 返回结果，请在声明成功之前修复它们。

### 验证循环

1. 生成幻灯片 → 使用 `python -m markitdown output.pptx` 提取文本 → 审阅内容
2. **列出发现的问题**（如果没有发现，请更仔细地再次查看）
3.修复问题
4. **重新验证受影响的幻灯片** - 一项修复通常会产生另一个问题
5. 重复直到完整通过没有发现新问题

**在至少完成一个修复和验证周期之前，不要宣布成功。**

---

## 依赖关系

- `pip install "markitdown[pptx]"` - 文本提取
- `npm install -g pptxgenjs` - 从头开始创建
