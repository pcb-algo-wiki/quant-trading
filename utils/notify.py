"""
utils/notify.py
===============
报警/通知模块

支持：
- PushPlus 微信推送
- 钉钉机器人
- 日志告警

用法:
  from utils.notify import notify, push_daily_report

  # 简单通知
  notify("策略跑起来了", "INFO")

  # 带数据推送
  notify("📊 每日报告", "INFO", data={
    "总收益": "+5.2%",
    "持仓": "创业板ETF 1000股",
    "信号": "买入",
  })
"""

import os
import json
import logging
import requests
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# ============ PushPlus（微信推送）============

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_URL = "http://www.pushplus.plus/send"


def pushplus_send(title: str, content: str, token: str = None) -> bool:
    """
    推送消息到微信（PushPlus）
    
    Args:
        title: 标题
        content: 内容（支持HTML）
        token: PushPlus token（不传则用全局token）
    
    Returns:
        是否成功
    """
    t = token or PUSHPLUS_TOKEN
    if not t:
        logger.warning("[PushPlus] 未配置token，跳过推送")
        return False

    try:
        resp = requests.post(
            PUSHPLUS_URL,
            json={
                "token": t,
                "title": title,
                "content": content,
                "template": "html",
            },
            timeout=10,
        )
        result = resp.json()
        if result.get("code") == 200:
            logger.info(f"[PushPlus] 推送成功: {title}")
            return True
        else:
            logger.error(f"[PushPlus] 推送失败: {result.get('msg')}")
            return False
    except Exception as e:
        logger.error(f"[PushPlus] 推送异常: {e}")
        return False


# ============ 钉钉机器人============

DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")


def dingtalk_send(text: str, webhook: str = None) -> bool:
    """
    推送消息到钉钉机器人
    """
    url = webhook or DINGTALK_WEBHOOK
    if not url:
        logger.warning("[DingTalk] 未配置webhook，跳过推送")
        return False

    try:
        resp = requests.post(
            url,
            json={
                "msgtype": "text",
                "text": {"content": text},
            },
            timeout=10,
        )
        if resp.json().get("errcode") == 0:
            logger.info(f"[DingTalk] 推送成功")
            return True
        return False
    except Exception as e:
        logger.error(f"[DingTalk] 推送异常: {e}")
        return False


# ============ 统一通知接口 ============


