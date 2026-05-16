from __future__ import annotations

from datetime import datetime


def build_daily_summary(
    payload: dict,
    timings: dict | None = None,
    errors: dict | None = None,
) -> str:
    """生成每日流水线摘要字符串（Markdown 兼容）。

    Args:
        payload: run_daily_pipeline() 返回的 result dict
        timings: 各步骤耗时 {step_name: seconds}
        errors:  各步骤错误 {step_name: error_msg}

    Returns:
        人类可读的摘要字符串，可直接推送微信/钉钉
    """
    timings = timings or {}
    errors = errors or {}

    data       = payload.get("data", {})
    events     = payload.get("events", {})
    ml_train   = payload.get("ml_train", {})
    ml_backtest= payload.get("ml_backtest", {})
    reconcile  = payload.get("reconcile", {})
    pipeline_ok= payload.get("pipeline_ok", len(errors) == 0)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    status_icon = "✅" if pipeline_ok else "⚠️"

    lines = [
        f"## {status_icon} 量化日报  {now}",
        "",
        "### 数据摄取",
        f"- 行情 bars：{data.get('bars_inserted', 0)} 条",
        f"- 新闻条数：{data.get('news_inserted', 0)} 条",
        "",
        "### 事件与知识",
        f"- 行业事件：{events.get('event_count', 0)} 条",
        f"- 行业数量：{events.get('industry_count', 0)}",
        "",
        "### ML 评估",
        f"- Walk-forward 窗口：{ml_train.get('n_windows', 0)}",
        f"- 平均 MSE：{ml_train.get('avg_mse', 0):.4f}" if ml_train.get('avg_mse') else "- 平均 MSE：N/A",
        f"- 策略总收益：{ml_backtest.get('total_return', 0):.2%}" if ml_backtest.get('total_return') is not None else "- 策略总收益：N/A",
        "",
        "### 对账",
        f"- 对账状态：{'✅ 干净' if reconcile.get('is_clean', True) else '⚠️ 有差异'}",
        f"- 报告 ID：{reconcile.get('reconcile_report_id', 'N/A')}",
    ]

    # 步骤耗时（排除空值）
    if timings:
        lines += ["", "### 步骤耗时（秒）"]
        for step, elapsed in timings.items():
            lines.append(f"- {step}：{elapsed}s")

    # 失败步骤
    if errors:
        lines += ["", "### ⚠️ 失败步骤"]
        for step, msg in errors.items():
            lines.append(f"- **{step}**：{msg[:120]}")

    return "\n".join(lines)
