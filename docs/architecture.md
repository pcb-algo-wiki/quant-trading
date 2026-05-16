# Architecture Overview

## Current modules

1. **data/**: market/news/fundamental data fetching and cache.
2. **strategies/**: signal generation (trend, rotation, multi-factor).
3. **backtest/**: backtest engine and risk controls.
4. **execution/**: paper trading execution and order lifecycle.
5. **scripts/**: daily report, dashboard, strategy runners.
6. **utils/**: config, retry, notification helpers.

## Data flow

1. Fetch market/news/fundamental data from providers (`data/*`).
2. Clean/validate input data (`data/quality.py`).
3. Build strategy signals (`strategies/*`).
4. Evaluate via backtest (`backtest/*`) or paper account (`execution/*`).
5. Publish artifacts via dashboard and daily report (`scripts/*`).

## Phase-0 boundaries

This phase keeps existing behavior and introduces explicit extension boundaries:

- **data_store/**: persistent storage and repositories for structured datasets.
- **knowledge/**: industry taxonomy, source docs, and knowledge cards.
- **research/**: event extraction, industry scoring, leaderboards/reports.
- **ml/**: feature/label dataset, model training and evaluation.

These modules are introduced as package boundaries first, then implemented in next phases.

## 当前架构（已实现）

```mermaid
flowchart LR
    subgraph Sources[数据源]
        AK[AkShare]
        SINA[新浪]
        YF[yfinance]
    end
    subgraph Ingest[摄取]
        DATA[data/*]
        DS[(data_store SQLite\nmarket_bars/news_items\npolicy_items/financial_reports)]
    end
    subgraph Research[研究/知识]
        KN[knowledge/\n行业卡片 + 4 类 taxonomy]
        RE[research/\nevents + industry_scores]
        ML[ml/\n线性基线 + walk-forward]
    end
    subgraph Strategy[策略 & 回测]
        ST[strategies/\ntrend/rotation/multi-factor]
        BT[backtest/\nengine + V2 风险]
    end
    subgraph Exec[执行]
        PA[execution/paper]
        BR[execution/broker mock/replay]
        LG[live_guard + risk_controls]
    end
    ORCH[scripts/daily_pipeline.py]

    Sources --> DATA --> DS
    DS --> KN --> RE
    DS --> ML --> ST
    KN --> RE --> ST
    ST --> BT
    ST --> PA --> BR
    LG --> PA
    ORCH -.调度.-> DATA & KN & RE & ML & BT
```

## 目标架构（方案蓝图）

```mermaid
flowchart LR
    subgraph K[知识底座 llmwiki + GraphRAG]
        RAW[raw/ 不可变原文]
        WIKI[wiki/ AI 可写沉淀]
        KG[(知识图谱\nNeo4j / NetworkX 替代)]
        VEC[(向量库)]
        HR[HybridRetriever\nBM25 + 图 + 向量 / RRF]
    end
    subgraph F[基本面摄取]
        SEC[SEC EDGAR]
        CN[巨潮 CNINFO]
        PDF[pdfplumber / GPT-Vision]
        MAD[ROLES Prompt + MAD\n单 LLM + 规则校验替代]
    end
    subgraph P[政策与情感]
        POL[十五五 / 政策文本]
        PAS[Policy Alignment Score]
        SEN[FinBERT / SnowNLP+词典]
        PROP[图传播 BFS / GNN]
    end
    subgraph D[多源数据]
        AK2[AkShare]
        TS[Tushare]
        YF2[yfinance]
        PG[Polygon / AlphaVantage]
    end
    subgraph S[策略层]
        LONG[长线: DCF + 护城河 + 政策 Alpha + MVO]
        SHORT[事件驱动: 情绪 + 图传染 + MACD/RSI]
        GATE[Regime Gating\n规则替代 RL]
    end
    subgraph X[执行]
        VN[VeighNa 适配器\ndry-run 起步]
        LG2[live_guard / 风控]
        REC[对账 reconciliation]
    end
    ORCH2[daily_pipeline / Airflow]

    SEC & CN --> PDF --> MAD --> KG
    POL --> PAS --> KG
    D --> KG
    KG & VEC --> HR
    HR --> LONG & SHORT
    SEN --> PROP --> SHORT
    LONG & SHORT --> GATE --> VN
    LG2 --> VN --> REC
    ORCH2 -.调度.-> F & P & D & S & X
```

## 落地策略

- 详见 `docs/落地全景计划.md`：把目标架构按 Phase 0–6 拆分，重型组件（Neo4j / GPT-Vision / MAD / FinBERT / GNN / VeighNa / RL）先用轻量方案落地，验证闭环后再升级。

## Phase 1 实际落点（已实现）

- 文件层：`llmwiki/{raw,wiki}/` + `llmwiki/CLAUDE.md`（4 类节点 / 5 类边 / 写入规则）。
- 持久化：`data_store` 新增 `knowledge_nodes / knowledge_edges / knowledge_evidence` 三表（含索引）。
- 内存图：`knowledge/graph.py` 的 `IndustryGraph`（NetworkX DiGraph + upsert + neighbors + save/load）；旧 `build_industry_graph(taxonomy, leaders)` 函数签名保留。
- 抽取：`knowledge/extractors.py` 规则 NER（公司词典 + taxonomy alias + 政策正则），预留 `LLMEntityExtractor` 接口。
- 检索：`knowledge/retrieval.py` 自实现 `BM25Retriever` + `GraphNeighborRetriever` + `HybridRetriever` (RRF)；`VectorRetriever` 占位。
- 构建脚本：`scripts/build_knowledge_graph.py`，已挂到 `scripts/daily_pipeline.py`（`config.yaml` 中 `knowledge.graph.enabled: false`，默认关闭）。
- 测试：`tests/test_knowledge_graph_phase1.py` 11 用例覆盖向后兼容、upsert 幂等、BFS 邻居、持久化、抽取正负样本、BM25、RRF、Hybrid、增量构建幂等、证据回链。


