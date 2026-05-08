# 量化交易系统 (Quantitative Trading System)

A股ETF量化回测 + 策略验证系统。

## 项目状态

> ⚠️ **重要结论**：经过5年历史数据 + Walk-Forward验证，当前简单技术指标策略**无法稳定跑赢买入持有基准**。不建议用于实盘。

## 功能模块

```
quant-trading/
├── data/
│   ├── fetcher.py          # 数据获取（新浪财经API，5年+历史）
│   └── cache/              # 本地缓存
├── strategies/
│   ├── trend.py            # 趋势策略：MA_Cross, MACD, Breakout
│   ├── mean_reversion.py   # 均值回归：RSI, BollingerBand, KD
│   └── base.py             # 策略基类
├── backtest/
│   ├── engine.py           # 回测引擎（V1基础版）
│   └── risk.py             # 风控模块（V2增强版：止损/仓位/熔断）
├── execution/
│   └── paper.py            # 模拟交易执行器
├── scripts/
│   └── walk_forward.py     # Walk-Forward滚动验证
└── run.py                  # 主入口
```

## 快速开始

```bash
cd /Users/tanwei/quant-trading
source .venv/bin/activate

# ETF多策略对比
python run.py --etf

# 带风控回测
python run.py --etf --risk

# 完整5年回测
python run.py --all

# Walk-Forward验证
python run.py --wf

# 单策略回测
python run.py --strategy MA_Cross --symbol 510300 --bt
```

## 回测结果（2023-2024）

| 策略 | 沪深300(510300) | 中证500(510500) | 创业板(159915) |
|------|-----------------|-----------------|----------------|
| MA(5,20) | -2.6% | -1.3% | +2.4% |
| MA(10,60) | +2.0% | +8.1% | +11.2% |
| MACD | -1.8% | +4.2% | +7.6% |
| Breakout(20) | -5.4% | -3.1% | +1.2% |
| 买入持有 | +1.9% | +1.8% | +5.6% |

## Walk-Forward验证结论（训练252天/测试63天）

| ETF | 最佳策略 | 平均夏普 | 跑赢基准概率 | 结论 |
|-----|---------|---------|-------------|------|
| 沪深300 | MA(10,60) | -0.21 | 45% | ❌ 无效 |
| 中证500 | MA(10,60) | -0.24 | 44% | ❌ 无效 |
| 创业板 | MA(10,60) | -0.38 | 43% | ❌ 无效 |

> 跑赢基准概率≈45%≈随机（50%），策略无实际预测能力。

## 风控模块 (backtest/risk.py)

```python
from backtest.risk import BacktestEngineV2, PositionConfig

cfg = PositionConfig(
    base_ratio=0.8,        # 仓位80%
    stop_loss=0.07,        # 7%固定止损
    trailing_stop=True,     # 启用跟踪止损
    trailing_pct=0.05,      # 5%跟踪
    daily_loss_limit=0.07,  # 日熔断7%
)
engine = BacktestEngineV2(initial_capital=100_000, risk_config=cfg)
result = engine.run(data, signals)
```

## 数据说明

- **来源**：新浪财经API（`money.finance.sina.com.cn`）
- **频率**：日线
- **缓存**：本地pickle，路径 `data/cache/`
- **5年数据**：2019-01-01 ~ 2024-12-31
- **覆盖**：ETF、股票、指数

## 下一步方向

1. **引入基本面数据**（PE、PB、财务报表）—— 当前纯技术指标不够
2. **多因子策略** —— 价值 + 动量 + 质量因子组合
3. **跨资产配置** —— 股债轮动、全球配置
4. **实盘对接** —— QMT/同花顺 API（需券商账号）

## 免责声明

本系统仅供学习研究，不构成投资建议。回测结果不代表未来收益，量化策略有重大亏损风险。
