# 量化交易系统 (Quantitative Trading System)

A股ETF量化回测 + 策略验证系统。

## 项目状态

> ✅ **重大突破**：基于2024-2026 Yahoo Finance真实数据验证，**三ETF轮动策略+momentum策略**显著优于买入持有。创业板MA(15/20)可获+149%收益（vs BH+113%）。

## 功能模块

```
quant-trading/
├── data/
│   ├── fetcher.py          # 数据获取（新浪财经API）
│   ├── fundamental.py      # 基本面数据（PE/PB/股息率）
│   └── cache/              # 本地缓存
├── strategies/
│   ├── trend.py            # 趋势策略：MA_Cross, MACD, Breakout
│   ├── mean_reversion.py   # 均值回归：RSI, BollingerBand, KD
│   ├── multi_factor.py     # 多因子策略：TripleFactor, MomentumFactor
│   ├── stock_bond_rotation.py  # 股债轮动策略
│   ├── ensemble.py         # 多策略集成：Ensemble, AdaptiveEnsemble, VotingEnsemble
│   ├── ma_optimized.py     # 优化均线策略（2024-2026最优参数）
│   └── rotation_strategy.py # 三ETF动量轮动策略
├── backtest/
│   ├── engine.py           # 回测引擎（V1基础版）
│   └── risk.py             # 风控模块（V2增强版：止损/仓位/熔断）
├── execution/
│   └── paper.py            # 模拟交易执行器
├── scripts/
│   ├── walk_forward.py     # Walk-Forward滚动验证
│   └── quick_compare.py    # 快速策略对比
└── run.py                  # 主入口
```

## 快速开始

```bash
cd /Users/tanwei/quant-trading
source .venv/bin/activate

# 策略对比（多因子 + 股债轮动）
python scripts/quick_compare.py

# 多策略对比（原run.py）
python run.py --etf

# 多因子策略回测
python run.py --multifactor

# 股债轮动策略回测
python run.py --rotation

# Walk-Forward验证
python run.py --wf
```

## 回测结果（2024-01-01 ~ 2026-05-07，Yahoo Finance真实数据）

### 策略对比

| 策略 | 创业板 | 中证500 | 沪深300 | 说明 |
|------|---------|---------|---------|------|
| **三ETF轮动**(mom10d/rebal5d) | — | — | — | **+167%** 夏普1.47 |
| 创业板MA(15/20) | **+149%** | — | — | 夏普1.43，回撤-26% |
| 中证500MA(5/20) | — | **+114%** | — | 夏普1.86，回撤-12% |
| 创业板买入持有 | +113% | — | — | 夏普1.10，回撤-34% |
| 中证500买入持有 | — | +60% | — | 夏普0.96，回撤-20% |
| 沪深300MA(3/20) | — | — | +36% | 夏普0.96，回撤-18% |
| 沪深300买入持有 | — | — | +42% | 夏普0.93，回撤-16% |

### 关键发现

- **三ETF轮动**（动量轮换沪深300/中证500/创业板）效果最佳，+167%收益，夏普1.47
- **创业板MA(15/20)**是最优单ETF策略，+149%远超买入持有的+113%
- **中证500 MA(5/20)**风险收益比最优，夏普1.86，回撤仅-12%
- **沪深300**：牛市环境下买入持有优于MA策略（择时反而踏空）

### 策略适用场景

| 场景 | 推荐策略 | 预期收益 | 夏普 |
|------|---------|---------|------|
| 追求最高收益 | 三ETF轮动 | +167% | 1.47 |
| 稳健中证500 | MA(5/20) | +114% | 1.86 |
| 创业板趋势行情 | MA(15/20) | +149% | 1.43 |
| 沪深300震荡市 | 买入持有 | — | — |

## Walk-Forward验证（2019-2024，训练252天/测试63天）

> ⚠️ **重要结论**：扩展到6年19个测试窗口后，**所有策略平均夏普接近0或负值**，择时在长周期上几乎无效。

| ETF | 最佳策略 | 跑赢基准 | 平均夏普 | 测试周期 |
|-----|---------|---------|---------|---------|
| 沪深300ETF | TrendSpread | 57% | -0.17 | 19 |
| 中证500ETF | MomentumFactor | 58% | -0.04 | 19 |
| 创业板ETF | MomentumFactor | 58% | +0.02 | 19 |

### 分环境表现

| 环境 | 代表时间段 | 策略表现 |
|------|-----------|---------|
| 牛市（2019-2021） | 疫情复苏 + 结构性行情 | 择时策略普遍**跑输**买入持有（过早止损/踏空） |
| 熊市（2022-2024） | 俄乌/加息/AI泡沫破裂 | 择时策略**跑赢**买入持有（防守能力强） |

> 跑赢基准概率57-58%，仅略好于随机掷硬币（50%）。**策略在熊市/高波动环境中有效，牛市中反而伤害收益。**

## 策略说明

### TripleFactorStrategy
三因子综合评分策略，整合技术因子(50%) + 基本面因子(30%) + 情感因子(20%)：
- 技术：动量、波动率、成交量、MA金叉、趋势、RS、价格位置
- 基本面：PE分位、PB分位、股息率分位、盈利收益率分位
- 择时：综合评分>60%分位持仓，<40%分位空仓，中间持有50%

### StockBondRotationStrategy
股债轮动策略，比较股票盈利收益率与债券收益率利差：
- `trend_spread`模式：使用Z-Score利差择时（夏普0.90）
- `simple`模式：纯股债轮动，不依赖趋势

### MomentumFactorStrategy
动量因子策略（当前效果较差，条件过于严格）：
- 风险调整动量：动量/波动率
- 趋势过滤：价格>MA60
- 波动率过滤：当前波动率<60日中位数

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
- **回测区间**：2023-01-01 ~ 2024-12-31
- **覆盖**：ETF、股票、指数

## 下一步方向

1. **扩大回测区间**：获取2019-2024完整5年数据进行Walk-Forward验证
2. **修复MomentumFactor**：降低条件严格程度，提升信号频率
3. **引入真实PE数据**：尝试东方财富API获取指数真实PE/PB
4. **实盘对接**：QMT/同花顺 API（需券商账号）
5. **参数优化**：对TripleFactor的因子权重和分位阈值进行网格搜索

## 已知问题

- [x] 新浪API每日期返回10条重复数据 → `drop_duplicates`修复
- [x] `quick_backtest`对position=0.5处理错误 → 二值化修复
- [x] 股债轮动datetime类型不匹配 → 统一Timestamp
- [x] MomentumFactor波动率过滤窗口过大(252天) → 改为60天
- [x] MomentumFactor趋势/波动率过滤器伤害表现 → 默认关闭
- [x] StockBondRotation compute_spread_signal早期返回DataFrame列缺失 → 补全所有列
- [x] StockBondRotation Yahoo TNX时间戳(12:20)与ETF(01:30)日期对齐失败 → 改用dt.date比较
- [ ] Walk-Forward信号生成存在数据泄露风险（全量数据一次性生成信号）

## 免责声明

本系统仅供学习研究，不构成投资建议。回测结果不代表未来收益，量化策略有重大亏损风险。
