"""
knowledge.industry_chain
=======================
产业链拓扑 + 龙头公司 + 政策节点定义。

这是 llmwiki 架构的知识底座初始化数据：
- leaders: 各行业龙头公司节点 + "leader" 边
- supplier_of: 跨产业链供应关系边
- policies: 关键政策节点 + "affected_by" 边

用法:
    from knowledge.industry_chain import build_industry_chain
    graph = IndustryGraph()
    build_industry_chain(graph)
    with get_connection() as conn:
        graph.save_to_store(conn)
"""
from __future__ import annotations

from knowledge.graph import IndustryGraph


# ─────────────────────────────────────────────────────────────────────────────
# 1. 龙头公司定义
# format: (symbol, display_name, industry_node_id)
# ─────────────────────────────────────────────────────────────────────────────
LEADERS: list[tuple[str, str, str]] = [
    # ── AI 算力层 ────────────────────────────────────────────────────────────
    ("NVDA",       "英伟达",          "ai_compute"),
    ("AMD",        "超威半导体",       "ai_compute"),
    ("AVGO",       "博通",             "ai_compute"),
    ("MSFT",       "微软",             "ai_compute"),
    ("GOOGL",      "谷歌",             "ai_compute"),
    ("AMZN",       "亚马逊",           "ai_compute"),
    ("META",       "Meta",             "ai_compute"),
    ("华为",       "华为",              "ai_compute"),
    ("百度",       "百度",              "ai_compute"),
    ("工业富联",   "工业富联(Fii)",     "ai_compute"),
    ("浪潮信息",   "浪潮信息",          "ai_compute"),
    ("中科曙光",   "中科曙光",          "ai_compute"),
    # ── GPU ─────────────────────────────────────────────────────────────────
    ("NVDA",       "英伟达",           "gpu"),
    ("AMD",        "超威半导体",        "gpu"),
    ("INTC",       "英特尔",            "gpu"),
    ("AVGO",       "博通",              "gpu"),
    # ── 半导体 ──────────────────────────────────────────────────────────────
    ("SMIC",       "中芯国际",          "semiconductor"),
    ("688981",     "中芯国际(A)",       "semiconductor"),
    ("华虹半导体", "华虹半导体",        "semiconductor"),
    ("三安光电",    "三安光电",          "semiconductor"),
    ("北方华创",    "北方华创",          "semiconductor"),
    ("中微公司",    "中微公司",          "semiconductor"),
    ("长电科技",    "长电科技",          "semiconductor"),
    ("通富微电",    "通富微电",          "semiconductor"),
    ("韦尔股份",    "韦尔股份",          "semiconductor"),
    ("卓胜微",      "卓胜微",            "semiconductor"),
    ("华大九天",    "华大九天",          "semiconductor"),
    ("中科飞测",    "中科飞测",          "semiconductor"),
    ("拓荆科技",    "拓荆科技",          "semiconductor"),
    ("沪硅产业",    "沪硅产业",          "semiconductor"),
    ("天岳先进",    "天岳先进",          "semiconductor"),
    ("有研硅",      "有研硅",            "semiconductor"),
    # ── 存储/HBM ────────────────────────────────────────────────────────────
    ("SK_Hynix",   "SK海力士",          "memory"),
    ("MU",         "镁光科技",          "memory"),
    ("长江存储",    "长江存储",           "memory"),
    ("长鑫存储",    "长鑫存储",           "memory"),
    # ── 半导体设备 ─────────────────────────────────────────────────────────
    ("ASML",       "ASML",              "equipment"),
    ("AMAT",       "应用材料",           "equipment"),
    ("LRCX",       "科磊半导体",        "equipment"),
    ("ACM",        "ACM Research",      "equipment"),
    # ── EDA/IP ──────────────────────────────────────────────────────────────
    ("SNPS",       "新思科技",           "eda_ip"),
    ("CDNS",       "Cadence",            "eda_ip"),
    # ── 光通信 ──────────────────────────────────────────────────────────────
    ("中际旭创",    "中际旭创",           "optical_comms"),
    ("光迅科技",    "光迅科技",           "optical_comms"),
    ("博创科技",    "博创科技",           "optical_comms"),
    ("新易盛",      "新易盛",             "optical_comms"),
    ("天邑股份",    "天邑股份",           "optical_comms"),
    ("天孚通信",    "天孚通信",           "optical_comms"),
    ("华为",        "华为",               "optical_comms"),
    # ── PCB/封装 ─────────────────────────────────────────────────────────────
    ("深南电路",    "深南电路",           "packaging"),
    ("生益科技",    "生益科技",           "packaging"),
    ("南亚新材",    "南亚新材",           "packaging"),
]