def notify(
    message: str,
    level: str = "INFO",
    data: Dict[str, Any] = None,
    pushplus_token: str = None,
    dingtalk_webhook: str = None,
) -> bool:
    """
    统一通知接口（同时推送到所有已配置渠道）
    
    Args:
        message: 通知内容
        level: INFO / WARNING / ERROR
        data: 额外数据（会格式化成表格）
        pushplus_token: PushPlus token（覆盖环境变量）
        dingtalk_webhook: 钉钉webhook
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"[{level}] {message} ({timestamp})"

    # 构建内容
    content_lines = [f"<h3>{message}</h3>", f"<p style='color:#888'>时间: {timestamp}</p>"]

    if data:
        content_lines.append("<table border='1' cellpadding='6' style='border-collapse:collapse;width:100%'>")
        for k, v in data.items():
            content_lines.append(
                f"<tr><td style='color:#555'><b>{k}</b></td>"
                f"<td style='color:#222'>{v}</td></tr>"
            )
        content_lines.append("</table>")

    html_content = "\n".join(content_lines)

    success = True

    # PushPlus
    token = pushplus_token or PUSHPLUS_TOKEN
    if token:
        if not pushplus_send(title, html_content, token):
            success = False
    else:
        logger.info(f"[Notify] {title}（未配置PushPlus，仅打印）")
        print(f"📢 {title}")
        if data:
            for k, v in data.items():
                print(f"   {k}: {v}")

    # DingTalk
    webhook = dingtalk_webhook or DINGTALK_WEBHOOK
    if webhook:
        text_content = f"{message}\n时间: {timestamp}"
        if data:
            for k, v in data.items():
                text_content += f"\n{k}: {v}"
        if not dingtalk_send(text_content, webhook):
            success = False

    return success


# ============ 快捷通知函数 ============


def notify_error(message: str, data: Dict = None):
    """ERROR级别通知"""
    return notify(message, "ERROR", data)


def notify_warning(message: str, data: Dict = None):
    """WARNING级别通知"""
    return notify(message, "WARNING", data)


def notify_info(message: str, data: Dict = None):
    """INFO级别通知"""
    return notify(message, "INFO", data)


# ============ 每日报告推送 ============


def push_daily_report(
    stats: dict,
    positions: list = None,
    signal: str = None,
    news_sentiment: float = None,
    macro_signal: str = None,
) -> bool:
    """
    推送每日量化报告

    Args:
        stats: 账户统计（来自PaperTrader.get_stats()）
        positions: 持仓列表（来自PaperTrader.get_positions_summary()）
        signal: 当前策略信号（buy/hold/sell）
        news_sentiment: 新闻情感得分 0~1
        macro_signal: 宏观信号描述
    """
    equity = stats.get("current_equity", 0)
    ret = stats.get("total_return_pct", "0%")
    cash = stats.get("cash", 0)

    # 标题emoji
    ret_val = float(str(ret).replace("%", ""))
    emoji = "🟢" if ret_val >= 0 else "🔴"

    # 构建内容
    lines = [
        f"<h2>📊 量化日报 {datetime.now().strftime('%Y-%m-%d')}</h2>",
        f"<h3>{emoji} 总收益 {ret} | 权益 {equity:.2f}</h3>",
        f"<p>现金: {cash:.2f} | 持仓: {stats.get('num_positions', 0)}个 | 交易: {stats.get('num_trades', 0)}笔</p>",
    ]

    # 持仓
    if positions:
        lines.append("<h4>📦 持仓</h4>")
        lines.append("<table border='1' cellpadding='5' style='border-collapse:collapse;width:100%'>")
        lines.append("<tr><th>代码</th><th>股数</th><th>成本</th><th>现价</th><th>盈亏</th><th>收益率</th></tr>")
        for p in positions:
            pnl = float(p.get("unrealized_pnl", 0))
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"<tr><td>{p['symbol']}</td>"
                f"<td>{p['shares']:.0f}</td>"
                f"<td>{p['avg_cost']:.3f}</td>"
                f"<td>{p['current_price']:.3f}</td>"
                f"<td>{pnl_emoji} {pnl:.2f}</td>"
                f"<td>{p['return_pct']}</td></tr>"
            )
        lines.append("</table>")

    # 信号
    if signal:
        sig_emoji = {"buy": "🟢买入", "hold": "⚪观望", "sell": "🔴卖出"}.get(signal, signal)
        lines.append(f"<h4>📡 策略信号: {sig_emoji}</h4>")

    if news_sentiment is not None:
        sentiment_emoji = "🟢偏多" if news_sentiment > 0.55 else "🔴偏空" if news_sentiment < 0.45 else "⚪中性"
        lines.append(f"<p>📰 新闻情感: {sentiment_emoji} ({news_sentiment:.2f})</p>")

    if macro_signal:
        lines.append(f"<p>📉 宏观信号: {macro_signal}</p>")

    # 统计
    if stats:
        win_rate = stats.get("win_rate", 0)
        lines.append(
            f"<p>胜率: {win_rate*100:.1f}% | "
            f"盈利: {stats.get('winning_trades', 0)}笔 | "
            f"亏损: {stats.get('losing_trades', 0)}笔</p>"
        )

    content = "\n".join(lines)
    title = f"量化日报 {datetime.now().strftime('%Y-%m-%d')} {emoji} {ret}"

    return notify(title, "INFO", pushplus_token=PUSHPLUS_TOKEN)


# ============ 日志Handler（自动推送ERROR）============

class NotificationHandler(logging.Handler):
    """日志Handler：ERROR级别自动推送"""

    def __init__(self, min_level: int = logging.ERROR):
        super().__init__(level=min_level)
        self.min_level = min_level

    def emit(self, record: logging.LogRecord):
        if record.levelno < self.min_level:
            return
        try:
            msg = self.format(record)
            level_map = {
                logging.ERROR: "ERROR",
                logging.WARNING: "WARNING",
                logging.CRITICAL: "CRITICAL",
            }
            level = level_map.get(record.levelno, "INFO")
            notify(f"[{record.name}] {msg}", level)
        except Exception:
            self.handleError(record)


def setup_notification_handler(logger_name: str = None, level: int = logging.ERROR):
    """为指定logger添加通知Handler"""
    log = logging.getLogger(logger_name)
    handler = NotificationHandler(level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    log.addHandler(handler)
    return handler
