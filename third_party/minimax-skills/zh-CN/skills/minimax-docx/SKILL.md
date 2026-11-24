---
name: minimax-docx
license: MIT
metadata:
  version: "1.0.0"
  category: document-processing
  author: MiniMaxAI
  sources:
    - "ECMA-376 Office Open XML File Formats"
    - "GB/T 9704-2012 Layout Standard for Official Documents"
    - "IEEE / ACM / APA / MLA / Chicago / Turabian Style Guides"
    - "Springer LNCS / Nature / HBR Document Templates"
description: >
  Professional DOCX document creation, editing, and formatting using OpenXML SDK (.NET).
  Three pipelines: (A) create new documents from scratch, (B) fill/edit content in existing
  documents, (C) apply template formatting with XSD validation gate-check.
  MUST use this skill whenever the user wants to produce, modify, or format a Word document —
  including when they say "write a report", "draft a proposal", "make a contract",
  "fill in this form", "reformat to match this template", or any task whose final output
  is a .docx file. Even if the user doesn't mention "docx" explicitly, if the task
  implies a printable/formal document, use this skill.
triggers:
  - Word
  - docx
  - document
  - 文档
  - Word文档
  - 报告
  - 合同
  - 公文
  - 排版
  - 套模板
---

# 极小极大-docx

通过 CLI 工具或基于 OpenXML SDK (.NET) 构建的直接 C# 脚本创建、编辑和格式化 DOCX 文档。

＃＃ 设置

**第一次：** `bash scripts/setup.sh`（或 Windows 上的 `powershell scripts/setup.ps1`，`--minimal` 跳过可选的 deps）。

**会话中的第一个操作：** `scripts/env_check.sh` — 如果是 `NOT READY`，则不继续。 （跳过同一会话中的后续操作。）

## 快速入门：直接 C# 路径

当任务需要结构化文档操作（自定义样式、复杂表格、多部分布局、页眉/页脚、目录、图像）时，请直接编写 C#，而不是与 CLI 限制作斗争。使用这个脚手架：

```csharp
// File: scripts/dotnet/task.csx  (or a new .cs in a Console project)
// dotnet run --project scripts/dotnet/MiniMaxAIDocx.Cli -- run-script task.csx
#r "nuget: DocumentFormat.OpenXml, 3.2.0"

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

using var doc = WordprocessingDocument.Create("output.docx", WordprocessingDocumentType.Document);
var mainPart = doc.AddMainDocumentPart();
mainPart.Document = new Document(new Body());

// --- Your logic here ---
// Read the relevant Samples/*.cs file FIRST for tested patterns.
// See Samples/ table in References section below.
```

**在编写任何 C# 之前，请阅读相关的 `Samples/*.cs` 文件** — 它们包含可编译的、经过 SDK 版本验证的模式。下面参考部分中的示例表将主题映射到文件。

## CLI 简写

下面的所有 CLI 命令都使用 `$CLI` 作为缩写：
```bash
dotnet run --project scripts/dotnet/MiniMaxAIDocx.Cli --
```

## 管道布线

通过检查进行路由：用户是否有输入的 .docx 文件？

```
User task
├─ No input file → Pipeline A: CREATE
│   signals: "write", "create", "draft", "generate", "new", "make a report/proposal/memo"
│   → Read references/scenario_a_create.md
│
└─ Has input .docx
    ├─ Replace/fill/modify content → Pipeline B: FILL-EDIT
    │   signals: "fill in", "replace", "update", "change text", "add section", "edit"
    │   → Read references/scenario_b_edit_content.md
    │
    └─ Reformat/apply style/template → Pipeline C: FORMAT-APPLY
        signals: "reformat", "apply template", "restyle", "match this format", "套模板", "排版"
        ├─ Template is pure style (no content) → C-1: OVERLAY (apply styles to source)
        └─ Template has structure (cover/TOC/example sections) → C-2: BASE-REPLACE
            (use template as base, replace example content with user content)
        → Read references/scenario_c_apply_template.md
```

如果请求跨越多个管道，请按顺序运行它们（例如，创建然后格式化应用）。

## 预处理

如果需要，转换 `.doc` → `.docx`：`scripts/doc_to_docx.sh input.doc output_dir/`

