"""推送通知模块（Phase 6）

支持:
  - PushPlus（微信通知，token 来自 config.yaml notification.pushplus_token）
  - 打印到控制台（无 token 时兜底）

软导入 requests，未安装时降级为打印。

用法:
    from research.notifier import Notifier
    from utils.config import cfg
    notifier = Notifier.from_cfg(cfg)
    notifier.send("你好", title="量化日报")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_PUSHPLUS_URL = "https://www.pushplus.plus/send"


@dataclass
class Notifier:
    """多渠道推送通知器。

    Args:
        pushplus_token: PushPlus token（空字符串时仅打印）
        dingtalk_webhook: 钉钉 Webhook URL（预留，Phase 7 实现）
        dry_run: True 时仅打印，不发送网络请求
    """
    pushplus_token: str = ""
    dingtalk_webhook: str = ""
    dry_run: bool = False

    @classmethod
    def from_cfg(cls, cfg) -> "Notifier":
        """从 utils.config.cfg 构建 Notifier。"""
        try:
            notification = cfg.get("notification", {}) or {}
            return cls(
                pushplus_token=notification.get("pushplus_token", "") or "",
                dingtalk_webhook=notification.get("dingtalk_webhook", "") or "",
            )
        except Exception:
            return cls()

    def send(self, content: str, title: str = "量化通知") -> bool:
        """发送通知。

        Returns:
            True 表示发送成功（或 dry_run），False 表示失败
        """
        if self.dry_run:
            logger.info("[Notifier dry_run] title=%s\n%s", title, content)
            return True

        if not self.pushplus_token or self.pushplus_token.startswith("${"):
            logger.info("[Notifier] 无 pushplus_token，仅打印\n%s: %s", title, content[:200])
            return True

        return self._send_pushplus(content, title)

    def _send_pushplus(self, content: str, title: str) -> bool:
        try:
            import requests
            resp = requests.post(
                _PUSHPLUS_URL,
                json={
                    "token": self.pushplus_token,
                    "title": title,
                    "content": content,
                    "template": "markdown",
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("code") == 200:
                logger.info("[Notifier] PushPlus 发送成功 msg_id=%s", data.get("data"))
                return True
            else:
                logger.warning("[Notifier] PushPlus 返回错误: %s", data)
                return False
        except ImportError:
            logger.warning("[Notifier] requests 未安装，跳过推送")
            return False
        except Exception as exc:
            logger.error("[Notifier] PushPlus 请求失败: %s", exc)
            return False

    def should_alert(self, payload: dict) -> list[str]:
        """根据 payload 判断是否触发告警，返回告警原因列表。

        触发条件（来自 config.yaml notification.triggers 约定）：
          - pipeline_ok=False → 流水线有失败步骤
          - ml_backtest.max_drawdown < -0.15 → 最大回撤超限
          - data.bars_inserted == 0 → 数据缺失
        """
        reasons: list[str] = []

        if not payload.get("pipeline_ok", True):
            errors = payload.get("step_errors", {})
            reasons.append(f"流水线步骤失败: {list(errors.keys())}")

        ml = payload.get("ml_backtest", {}) or {}
        drawdown = ml.get("max_drawdown", 0) or 0
        if drawdown < -0.15:
            reasons.append(f"最大回撤超限: {drawdown:.2%}")

        data = payload.get("data", {}) or {}
        if data.get("bars_inserted", -1) == 0:
            reasons.append("数据缺失: 今日行情 bars_inserted=0")

        return reasons
