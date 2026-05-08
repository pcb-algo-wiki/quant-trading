# Quant Trading System

> **目标**: 构建一个可持续盈利的量化交易系统

## 系统架构

```
data/          # 数据层：采集、存储、清洗
├── fetcher.py  # 数据获取（东方财富、AKShare）
├── storage.py  # 本地存储
└── cleaner.py  # 数据清洗

strategies/    # 策略层：信号生成
├── base.py     # 策略基类
├── trend.py    # 趋势策略（双均线、MACD）
├── mean_rev.py # 均值回归策略（布林带、RSI）
└── multi_factor.py  # 多因子策略

backtest/      # 回测层：验证策略有效性
├── engine.py   # 回测引擎
├── optimizer.py  # 参数优化
└── validator.py  # Walk-forward验证

execution/     # 执行层：模拟/实盘
├── paper.py    # 模拟交易
└── broker.py   # 券商接口

dashboard/     # 可视化层
├── app.py      # Flask看板
└── templates/  # HTML模板

utils/         # 工具
├── risk.py     # 风险管理
├── analytics.py # 绩效分析
└── config.py   # 配置管理
```

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env

# 1. 数据获取
python -m data.fetcher --stock 000001 --start 20230101

# 2. 运行回测
python -m backtest.engine --strategy trend_ma --stock 000001

# 3. 启动看板
python -m dashboard.app
```

## 当前策略

| 策略 | 类型 | 状态 | 年化 | 夏普 |
|------|------|------|------|------|
| MA_Cross(5,20) | 趋势 | ✅ | -10% | -0.43 |
| RSI(14) | 均值回归 | 🔨 | - | - |
| BollingerBand | 均值回归 | 🔨 | - | - |

## 核心指标

- 年化收益率 > 10%
- 最大回撤 < 15%
- 夏普比率 > 1.0
- 交易次数 > 20次/年

## Roadmap

- [x] 数据层搭建
- [x] 双均线策略回测
- [ ] 多策略组合
- [ ] Walk-forward验证
- [ ] 模拟交易接入
- [ ] 实时看板
- [ ] 实盘对接