编辑前预览（避免读取原始 XML）：`scripts/docx_preview.sh document.docx`

分析编辑场景的结构：`$CLI analyze --input document.docx`

## 场景 A：创建

首先读取 `references/scenario_a_create.md`、`references/typography_guide.md` 和 `references/design_principles.md`。从 `Samples/AestheticRecipeSamples.cs` 中选择与文档类型相匹配的美学配方 - 不要发明格式值。对于 CJK，另请阅读 `references/cjk_typography.md`。

**选择你的路径：**
- **简单**（纯文本，最小格式）：使用 CLI — `$CLI create --type report --output out.docx --config content.json`
- **结构**（自定义样式、多节、目录、图像、复杂表格）：直接编写 C#。先阅读相关的`Samples/*.cs`。

CLI 选项：`--type`（报告|信件|备忘录|学术）、`--title`、`--author`、`--page-size`（信件|a4|法律|a3）、`--margins`（标准|窄|宽）、`--header`、`--footer`、`--page-numbers`、`--toc`、 `--content-json`。

然后运行**验证管道**（如下）。

## 场景 B：编辑/填充

先读`references/scenario_b_edit_content.md`。预览→分析→编辑→验证。

**选择你的路径：**
- **简单**（文本替换、占位符填充）：使用 CLI 子命令。
- **结构**（添加/重新组织部分、修改样式、操作表格、插入图像）：直接编写 C#。读取`references/openxml_element_order.md`和相关的`Samples/*.cs`。

可用的 CLI 编辑子命令：
- `replace-text --find "X" --replace "Y"`
- `fill-placeholders --data '{"key":"value"}'`
- `fill-table --data table.json`
- `insert-section`、`remove-section`、`update-header-footer`

```bash
$CLI edit replace-text --input in.docx --output out.docx --find "OLD" --replace "NEW"
$CLI edit fill-placeholders --input in.docx --output out.docx --data '{"name":"John"}'
```

然后运行**验证管道**。还运行 diff 来验证最小的更改：
```bash
$CLI diff --before in.docx --after out.docx
```

## 场景 C：应用模板

先读`references/scenario_c_apply_template.md`。预览并分析源和模板。

```bash
$CLI apply-template --input source.docx --template template.docx --output out.docx
```

对于复杂的模板操作（多模板合并、每节页眉/页脚、样式合并），请直接编写 C# — 请参阅下面的关键规则以了解所需的模式。

运行**验证管道**，然后运行**硬门检查**：
```bash
$CLI validate --input out.docx --gate-check assets/xsd/business-rules.xsd
```
登机口检查是一项**硬性要求**。在通过之前不要交付。如果失败：诊断、修复、重新运行。

还比较验证内容保存：`$CLI diff --before source.docx --after out.docx`

## 验证管道

每次写操作后运行。对于场景 C，完整的管道是**强制性的**；对于 A/B，**推荐**（仅当操作非常简单时才跳过）。

```bash
$CLI merge-runs --input doc.docx                                    # 1. consolidate runs
$CLI validate --input doc.docx --xsd assets/xsd/wml-subset.xsd     # 2. XSD structure
$CLI validate --input doc.docx --business                           # 3. business rules
```

如果 XSD 失败，自动修复并重试：
```bash
$CLI fix-order --input doc.docx
$CLI validate --input doc.docx --xsd assets/xsd/wml-subset.xsd
```

如果 XSD 仍然失败，请退回到业务规则 + 预览：
```bash
$CLI validate --input doc.docx --business
scripts/docx_preview.sh doc.docx
# Verify: font contamination=0, table count correct, drawing count correct, sectPr count correct
```

最终预览：`scripts/docx_preview.sh doc.docx`

## 关键规则

这些可以防止文件损坏 — OpenXML 对元素排序非常严格。

**元素顺序**（属性始终排在第一位）：

|家长 |订单|
|--------|--------|
| `w:p` | `pPr` → 运行 |
| `w:r` | `rPr` → `t`/`br`/`tab` |
| `w:tbl`| `tblPr` → `tblGrid` → `tr` |
| `w:tr` | `trPr` → `tc` |
| `w:tc` | `tcPr` → `p`（最少 1 `<w:p/>`）|
| `w:body` |块内容 → `sectPr`（最后一个子项）|