# ─────────────────────────────────────────────────────────────────────────────
# 2. 供应关系定义
# format: (upstream_node_id, downstream_node_id, weight)
# 跨行业链接反映真实产业依存
# ─────────────────────────────────────────────────────────────────────────────
SUPPLIER_OF: list[tuple[str, str, float]] = [
    # ══════════════════════════════════════════════════════════════════════════
    # AI 算力层内部
    # ══════════════════════════════════════════════════════════════════════════
    # 电力 → 算力基础设施
    ("ai_compute:upstream:power",         "ai_compute:midstream:data_center",     0.8),
    # 芯片 → 服务器 → 云 → AI 应用
    ("ai_compute:upstream:chips",         "ai_compute:midstream:servers",         0.9),
    ("ai_compute:upstream:memory",        "ai_compute:midstream:servers",          0.8),
    ("ai_compute:midstream:servers",       "ai_compute:midstream:cloud",            0.9),
    ("ai_compute:midstream:cloud",         "ai_compute:downstream:model_training",  0.8),
    ("ai_compute:midstream:cloud",         "ai_compute:downstream:enterprise_ai",   0.7),
    # 网络 → 数据中心
    ("ai_compute:upstream:network",        "ai_compute:midstream:data_center",      0.9),

    # ══════════════════════════════════════════════════════════════════════════
    # GPU 内部
    # ══════════════════════════════════════════════════════════════════════════
    ("gpu:upstream:eda_ip",               "gpu:midstream:gpu_design",               0.9),
    ("gpu:upstream:materials",            "gpu:midstream:advanced_packaging",        0.7),
    ("gpu:upstream:wafer_fab",            "gpu:midstream:gpu_design",                0.6),
    ("gpu:upstream:hbm_memory",            "gpu:midstream:gpu_design",               0.9),
    ("gpu:midstream:gpu_design",           "gpu:midstream:advanced_packaging",        0.8),
    # GPU → AI 应用
    ("gpu:downstream:training",           "ai_compute:downstream:model_training",   1.0),
    ("gpu:downstream:inference",          "ai_compute:downstream:enterprise_ai",    0.9),
    ("gpu:downstream:inference",          "ai_compute:downstream:edge_ai",           0.8),

    # ══════════════════════════════════════════════════════════════════════════
    # 半导体内部
    # ══════════════════════════════════════════════════════════════════════════
    ("semiconductor:upstream:materials",   "semiconductor:midstream:foundry",         0.8),
    ("semiconductor:upstream:materials",   "semiconductor:midstream:ic_design",       0.6),
    ("semiconductor:upstream:equipment",   "semiconductor:midstream:foundry",        0.9),
    ("semiconductor:upstream:equipment",   "semiconductor:midstream:packaging_test", 0.7),
    ("semiconductor:upstream:EDA",         "semiconductor:midstream:ic_design",       0.9),
    ("semiconductor:midstream:foundry",    "semiconductor:midstream:ic_design",      0.5),
    ("semiconductor:midstream:ic_design",  "semiconductor:midstream:packaging_test",  0.8),
    # 半导体 → 下游
    ("semiconductor:midstream:foundry",    "gpu:upstream:wafer_fab",                  0.7),
    ("semiconductor:midstream:ic_design",  "gpu:midstream:gpu_design",                0.6),
    ("semiconductor:midstream:foundry",    "semiconductor:downstream:consumer_electronics", 0.7),
    ("semiconductor:midstream:foundry",    "semiconductor:downstream:automotive",     0.6),

    # ══════════════════════════════════════════════════════════════════════════
    # 存储/HBM 内部
    # ══════════════════════════════════════════════════════════════════════════
    ("memory:upstream:materials",          "memory:midstream:chip_fab",               0.8),
    ("memory:upstream:equipment",          "memory:midstream:chip_fab",                0.9),
    ("memory:midstream:chip_fab",         "memory:midstream:hbm_packaging",           0.9),
    ("memory:midstream:hbm_packaging",    "gpu:upstream:hbm_memory",                  1.0),
    # 存储 → 下游
    ("memory:downstream:server_memory",    "ai_compute:midstream:servers",            0.9),
    ("memory:downstream:server_memory",    "ai_compute:midstream:data_center",        0.8),
    ("memory:downstream:consumer_memory",  "semiconductor:downstream:consumer_electronics", 0.7),

    # ══════════════════════════════════════════════════════════════════════════
    # 半导体设备内部
    # ══════════════════════════════════════════════════════════════════════════
    ("equipment:upstream:components",     "equipment:midstream:wafer_equip",         0.8),
    ("equipment:upstream:components",     "equipment:midstream:test_equip",           0.7),
    ("equipment:midstream:wafer_equip",   "semiconductor:midstream:foundry",         1.0),
    ("equipment:midstream:wafer_equip",   "memory:midstream:chip_fab",               0.9),
    ("equipment:midstream:packaging_equip","semiconductor:midstream:packaging_test",  0.9),
    ("equipment:midstream:test_equip",    "semiconductor:midstream:packaging_test",  0.8),

    # ══════════════════════════════════════════════════════════════════════════
    # EDA/IP 内部
    # ══════════════════════════════════════════════════════════════════════════
    ("eda_ip:upstream:IP_cores",          "eda_ip:midstream:EDA_tools",              0.9),
    ("eda_ip:midstream:EDA_tools",        "gpu:midstream:gpu_design",                 0.9),
    ("eda_ip:midstream:EDA_tools",        "semiconductor:midstream:ic_design",        0.9),
    ("eda_ip:midstream:EDA_tools",        "memory:midstream:chip_fab",                0.7),

    # ══════════════════════════════════════════════════════════════════════════
    # 封装/PCB 内部
    # ══════════════════════════════════════════════════════════════════════════
    ("packaging:upstream:substrate",       "packaging:midstream:advanced_pkging",     0.9),
    ("packaging:upstream:materials",        "packaging:midstream:advanced_pkging",     0.7),
    ("packaging:midstream:advanced_pkging","gpu:midstream:advanced_packaging",          0.8),
    ("packaging:midstream:advanced_pkging","memory:midstream:hbm_packaging",           0.8),
    ("packaging:midstream:advanced_pkging","semiconductor:midstream:packaging_test",    0.7),
    ("packaging:midstream:PCB",            "ai_compute:midstream:servers",             0.8),
    ("packaging:midstream:PCB",            "ai_compute:midstream:data_center",         0.7),

    # ══════════════════════════════════════════════════════════════════════════
    # 光通信内部
    # ══════════════════════════════════════════════════════════════════════════
    ("optical_comms:upstream:optical_chips",     "optical_comms:midstream:optical_modules",  0.9),
    ("optical_comms:upstream:optical_materials",  "optical_comms:midstream:optical_modules",  0.7),
    ("optical_comms:upstream:optical_chips",     "optical_comms:midstream:optical_devices",  0.8),
    ("optical_comms:midstream:optical_modules",   "optical_comms:downstream:data_center_network", 1.0),
    ("optical_comms:midstream:optical_modules",   "optical_comms:downstream:telecom_network",   0.9),

    # ══════════════════════════════════════════════════════════════════════════
    # 跨行业链接
    # ══════════════════════════════════════════════════════════════════════════
    # 光通信 → AI 数据中心
    ("optical_comms:midstream:optical_modules",   "ai_compute:midstream:data_center",    0.9),
    ("optical_comms:downstream:data_center_network","ai_compute:midstream:data_center", 0.8),
    # 半导体 → AI 算力
    ("semiconductor:midstream:ic_design",   "ai_compute:upstream:chips",              0.8),
    ("semiconductor:midstream:foundry",     "ai_compute:upstream:chips",              0.7),
    # 存储 → AI 算力
    ("memory:midstream:hbm_packaging",      "ai_compute:upstream:memory",             0.9),
    # 封装 → AI 服务器
    ("packaging:midstream:PCB",             "ai_compute:midstream:servers",           0.8),
    # 电力 → 半导体晶圆
    ("ai_compute:upstream:power",            "semiconductor:upstream:equipment",       0.5),
    # GPU 设计用 EDA（跨行业）
    ("gpu:upstream:eda_ip",                  "semiconductor:midstream:ic_design",     0.7),
]

