# llmwiki

本目录是项目知识底座的文件层（参考 Karpathy "LLM-wiki" 理念），与 `data_store`
SQLite 中的 `knowledge_nodes / knowledge_edges / knowledge_evidence` 三表配合使用：

- `raw/` — **不可变原文**。任何抓取下来的原始文档（公告 PDF、政策原文、新闻全文）按
  `<source>/<yyyy>/<content_hash>.{ext}` 落盘。一旦写入禁止修改/删除，只能追加新版本。
- `wiki/` — **AI 可写沉淀**。结构化卡片（行业卡片、公司护城河、政策解读）以 Markdown +
  YAML frontmatter 保存，按 `<节点类型>/<节点 id>.md` 组织。允许 AI / 脚本覆写。
- `CLAUDE.md` — 给 AI 助手（Claude / Copilot / 其它 LLM）的写入规则、schema、约束。

详细 schema 与约束见 `CLAUDE.md`。