**直接格式污染：** 从源文档复制内容时，内联 `rPr`（字体、颜色）和 `pPr`（边框、底纹、间距）会覆盖模板样式。始终删除直接格式 - 仅保留 `pStyle` 参考和 `t` 文本。也清理表格（包括单元格内的 `pPr/rPr`）。

**跟踪更改：** `<w:del>` 使用 `<w:delText>`，而不是 `<w:t>`。 `<w:ins>` 使用 `<w:t>`，而不是 `<w:delText>`。

**字体大小：** `w:sz` = 点数 × 2 (12pt → `sz="24"`)。 DXA 中的边距/间距（1 英寸 = 1440，1 厘米 ≈ 567）。

**标题样式必须具有 OutlineLevel：** 定义标题样式（Heading1、ThesisH1 等）时，始终在 `StyleParagraphProperties` 中包含 `new OutlineLevel { Val = N }`（H1→0、H2→1、H3→2）。如果没有这个，Word 会将它们视为纯样式文本 - 目录和导航窗格将无法工作。

**多模板合并：** 当给定多个模板文件（字体、标题、中断）时，请首先阅读 `references/scenario_c_apply_template.md` 部分“多模板合并”。关键规则：
- 将所有模板中的样式合并到一个 styles.xml 中。结构（章节/中断）来自中断模板。
- 每个内容段落必须精确出现一次——插入分节符时切勿重复。
- 切勿插入空/空白段落作为填充或部分分隔符。输出段落数必须等于输入。使用分节符属性（`w:pPr` 内的 `w:sectPr`）和样式间距（之前/之后的 `w:spacing`）进行视觉分离。
- 在每个章节标题之前插入奇数页分节符，而不仅仅是第一个。即使章节有双栏内容，它也必须以 oddPage 开头；在标题后使用第二个连续中断来进行列切换。
- 双栏章节需要三个分节符：(1) 前面段落的 pPr 中的 oddPage，(2) 章节标题的 pPr 中的 Continuous+cols=2，(3) 要恢复的最后一个正文段落的 pPr 中的 Continuous+cols=1。
- 从每个部分的休息模板中复制 `titlePg` 设置。摘要和目录部分通常需要 `titlePg=true`。

**多部分页眉/页脚：** 具有 10 多个部分的模板（例如中文论文）每个部分具有不同的页眉/页脚（罗马与阿拉伯页码，每个区域不同的页眉文本）。规则：
- 使用 C-2 Base-Replace：复制 TEMPLATE 作为输出库，然后替换正文内容。这会自动保留所有部分、页眉、页脚和 titlePg 设置。
- 切勿从头开始重新创建页眉/页脚 — 逐字节复制模板页眉/页脚 XML。
- 切勿添加模板标题 XML 中不存在的格式（边框、对齐方式、字体大小）。
- 非封面部分必须具有页眉/页脚 XML 文件（至少为空页眉 + 页码页脚）。
- 请参阅 `references/scenario_c_apply_template.md` 部分“多节页眉/页脚传输”。

＃＃ 参考

根据需要加载 - 不要一次加载全部。选择与任务最相关的文件。

**下面的 C# 示例和设计参考是项目的知识库（“百科全书”）。** 在编写 OpenXML 代码时，始终首先阅读相关示例文件 - 它包含可编译、经过 SDK 版本验证的模式，可以防止常见错误。在做出美学决策时，请阅读设计原则和配方文件 - 它们对来自权威来源（IEEE、ACM、APA、Nature 等）的经过测试的和谐参数集进行编码，而不是猜测。

### 场景指南（首先阅读每个管道）

|文件 |当 |
|------|------|
| `references/scenario_a_create.md` |管道 A：从头开始创建 |
| `references/scenario_b_edit_content.md` |管道 B：编辑现有内容 |
| `references/scenario_c_apply_template.md` |管道 C：应用模板格式 |

### C# 代码示例（可编译，有大量注释 - 编写代码时阅读）

