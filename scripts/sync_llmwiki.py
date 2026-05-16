#!/usr/bin/env python3
"""
scripts/sync_llmwiki.py
========================
将 data_store SQLite 中的知识图谱同步投影到 llmwiki/wiki/ 目录，
生成 Markdown 行业/公司/政策卡片。

工作流程：
  1. 从 SQLite 加载 knowledge_nodes / knowledge_edges / knowledge_evidence
  2. 按 node_id 类型分别渲染：
     - industry / segment → wiki/industry/<id>.md
     - company          → wiki/company/<symbol>.md
     - policy           → wiki/policy/<id>.md
     - document         → (暂不生成独立文件，证据内联到来源节点)
  3. 生成 wiki/index.md 导航索引
  4. 生成 wiki/log.md 同步记录

调用：
    python scripts/sync_llmwiki.py
    python scripts/sync_llmwiki.py --dry
"""
from __future__ import annotations

import json
import re
import hashlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_store.db import get_connection

WIKI_ROOT = Path(__file__).parent.parent / "llmwiki" / "wiki"
RAW_ROOT  = Path(__file__).parent.parent / "llmwiki" / "raw"


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _slug(name: str) -> str:
    """生成安全的文件名 slug."""
    return re.sub(r'[^\w\-]', '_', name).strip('_')[:48]


