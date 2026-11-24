---
name: pr-review
description: >
  Review pull requests for the MiniMax Skills repository. Use when reviewing PRs,
  validating new skill submissions, or checking existing skills for compliance.
  Run the validation script first for hard checks, then apply quality guidelines
  for content review. Triggers: PR review, pull request, validate skill, check skill.
license: MIT
metadata:
  version: "1.0"
  category: tooling
---

# 公关审核技巧

根据存储库标准审查拉取请求。两阶段过程：自动验证，然后手动内容审核。

## 第 1 阶段：自动验证（硬规则）

运行验证脚本来检查结构要求：

```bash
python .claude/skills/pr-review/scripts/validate_skills.py
```

该脚本检查：
- `SKILL.md`存在于每个技能目录中
- YAML frontmatter 是可解析的
- 存在必填字段：`name`、`description`
- `name` 匹配目录名称
- 未检测到硬编码秘密

所有错误级别的检查都必须通过。警告级别的项目（缺少 `license`、`metadata`）应被标记，但不是阻止程序。

有关完整的硬规则规范，请参阅 [references/structural-rules.md](references/structure-rules.md)]。

## 第 2 阶段：内容审核（软准则）

自动检查通过后，根据质量指南审查 PR：

1. **技能范围** — 是否与现有技能重叠？界限是否清晰？
2. **描述质量** — `description` 是否包含明确的触发条件？
3. **文件大小** — 参考文档的大小是否适合上下文窗口的使用？
4. **API 密钥处理** — 如果使用外部 API，是否从环境变量中读取凭据？
5. **脚本质量** — 脚本是否有 shebang、requirements.txt 和错误处理？
6. **语言** — SKILL.md 和代码是用英语编写的吗？
7. **自述文件同步** — `README.md` 和 `README_zh.md` 是否更新了新技能？

有关软指南的详细信息，请参阅 [references/quality-guidelines.md](references/quality-guidelines.md)。

## 审核清单摘要

### 必须通过（阻碍者）
- [ ] `validate_skills.py` 退出，代码为 0
- [ ] PR 标题遵循常规提交格式
- [ ] 一个公关，一个目的

### 应该通过（在审核中标记）
- [ ] 与现有技能没有功能重叠
- [ ] 描述包括触发条件
- [ ] 文件大小合理
- [ ] 通过环境变量的 API 密钥
- [ ] README 表更新了新技能（源列设置为 `Community`）