|文件 |主题 |
|------|--------|
| `Samples/DocumentCreationSamples.cs` |文档生命周期：创建、打开、保存、流、文档默认值、设置、属性、页面设置、多节|
| `Samples/StyleSystemSamples.cs` |样式：普通/标题链、字符/表格/列表样式、DocDefaults、latentStyles、CJK 公文、APA 7th、导入、解析继承 |
| `Samples/CharacterFormattingSamples.cs` | RunProperties：字体、大小、粗体/斜体、所有下划线、颜色、突出显示、删除线、子/超级、大写字母、间距、阴影、边框、强调标记 |
| `Samples/ParagraphFormattingSamples.cs` |段落属性：对齐、缩进、行/段落间距、保留/窗口、大纲级别、边框、制表符、编号、双向、框架 |
| `Samples/TableSamples.cs` |表格：边框、网格、单元格属性、边距、行高、标题重复、合并 (H+V)、嵌套、浮动、三行三线表、斑马条纹 |
| `Samples/HeaderFooterSamples.cs` |页眉/页脚：页码、“Y 页 X”、第一个/偶数/奇数、徽标图像、表格布局、公文“-X-”、每节 |
| `Samples/ImageSamples.cs` |图像：内联、浮动、文本换行、边框、替代文本、标题/表格中、替换、SVG 后备、尺寸计算 |
| `Samples/ListAndNumberingSamples.cs` |编号：项目符号、多级小数、自定义符号、大纲→标题、合法、中文一/（一）/1./(1)、重启/继续 |
| `Samples/FieldAndTocSamples.cs` |字段：TOC、SimpleField 与复杂字段、DATE/PAGE/REF/SEQ/MERGEFIELD/IF/STYLEREF、TOC 样式 |
| `Samples/FootnoteAndCommentSamples.cs` |脚注、尾注、注释（4 文件系统）、书签、超链接（内部 + 外部）|
| `Samples/TrackChangesSamples.cs` |修订：插入 (w:t)、删除 (w:delText!)、格式更改、接受/拒绝全部、移动跟踪 |
| `Samples/AestheticRecipeSamples.cs` |来自权威来源的 13 个美学秘诀：ModernCorporate、AcademicThesis、ExecutiveBrief、ChineseGovernment (GB/T 9704)、MinimalModern、IEEE Con​​ference、ACM sigconf、APA 7th、MLA 9th、Chicago/Turabian、Springer LNCS、Nature、HBR — 每一个都具有来自官方风格指南的精确值 |

注意：`Samples/` 路径是相对于 `scripts/dotnet/MiniMaxAIDocx.Core/` 的。

### Markdown 参考（当您需要规范或设计规则时阅读）

|文件 |当 |
|------|------|
| `references/openxml_element_order.md` | XML 元素排序规则（防止损坏）|
| `references/openxml_units.md` |单位换算：DXA、EMU、半分、八分之一 |
| `references/openxml_encyclopedia_part1.md` |详细的C#百科全书：文档创建、样式、字符和段落格式|
| `references/openxml_encyclopedia_part2.md` |详细的C#百科全书：页面设置、表格、页眉/页脚、节、文档属性 |
| `references/openxml_encyclopedia_part3.md` |详细的C#百科全书：TOC、脚注、字段、跟踪更改、注释、图像、数学、编号、保护 |
| `references/typography_guide.md` |字体配对、大小、间距、页面布局、表格设计、配色方案 |
| `references/cjk_typography.md` | CJK 字体、字号大小、RunFonts 映射、GB/T 9704 公文标准 |
| `references/cjk_university_template_guide.md` |中国大学论文模板：数字styleIds（1/2/3 vs Heading1）、文档区域结构（封面→摘要→目录→正文→参考文献）、字体期望、常见错误 |
| `references/design_principles.md` | **美学基础**：6 条设计原则（留白、对比度/比例、邻近性、对齐、重复、层次结构）— 教导“为什么”，而不仅仅是“什么”|
| `references/design_good_bad_examples.md` | **好与坏的比较**：OpenXML 值、ASCII 模型和修复的 10 类排版错误 |
| `references/track_changes_guide.md` |修订标志着深入研究|
| `references/troubleshooting.md` | **症状驱动的修复**：按您所看到的内容索引的 13 个常见问题（标题错误、图像丢失、目录损坏等）- 按症状搜索，找到修复方法 |