# ─────────────────────────────────────────────────────────────────────────────
# 3. 政策节点定义
# format: (policy_id, display_name, affected_industry_or_segment, weight)
# ─────────────────────────────────────────────────────────────────────────────
POLICIES: list[tuple[str, str, str, float]] = [
    ("芯片出口管制_2020",  "美国芯片出口管制 (2020)",          "ai_compute",        0.9),
    ("芯片出口管制_2020",  "美国芯片出口管制 (2020)",          "gpu",                0.9),
    ("芯片出口管制_2020",  "美国芯片出口管制 (2020)",          "semiconductor",      0.7),
    ("实体清单_2023",      "实体清单扩展 (2023)",              "ai_compute",         0.8),
    ("实体清单_2023",      "实体清单扩展 (2023)",              "semiconductor",      0.8),
    ("半导体大基金",       "国家半导体产业大基金",              "semiconductor",      1.0),
    ("半导体大基金",       "国家半导体产业大基金",              "gpu",                0.7),
    ("十五五规划_ai",      "十五五 AI 新质生产力",              "ai_compute",         1.0),
    ("十五五规划_ai",      "十五五 AI 新质生产力",              "gpu",                0.9),
    ("十五五规划_ai",      "十五五 AI 新质生产力",              "semiconductor",      0.9),
    ("专精特新",           "专精特新企业政策",                 "semiconductor",      0.8),
    ("专精特新",           "专精特新企业政策",                 "optical_comms",      0.7),
    ("双碳政策",           "碳达峰碳中和政策",                 "ai_compute",         0.4),
    ("双碳政策",           "碳达峰碳中和政策",                 "optical_comms",      0.5),
    ("算力基础设施政策",   "全国算力基础设施发展规划",         "ai_compute",         1.0),
    ("算力基础设施政策",   "全国算力基础设施发展规划",         "optical_comms",      0.8),
]


