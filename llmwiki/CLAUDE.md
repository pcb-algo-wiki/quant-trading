# llmwiki Schema 与写入规则

> 所有 AI 助手（Claude / Copilot / 其它 LLM）在 `llmwiki/` 下读写时**必须**遵循本文件约束。

## 1. 目录约定

```
llmwiki/
├── raw/         # 不可变原文（来源即真理）
│   └── <source>/<yyyy>/<content_hash>.{pdf|html|txt|json}
└── wiki/        # AI 可写沉淀（结构化卡片）
    ├── industry/<industry_id>.md
    ├── company/<symbol>.md
    └── policy/<policy_id>.md
```

- `content_hash` = sha256(原始字节) 前 16 位，与 `data_store.source_documents.content_hash` 一致。
- 同一原文被多次抓取，按字节去重；hash 变化即视为新版本，新文件名落盘，旧文件保留。

## 2. 节点四类（与 `knowledge_nodes.type` 一一对应）

| 类型 | id 规则 | 说明 |
|---|---|---|
| `industry` | taxonomy key（如 `ai_compute`） | 一级行业 |
| `segment` | `<industry>:<layer>:<segment>`（如 `gpu:midstream:gpu_design`） | 产业链节点 |
| `company` | A 股 6 位代码 / 美股 ticker | 公司主体 |
| `policy` | `policy:<source>:<hash16>` | 政策文件 |

## 3. 边五类（与 `knowledge_edges.type` 一一对应）

| 类型 | 方向 | 含义 |
|---|---|---|
| `has_segment` | industry → segment | 行业包含产业链节点 |
| `leader` | industry → company | 行业龙头 |
| `supplier_of` | company → company | 供应关系（上游 → 下游） |
| `mentioned_in` | (company\|industry\|segment) → doc | 实体在某文档被提及 |
| `affected_by` | (company\|industry) → policy | 受政策影响 |

边可带 `weight ∈ [0,1]` 与 `evidence_json`（来源文档 hash + 片段）。

## 4. wiki/ 卡片 frontmatter 必填项

```yaml
---
node_id: <对应 knowledge_nodes.node_id>
type: industry|company|policy
name: <人类可读名>
sources: [<content_hash16>, ...]   # 至少 1 个，回链 raw/ 或 source_documents
updated_at: <ISO8601>
generator: rule | llm:<model> | manual
confidence: 0.0-1.0                # generator=rule 时固定 1.0
---
```

正文部分由生成器自由组织，但**禁止编造未列入 `sources` 的具体数字 / 公司名 / 政策条款**。

## 5. 写入规则（AI 必须遵守）

1. **来源回链强制**：任何 `wiki/` 写入都必须能在 `sources` 中找到至少一个文档 hash。
2. **数字一致性**：卡片中的财务数字、市值、占比，必须能在引用文档原文（或解析后的
   `data_store.financial_reports`）中找到原值；不允许"近似"或"估算"。
3. **降级原则**：LLM 抽取置信度 < 0.6 或校验失败时，回退到规则版输出，并在 `generator` 标注 `rule`。
4. **幂等写入**：同 `node_id` 再次写入需覆盖式更新 + bump `updated_at`，不创建副本。
5. **不可改 `raw/`**：禁止编辑、覆写、删除 `raw/` 下任何已存在文件。

## 6. 与 data_store 的关系

- 文件系统（本目录）= 人类可读 + 版本友好的展示层。
- `data_store` 三表 = 可查询、可索引、支持 HybridRetriever 的结构化层。
- 两侧通过 `node_id` 与 `content_hash` 双向回链；以 `data_store` 为单一真相源（SSOT），
  `wiki/` 卡片是其投影，可随时由 `scripts/build_knowledge_graph.py` 重新生成。
