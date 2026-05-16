from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LiveGuard:
    """交易前置安全闸门。

    原有字段向后兼容；Phase 5 新增：
      symbol_whitelist    — 允许交易的标的集合（空集合表示全部允许）
      symbol_blacklist    — 禁止交易的标的集合（黑名单，从图谱风险节点联动）
      max_single_notional — 单笔最大名义金额（元），0 表示不限
      max_daily_orders    — 每日最大下单次数，0 表示不限
    """

    require_manual_confirmation: bool = True
    max_consecutive_losses: int = 3
    max_slippage_bp: float = 30.0

    # Phase 5 新增字段
    symbol_whitelist: set = field(default_factory=set)
    symbol_blacklist: set = field(default_factory=set)
    max_single_notional: float = 0.0    # 0 = 不限
    max_daily_orders: int = 0           # 0 = 不限

    # ── 原有接口（不变）──────────────────────────────────────────────────────

    def can_place_live_order(
        self,
        manual_confirmed: bool,
        consecutive_losses: int,
        slippage_bp: float,
    ) -> tuple[bool, str]:
        if self.require_manual_confirmation and not manual_confirmed:
            return False, "manual_confirmation_required"
        if consecutive_losses > self.max_consecutive_losses:
            return False, "consecutive_loss_limit"
        if slippage_bp > self.max_slippage_bp:
            return False, "slippage_limit"
        return True, "ok"

    # ── Phase 5 新接口 ────────────────────────────────────────────────────────

    def check_order(
        self,
        symbol: str,
        notional: float,
        daily_order_count: int = 0,
    ) -> tuple[bool, str]:
        """Pre-trade 检查：白名单 / 黑名单 / 单笔上限 / 日内上限。

        Args:
            symbol: 标的代码
            notional: 本次下单名义金额（price × qty）
            daily_order_count: 当前交易日已下单次数

        Returns:
            (allowed: bool, reason: str)
        """
        if self.symbol_whitelist and symbol not in self.symbol_whitelist:
            return False, "symbol_not_in_whitelist"

        if symbol in self.symbol_blacklist:
            return False, "symbol_in_blacklist"

        if self.max_single_notional > 0 and notional > self.max_single_notional:
            return False, "single_notional_limit"

        if self.max_daily_orders > 0 and daily_order_count >= self.max_daily_orders:
            return False, "daily_order_limit"

        return True, "ok"

    def update_blacklist_from_graph(self, risk_symbols: set) -> None:
        """从知识图谱风险节点更新黑名单（追加，不清空已有黑名单）。

        Args:
            risk_symbols: 风险标的集合
        """
        self.symbol_blacklist.update(risk_symbols)