# ─────────────────────────────────────────────────────────────────────────────
# 4. 构建函数
# ─────────────────────────────────────────────────────────────────────────────

def build_industry_chain(graph: IndustryGraph) -> dict:
    """将龙头公司、供应关系、政策节点写入 graph。幂等调用。"""
    stats = {"leaders": 0, "supplier_edges": 0, "policies": 0, "affected_edges": 0}

    # 4a. 注入 taxonomy 基线（确保行业/segment 节点已存在）
    from knowledge.taxonomy import DEFAULT_TAXONOMY
    graph.add_taxonomy(DEFAULT_TAXONOMY)

    # 4b. 龙头公司
    seen_companies: set[str] = set()
    for symbol, name, industry in LEADERS:
        if symbol not in seen_companies:
            graph.upsert_node(symbol, "company", name)
            seen_companies.add(symbol)
            stats["leaders"] += 1
        graph.upsert_edge(industry, symbol, "leader", weight=1.0)

    # 4c. 供应关系
    for src, dst, weight in SUPPLIER_OF:
        if not graph.has_node(src):
            # 自动创建缺失的 segment 节点
            parts = src.split(":", 2)
            if len(parts) == 3:
                _, layer, seg_name = parts
                graph.upsert_node(src, "segment", seg_name, layer=layer)
        if not graph.has_node(dst):
            parts = dst.split(":", 2)
            if len(parts) == 3:
                _, layer, seg_name = parts
                graph.upsert_node(dst, "segment", seg_name, layer=layer)
        graph.upsert_edge(src, dst, "supplier_of", weight=weight)
        stats["supplier_edges"] += 1

    # 4d. 政策节点 + affected_by 边
    seen_policies: set[str] = set()
    for policy_id, name, target, weight in POLICIES:
        if policy_id not in seen_policies:
            graph.upsert_node(policy_id, "policy", name)
            seen_policies.add(policy_id)
            stats["policies"] += 1
        graph.upsert_edge(target, policy_id, "affected_by", weight=weight)
        stats["affected_edges"] += 1

    return stats