def _hash16(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# 加载阶段
# ─────────────────────────────────────────────────────────────────────────────

def _load_graph(conn: sqlite3.Connection) -> tuple[dict, dict, dict]:
    """返回 (nodes, edges, evidence) 三个 dict。"""
    nodes: dict = {}
    for row in conn.execute(
        "SELECT node_id, type, name, attrs_json, updated_at FROM knowledge_nodes"
    ):
        nodes[row["node_id"]] = {
            "type":      row["type"],
            "name":      row["name"],
            "attrs":     json.loads(row["attrs_json"] or "{}"),
            "updated_at": row["updated_at"],
        }

    edges: dict = {}
    for row in conn.execute(
        "SELECT src, dst, type, weight, evidence_json, updated_at FROM knowledge_edges"
    ):
        key = (row["src"], row["dst"], row["type"])
        edges[key] = {
            "weight":      float(row["weight"]),
            "evidence":    json.loads(row["evidence_json"] or "[]"),
            "updated_at":  row["updated_at"],
        }

    evidence: dict = {}
    for row in conn.execute(
        "SELECT node_id, doc_source, doc_hash, snippet, ts FROM knowledge_evidence"
    ):
        nid = row["node_id"]
        if nid not in evidence:
            evidence[nid] = []
        evidence[nid].append({
            "source": row["doc_source"],
            "hash":   row["doc_hash"],
            "snippet": row["snippet"],
            "ts":     row["ts"],
        })

    return nodes, edges, evidence


# ─────────────────────────────────────────────────────────────────────────────
# 渲染阶段
# ─────────────────────────────────────────────────────────────────────────────

def _frontmatter(node_id: str, ntype: str, name: str,
                  sources: list[str], updated_at: str) -> str:
    """渲染 YAML frontmatter."""
    generator = "rule"
    confidence = 1.0
    srcs = json.dumps(sources, ensure_ascii=False)
    return (
        f"---\n"
        f"node_id: {node_id}\n"
        f"type: {ntype}\n"
        f"name: {name}\n"
        f"sources: {srcs}\n"
        f"updated_at: {updated_at}\n"
        f"generator: {generator}\n"
        f"confidence: {confidence}\n"
        f"---\n"
    )


def _render_industry(node_id: str, node: dict,
                      edges: dict, evidence: dict) -> str:
    """渲染行业卡片。"""
    parts = node_id.split(":", 1) if ":" in node_id else [node_id, ""]
    industry_id = parts[0]
    layer = node.get("attrs", {}).get("layer", "")

    # 找关联边
    out_edges = {
        (dst, etype): edata
        for (src, dst, etype), edata in edges.items()
        if src == node_id
    }
    in_edges = {
        (src, etype): edata
        for (src, dst, etype), edata in edges.items()
        if dst == node_id
    }

    segments = [
        (dst, edata["weight"])
        for (dst, etype), edata in out_edges.items()
        if etype == "has_segment"
    ]
    leaders = [
        dst
        for (dst, etype) in out_edges.keys()
        if etype == "leader"
    ]
    suppliers = [
        (src, edata["weight"])
        for (src, etype), edata in in_edges.items()
        if etype == "supplier_of"
    ]
    affected_by = [
        (src, edata["weight"])
        for (src, etype), edata in in_edges.items()
        if etype == "affected_by"
    ]
    ev = evidence.get(node_id, [])

    lines = [
        f"# {node['name']} ({industry_id})",
        "",
    ]
    if layer:
        lines.append(f"**产业链层级**: {layer}")
        lines.append("")

    if segments:
        lines.append("## 产业链节点")
        for seg, w in sorted(segments, key=lambda x: -x[1]):
            lines.append(f"- `{seg}` (权重 {w:.2f})")
        lines.append("")

    if leaders:
        lines.append(f"## 龙头公司 ({len(leaders)} 个)")
        for sym in sorted(leaders):
            lines.append(f"- **{sym}**")
        lines.append("")

    if suppliers:
        lines.append(f"## 供应商关系 ({len(suppliers)} 条)")
        for src, w in sorted(suppliers, key=lambda x: -x[1])[:10]:
            lines.append(f"- ← `{src}` (强度 {w:.2f})")
        lines.append("")

    if affected_by:
        lines.append(f"## 受政策影响 ({len(affected_by)} 条)")
        for pol, w in sorted(affected_by, key=lambda x: -x[1]):
            lines.append(f"- ← **{pol}** (关联 {w:.2f})")
        lines.append("")

    if ev:
        lines.append(f"## 证据来源 ({len(ev)} 条)")
        for e in ev[:5]:
            snippet = (e.get("snippet") or "")[:80].replace("\n", " ")
            lines.append(f"- `[{e['source']}]` {snippet}...")
        lines.append("")

    return "\n".join(lines)


def _render_company(node_id: str, node: dict,
                     edges: dict, evidence: dict) -> str:
    """渲染公司卡片。"""
    ev = evidence.get(node_id, [])

    # 找所有入边（公司被哪些行业/节点关注）
    in_edges = {
        (src, etype): edata
        for (src, dst, etype), edata in edges.items()
        if dst == node_id
    }
    industries = [src for (src, etype) in in_edges.keys() if etype == "leader"]
    suppliers  = [src for (src, etype) in in_edges.keys() if etype == "supplier_of"]
    policies   = [src for (src, etype) in in_edges.keys() if etype == "affected_by"]

    lines = [
        f"# {node['name']} ({node_id})",
        "",
        f"**类型**: {node['type']}",
        "",
    ]

    if industries:
        lines.append(f"## 所属行业 ({len(industries)} 个)")
        for ind in sorted(industries):
            lines.append(f"- {ind}")
        lines.append("")

    if suppliers:
        lines.append(f"## 供应关系 ({len(suppliers)} 条)")
        for src, edata in sorted(suppliers, key=lambda x: -x[1][0])[:8]:
            w = edata["weight"]
            lines.append(f"- ← `{src}` (强度 {w:.2f})")
        lines.append("")

    if policies:
        lines.append(f"## 受政策影响 ({len(policies)} 条)")
        for pol in sorted(policies):
            lines.append(f"- ← **{pol}**")
        lines.append("")

    if ev:
        lines.append(f"## 证据来源 ({len(ev)} 条)")
        for e in ev[:5]:
            snippet = (e.get("snippet") or "")[:80].replace("\n", " ")
            lines.append(f"- `[{e['source']}]` {snippet}...")
        lines.append("")

    return "\n".join(lines)


def _render_policy(node_id: str, node: dict,
                   edges: dict, evidence: dict) -> str:
    """渲染政策卡片。"""
    in_edges = {
        (src, etype): edata
        for (src, dst, etype), edata in edges.items()
        if dst == node_id
    }
    affected = [
        (src, edata["weight"])
        for (src, etype), edata in in_edges.items()
        if etype == "affected_by"
    ]
    ev = evidence.get(node_id, [])

    lines = [
        f"# {node['name']}",
        "",
        f"**政策ID**: `{node_id}`",
        "",
    ]

    if affected:
        lines.append(f"## 影响实体 ({len(affected)} 个)")
        for ent, w in sorted(affected, key=lambda x: -x[1]):
            lines.append(f"- `{ent}` (关联 {w:.2f})")
        lines.append("")

    if ev:
        lines.append(f"## 证据来源 ({len(ev)} 条)")
        for e in ev[:5]:
            snippet = (e.get("snippet") or "")[:80].replace("\n", " ")
            lines.append(f"- `[{e['source']}]` {snippet}...")
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 索引生成
# ─────────────────────────────────────────────────────────────────────────────

def _build_index(nodes: dict, edges: dict) -> str:
    industries = [(nid, n) for nid, n in nodes.items() if n["type"] == "industry"]
    segments   = [(nid, n) for nid, n in nodes.items() if n["type"] == "segment"]
    companies  = [(nid, n) for nid, n in nodes.items() if n["type"] == "company"]
    policies   = [(nid, n) for nid, n in nodes.items() if n["type"] == "policy"]

    lines = [
        "# Wiki Index",
        "",
        f"> 自动生成于 {_now()}。",
        f"> 共 {len(nodes)} 节点 / {len(edges)} 边。",
        "",
        "## 行业 (Industries)",
    ]
    for nid, n in sorted(industries):
        segs = sum(1 for (s,d,t) in edges if s == nid and t == "has_segment")
        leads = sum(1 for (s,d,t) in edges if d == nid and t == "leader")
        lines.append(f"- [[industry/{nid}|{n['name']}]] ({segs} 细分 / {leads} 龙头)")

    lines += ["", "## 产业链节点 (Segments)"]
    for nid, n in sorted(segments):
        ind = nid.split(":")[0] if ":" in nid else ""
        lines.append(f"- [[industry/{ind}|{nid}]] ({n['name']})")

    lines += ["", "## 公司 (Companies)"]
    for nid, n in sorted(companies):
        lines.append(f"- [[company/{nid}|{n['name']}]]")

    lines += ["", "## 政策 (Policies)"]
    for nid, n in sorted(policies):
        lines.append(f"- [[policy/{nid}|{n['name']}]]")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 主逻辑
# ─────────────────────────────────────────────────────────────────────────────

def sync(write: bool = True, db_path: str | None = None) -> dict:
    """同步 SQLite graph → llmwiki/wiki/."""
    import sqlite3
    from pathlib import Path as _Path

    stats = {"industries": 0, "companies": 0, "policies": 0,
             "edges": 0, "evidence": 0, "errors": []}

    _conn = get_connection(db_path)
    conn = _conn.__enter__()
    try:
        nodes, edges, evidence = _load_graph(conn)
    finally:
        _conn.__exit__(None, None, None)

    if not write:
        return {**stats, "nodes": len(nodes), "edges": len(edges),
                "evidence_total": sum(len(v) for v in evidence.values())}

    # Ensure directories exist
    (_Path(WIKI_ROOT) / "industry").mkdir(parents=True, exist_ok=True)
    (_Path(WIKI_ROOT) / "company").mkdir(parents=True, exist_ok=True)
    (_Path(WIKI_ROOT) / "policy").mkdir(parents=True, exist_ok=True)

    updated: list[str] = []

    for node_id, node in nodes.items():
        ntype = node["type"]
        name  = node["name"]
        attrs = node["attrs"]
        updated_at = node.get("updated_at", _now())
        ev = evidence.get(node_id, [])

        # 来源收集（前 16 条 evidence 作为 sources）
        sources = []
        for e in ev[:16]:
            h = _hash16(f"{e['source']}:{e['hash']}")
            sources.append(h)

        # 渲染
        fm = _frontmatter(node_id, ntype, name, sources, updated_at)

        if ntype == "industry":
            body = _render_industry(node_id, node, edges, evidence)
            path = WIKI_ROOT / "industry" / f"{_slug(node_id)}.md"
            stats["industries"] += 1
        elif ntype == "segment":
            # segment 不单独成文件，并入行业卡片
            continue
        elif ntype == "company":
            body = _render_company(node_id, node, edges, evidence)
            slug = _slug(node_id)
            path = WIKI_ROOT / "company" / f"{slug}.md"
            stats["companies"] += 1
        elif ntype == "policy":
            body = _render_policy(node_id, node, edges, evidence)
            slug = _slug(node_id)
            path = WIKI_ROOT / "policy" / f"{slug}.md"
            stats["policies"] += 1
        else:
            continue

        path.write_text(fm + "\n" + body + "\n", encoding="utf-8")
        updated.append(str(path.relative_to(WIKI_ROOT)))
        stats["evidence"] += len(ev)

    stats["edges"] = len(edges)

    # 写入索引
    index_md = _build_index(nodes, edges)
    (WIKI_ROOT / "index.md").write_text(index_md + "\n", encoding="utf-8")
    updated.append("index.md")

    # 追加日志
    log_line = f"## {_now()} | nodes={len(nodes)} edges={len(edges)} evidence={stats['evidence']}"
    log_path = WIKI_ROOT / "log.md"
    if log_path.exists():
        old = log_path.read_text(encoding="utf-8")
    else:
        old = "# Wiki Log\n\n> 追加式同步记录。\n\n"
    log_path.write_text(old + log_line + "\n", encoding="utf-8")
    updated.append("log.md")

    return {**stats, "files": updated}


if __name__ == "__main__":
    import sys
    dry = "--dry" in sys.argv
    result = sync(write=not dry)
    print(result)
    if dry:
        print("(dry run — no files written)")
