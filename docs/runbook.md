# 量化交易系统运维手册（Runbook）

> 版本：Phase 6（2026-05）  
> 维护人：单人/兼职模式，本地优先

---

## 1. 日常运维流程

### 1.1 每日流水线（核心操作）

```bash
# 标准执行（无推送）
python run.py --daily-pipeline

# 带微信推送
python run.py --daily-pipeline --notify

# 仅验证导入链路（不执行网络请求）
python run.py --daily-pipeline --dry-run
```

流水线步骤（按序，失败隔离互不影响）：

| 步骤 | 模块 | 说明 |
|------|------|------|
| data | `scripts/update_data_store.py` | 行情 + 新闻摄取到 SQLite |
| knowledge | `scripts/update_knowledge.py` | 知识卡片更新 |
| events | `scripts/update_events.py` | 行业事件打分 |
| ml_train | `scripts/train_ml_strategy.py` | Walk-forward ML 训练 |
| ml_backtest | `scripts/run_ml_backtest.py` | ML 策略回测 |
| reconcile | `execution/reconciliation.py` | 三方对账（信号 vs 成交） |

### 1.2 定时任务（Cron / 任务计划程序）

Windows 任务计划程序示例（每天 09:00）：

```
Program:  python
Arguments: D:\github-repo\quant-trading\run.py --daily-pipeline --notify
Start in:  D:\github-repo\quant-trading
```

或 Linux cron：

```cron
0 9 * * 1-5 cd /path/to/quant-trading && python run.py --daily-pipeline --notify >> logs/cron.log 2>&1
```

---

## 2. 数据底座

### 2.1 SQLite 数据库

默认路径：`data/cache/quant_data.db`

主要表：

| 表 | 说明 |
|----|------|
| `market_bars` | OHLCV 行情（source 区分提供者）|
| `news_items` | 新闻（content_hash 去重）|
| `industry_events` | 行业事件（policy/sentiment/propagated 分） |
| `financial_reports` | 财报基本面数据 |
| `pipeline_runs` | 流水线执行记录 |
| `reconcile_reports` | 对账报告（is_clean, 差异详情）|
| `knowledge_nodes/edges` | 知识图谱节点与边 |

### 2.2 数据提供者路由

配置（`config.yaml providers` 段）：

```yaml
providers:
  a_share_order: [sina, akshare, tushare]
  us_order: [polygon, yfinance]
  tushare:
    token: ""     # 填入后自动激活
  polygon:
    api_key: ""   # 填入后自动激活
```

路由逻辑：纯数字代码 → A股链；字母/混合 → 美股链。  
提供者 `is_available()=False` 时自动跳过，全部失败抛 `RuntimeError`。

---

## 3. 策略与回测

### 3.1 策略子命令

```bash
python run.py --long-alpha --symbol 510300 --start 20230101 --end 20241231
python run.py --event-driven --symbol 510300
python run.py --regime-portfolio --symbol 510300
python run.py --compare
python run.py --etf
python run.py --wf
```

### 3.2 信号契约

所有策略输出 DataFrame 须包含：

| 列 | 类型 | 含义 |
|----|------|------|
| `signal` | int (1/-1/0) | 买入/卖出/持仓不变 |
| `position` | int (1/0) | 是否持仓（旗标）|

`BacktestEngine.run(data, signals)` 直接消费此格式。

---

## 4. 执行链路

### 4.1 VeighNa 模拟适配器

```python
from execution.broker_veighna import VeighNaBrokerAdapter
broker = VeighNaBrokerAdapter(dry_run=True, initial_cash=100_000)
order = broker.place_order("510300", "BUY", 4.50, 1000)
```

**注意**：Phase 6 阶段 `dry_run` 必须为 `True`（R4 风控约束）。  
Phase 7 真实柜台接入时才可设为 `False`。

### 4.2 LiveGuard pre-trade 检查

```python
from execution.live_guard import LiveGuard
guard = LiveGuard(
    symbol_whitelist={"510300", "510500"},
    max_single_notional=100_000,
    max_daily_orders=10,
)
ok, reason = guard.check_order("510300", notional=45_000, daily_order_count=2)
```

### 4.3 三方对账

```python
from execution.reconciliation import Reconciler
rec = Reconciler()
report = rec.reconcile(signals_df, trades_list, positions_dict, date="2024-01-15")
print(report.is_clean)  # True / False
```

---

## 5. 通知告警

### 5.1 配置

```yaml
notification:
  enabled: true
  pushplus_token: "${PUSHPLUS_TOKEN}"   # 在 .env 中设置
  dingtalk_webhook: ""
```

### 5.2 告警触发条件

| 条件 | 触发阈值 |
|------|---------|
| 流水线步骤失败 | 任意步骤异常 |
| 最大回撤超限 | `max_drawdown < -15%` |
| 数据缺失 | `bars_inserted == 0` |

手动测试通知：

```python
from research.notifier import Notifier
from utils.config import cfg
n = Notifier.from_cfg(cfg)
n.send("测试消息", title="量化告警测试")
```

---

## 6. 开发工作流

```bash
# 安装依赖
python -m pip install -r requirements.txt

# 运行所有测试
python -m pytest

# 单文件测试
python -m pytest tests/test_phase6_pipeline.py -v

# Make 快捷命令
make test
make lint
```

### 6.1 Feature Flag

所有重型组件默认关闭，通过 `config.yaml` 开启：

```yaml
knowledge:
  graph:
    enabled: false   # 改为 true 启用知识图谱构建
filings:
  enabled: false
policy:
  enabled: false
sentiment:
  enabled: false
```

---

## 7. 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `RuntimeError: no provider succeeded` | 所有数据提供者不可用 | 检查网络/API Key |
| `reconcile_reports` 表不存在 | schema 未初始化 | `get_connection()` 自动创建；或删除旧 DB 重新生成 |
| PushPlus 推送无效 | Token 未配置或过期 | 在 `.env` 中更新 `PUSHPLUS_TOKEN` |
| `dry_run=False` 报错 | Phase 6 R4 风控约束 | Phase 7 前保持 `dry_run=True` |
| import 失败（akshare/tushare/vnpy）| 包未安装 | `pip install akshare` 等；`is_available()` 会自动跳过 |

---

## 8. Phase 7 升级路线（参考）

| 组件 | 当前（轻量） | Phase 7（重型） |
|------|------------|----------------|
| NLP | SnowNLP | FinBERT |
| 图数据库 | NetworkX+SQLite | Neo4j |
| ML 模型 | 线性 baseline | PyG GNN / RL |
| 执行层 | dry-run | VeighNa 真实柜台 |
| 回测框架 | 自研 engine | Vectorbt / Qlib |
