# Phase 4 策略层设计规格

> 日期：2026-05-16  
> 约束：单人 / 本地优先 / scipy（已有）/ 无 RL

---

## 目标

在现有回测框架上增加三层：
1. **长线 Alpha 策略**（`value_long.py`）：护城河 + 政策对齐 + 情感三因子合成信号
2. **事件驱动策略**（`event_driven.py`）：消费 `industry_events.propagated_score` + MACD 过滤
3. **投资组合层**（`portfolio/`）：MVO 权重优化 + Regime 规则化调度

---

## 架构总图

```
DB(financial_reports)   DB(industry_events)
        │                      │
        ▼                      ▼
ValueLongStrategy        EventDrivenStrategy
  .generate(ohlcv)         .generate(ohlcv)
  → signal/position        → signal/position
        │                      │
        └──────┬────────────────┘
               ▼
        MVOptimizer.optimize(returns)
        → {strategy: weight}
               │
               ▼
        RegimeDetector.detect(price, sentiment)
        → regime: bull/neutral/bear
               │
               ▼
        combined weights → BacktestEngine
```

---

## 组件设计

### 1. `strategies/value_long.py`

**信号逻辑：**

```
composite = 0.4 * (moat_score / 5.0)
          + 0.3 * policy_score
          + 0.3 * ((avg_sentiment + 1) / 2)   # 映射 [-1,1] → [0,1]

if composite > buy_threshold (默认 0.55):  signal = 1
elif composite < sell_threshold (默认 0.45): signal = -1
else: signal = 0
```

**降级策略：**
- 无 DB 连接时：moat_score=2.5（中性），policy_score=0，avg_sentiment=0
- `generate(data)` 中 `conn=None` 时用 SMA 20/60 金叉替代复合因子

**接口：**
```python
class ValueLongStrategy(Strategy):
    def __init__(self, buy_threshold=0.55, sell_threshold=0.45,
                 weights=(0.4, 0.3, 0.3), db_path=None): ...
    def generate(self, data: pd.DataFrame) -> pd.DataFrame: ...
    def _load_scores(self, symbol: str, conn) -> tuple[float, float, float]:
        """返回 (moat_score, policy_score, avg_sentiment)"""
```

---

### 2. `strategies/event_driven.py`

**信号逻辑：**

```
从 industry_events 取最近 window 天内该 industry/symbol 的 propagated_score 均值
MACD 过滤：only act when MACD line > Signal line (上升趋势)

event_score = mean(propagated_score[-window:])
if event_score > pos_threshold (0.2) AND macd_bullish: signal = 1
elif event_score < neg_threshold (-0.2) AND macd_bearish: signal = -1
else: signal = 0
```

**接口：**
```python
class EventDrivenStrategy(Strategy):
    def __init__(self, industry=None, symbol=None,
                 window=7, pos_threshold=0.2, neg_threshold=-0.2,
                 db_path=None): ...
    def generate(self, data: pd.DataFrame) -> pd.DataFrame: ...
    def _get_event_scores(self, conn, dates: list[str]) -> pd.Series:
        """按日期返回 propagated_score Series，缺失填 0"""
```

---

### 3. `portfolio/optimizer.py`

**MVOptimizer：最大化 Sharpe 比率（scipy SLSQP）**

```python
class MVOptimizer:
    def optimize(
        self,
        returns: pd.DataFrame,        # T × N，列为策略名
        risk_free_rate: float = 0.0,
    ) -> dict[str, float]:
        """
        最大化 Sharpe = (μ - rf) / σ（年化）
        约束：∑w = 1，0 ≤ wᵢ ≤ 1
        returns 不足 2 行时返回等权
        """
```

---

### 4. `portfolio/regime_gating.py`

**RegimeDetector：三档规则**

| 指标 | bull | neutral | bear |
|---|---|---|---|
| 滚动20日年化波动率 | < 0.15 | 0.15–0.25 | > 0.25 |
| 60日最大回撤 | > -0.05 | -0.05~-0.15 | < -0.15 |
| 平均情感（industry_events均值） | > 0.1 | -0.1~0.1 | < -0.1 |

三个指标投票（bull=+1，bear=-1，neutral=0），sum > 0 → bull；sum < 0 → bear；else → neutral。

**策略权重：**

| regime | long_alpha 权重 | event_driven 权重 |
|---|---|---|
| bull | 0.7 | 0.3 |
| neutral | 0.5 | 0.5 |
| bear | 0.3 | 0.7 |

```python
class RegimeDetector:
    def detect(
        self,
        price: pd.Series,
        avg_sentiment: float = 0.0,
        vol_window: int = 20,
        dd_window: int = 60,
    ) -> str:
        """返回 'bull' | 'neutral' | 'bear'"""

    def get_weights(self, regime: str) -> dict[str, float]:
        """返回 {'long_alpha': w1, 'event_driven': w2}"""
```

---

### 5. `run.py` 新增子命令

- `--long-alpha`：下载沪深300ETF 510300（20230101-20241231），运行 `ValueLongStrategy`，打印回测结果
- `--event-driven`：同一数据，运行 `EventDrivenStrategy`，打印回测结果  
- `--regime-portfolio`：运行两策略，MVO 权重 + Regime 调度，打印组合指标

---

## 测试计划（≥16 用例）

| 模块 | 用例 |
|---|---|
| value_long | 无 DB 降级返回合法 signal/position；信号契约满足（含 -1/0/1）；高 composite→buy；低→sell |
| event_driven | 无事件时 signal=0；正事件+MACD上涨→buy；负事件→sell；MACD 过滤生效 |
| optimizer | 等权降级（数据不足）；权重和=1；权重∈[0,1]；Sharpe 最大化方向正确 |
| regime_gating | bull/neutral/bear 三种检测；get_weights 权重和=1；极端输入不崩溃 |
| integration | 两策略 generate 输出均含 signal/position；run.py --long-alpha 可调用不报错 |

---

## 验收标准

1. `python -m pytest -q` → **≥ 123 passed**（107 旧 + 16 新）
2. `python run.py --long-alpha` 打印回测结果（年化、夏普、回撤）
3. `python run.py --regime-portfolio` 打印组合权重和指标
4. 两种策略均输出 `signal` 和 `position` 列，与 `BacktestEngine.run()` 兼容
