"""
data/chain_validator.py
=======================
产业链事件验证 — 基于历史事件回测信号有效性

核心思想：
  历史事件（政策/产品/资本）发生后，产业链各环节的真实收益统计
  → 用于修正信号权重，形成反馈闭环

验证维度：
  1. 信号强度 vs 后续收益（政策信号是否比资本信号更有效？）
  2. 周期位置 vs 收益（早期布局 vs 中期轮动的胜率）
  3. 节点位置 vs 收益（上游材料 vs 中游制造谁更先涨？）

⚠️ 注意：
  - 需要有历史事件库 + 价格数据才能运行
  - 目前用akshare获取ETF/个股价格，A股个股数据有限
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).parent))

from industry_chain import (
    INDUSTRY_CHAINS, list_chains, ChainNode,
    IndustryEventDB, TrendEvent, ChainLevel, TrendSignal
)

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True, parents=True)


# ============ 名称→股票代码映射 ============

import subprocess
import urllib.parse

_NAME_TO_CODE_CACHE = {}


def name_to_code(name: str) -> Optional[str]:
    """公司名 → A股代码（带缓存）"""
    if not name or len(name) < 2:
        return None

    # 已知的一些名称映射（覆盖产业链图谱中常见的）
    KNOWN = {
        '北方华创': '002371',
        '中微公司': '688012',
        '华大九天': '301269',
        '概伦电子': '688206',
        '芯愿景': '688787',
        '中芯国际': '688981',
        '华虹半导体': '688347',
        '长电科技': '600584',
        '通富微电': '002156',
        '华天科技': '002185',
        '沪硅产业': '688126',
        '立昂微': '605358',
        '中环股份': '002129',
        '容百科技': '688005',
        '当升科技': '300073',
        '德方纳米': '300769',
        '贝特瑞': '688185',
        '璞泰来': '603659',
        '杉杉股份': '600884',
        '天赐材料': '002709',
        '新宙邦': '300037',
        '恩捷股份': '002812',
        '宁德时代': '300750',
        '比亚迪': '002594',
        '中创新航': '003001',
        '赣锋锂业': '002460',
        '天齐锂业': '002466',
        '盐湖股份': '000792',
        '华友钴业': '603799',
        '格林美': '002340',
        '寒锐钴业': '300618',
        '先导智能': '300450',
        '赢合科技': '300457',
        '杭可科技': '688006',
        '汇川技术': '300124',
        '卧龙电驱': '600580',
        '麦格米特': '002851',
        '绿的谐波': '688017',
        '来福谐波': '688787',  # 近似
        '坤维科技': '688710',
        '敏芯股份': '688286',
        '亿航智能': 'EH',  # 美股
        '浪潮信息': '000977',
        '中兴通讯': '000063',
        '中际旭创': '300308',
        '新易盛': '300502',
        '剑桥科技': '603083',
        '特锐德': '300001',
        '星星充电': '002358',
        '英维克': '002837',
        '申菱环境': '002011',
        '艾默生': 'EMR',  # 美股
        '生益科技': '600183',
        '华正新材': '603186',
        '南亚新材': '688539',
        '拓荆科技': '688072',
        '寒武纪': '688256',
        '海光信息': '688041',
        '小鹏汇天': 'XPEV',  # 美股
        '大疆创新': 'DJI',   # 私有
        '道通智能': '688349',
        '禾赛科技': 'HSAI',  # 美股
        '速腾聚创': '2498',  # 港股
        '国家电网': '600795',
        '顺丰无人机': '002352',
        '美团无人机': '3690',  # 港股
    }

    # 先查缓存
    if name in _NAME_TO_CODE_CACHE:
        return _NAME_TO_CODE_CACHE[name]

    # 查已知映射
    if name in KNOWN:
        _NAME_TO_CODE_CACHE[name] = KNOWN[name]
        return KNOWN[name]

    # 实时搜索
    try:
        url = (f"https://searchapi.eastmoney.com/api/suggest/get"
               f"?input={urllib.parse.quote(name)}"
               f"&type=14&token=D43BF722C8E33BDC906FB84D85E326E8"
               f"&count=1")
        r = subprocess.run(
            ['curl', '-s', '--noproxy', '*', '-L', '--max-time', '8', url],
            capture_output=True, text=True, timeout=12
        )
        data = json.loads(r.stdout)
        items = data.get('QuotationCodeTable', {}).get('Data', [])
        if items:
            code = items[0].get('Code', '')
            _NAME_TO_CODE_CACHE[name] = code
            return code
    except Exception:
        pass

    _NAME_TO_CODE_CACHE[name] = None
    return None


def _curl_kline(sec_code: str, days: int = 365) -> str:
    """用curl获取东方财富K线数据（绕过代理）"""
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

    # 判断市场和代码格式
    if sec_code.startswith(('6', '5')):
        market = '1'  # 上海
        sec = sec_code
    elif sec_code.startswith(('0', '3', '002', '000')):
        market = '0'  # 深圳
        sec = sec_code
    else:
        # 尝试直接匹配
        market = '0'
        sec = sec_code

    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6"
           f"&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61%2Cf116"
           f"&ut=7eea3edcaed734bea9cbfc24409ed989"
           f"&klt=101&fqt=1&secid={market}.{sec}&beg={start_date}&end={end_date}")

    result = subprocess.run(
        ['curl', '-s', '--noproxy', '*', '-L', '--max-time', '15', url],
        capture_output=True, text=True, timeout=20
    )
    return result.stdout


def get_price_data(sec_code: str, days: int = 180) -> pd.DataFrame:
    """获取近days天的日线价格（新浪API，绕过代理）"""
    try:
        # 判断市场前缀
        if sec_code.startswith(('6', '5')):
            prefix = 'sh'
        elif sec_code.startswith(('0', '3', '002', '000')):
            prefix = 'sz'
        else:
            return pd.DataFrame()

        url = (f"https://quotes.sina.cn/cn/api/json_v2.php"
               f"/CN_MarketDataService.getKLineData"
               f"?symbol={prefix}{sec_code}&scale=240&ma=no&datalen={days}")

        r = subprocess.run(
            ['curl', '-s', '--noproxy', '*', '-L', '--max-time', '10', url],
            capture_output=True, text=True, timeout=15
        )
        if not r.stdout:
            return pd.DataFrame()

        data = json.loads(r.stdout)
        if not isinstance(data, list):
            return pd.DataFrame()

        rows = []
        for bar in data:
            rows.append({
                'date': pd.to_datetime(bar['day']),
                'open': float(bar['open']),
                'close': float(bar['close']),
                'high': float(bar['high']),
                'low': float(bar['low']),
                'volume': float(bar['volume']),
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values('date').reset_index(drop=True)
        return df
    except Exception as e:
        print(f"  ⚠️ 价格获取失败({sec_code}): {e}")
        return pd.DataFrame()


def get_returns(price_df: pd.DataFrame, event_date: str, windows: List[int] = [7, 30, 60, 90]) -> Dict[int, float]:
    """
    计算事件发生后各窗口期的收益率

    Returns:
        {window_days: return_pct}  e.g. {7: 2.3, 30: 5.1, ...}
    """
    if price_df.empty:
        return {w: np.nan for w in windows}

    event_dt = pd.to_datetime(event_date)
    price_df = price_df.sort_values('date').reset_index(drop=True)

    # 基准价：事件前最后一天的收盘价
    before = price_df[price_df['date'] < event_dt]
    if before.empty:
        # 事件当天或之前无数据，尝试事件当天
        on_day = price_df[price_df['date'] == event_dt]
        if on_day.empty:
            return {w: np.nan for w in windows}
        start_price = on_day.iloc[0]['close']
        start_idx = price_df[price_df['date'] == event_dt].index[0]
    else:
        start_price = before.iloc[-1]['close']
        start_idx = before.iloc[-1].name

    results = {}
    for w in windows:
        target_date = event_dt + timedelta(days=w)
        # 找窗口期末的收盘价
        available = price_df[price_df['date'] <= target_date]
        if len(available) > start_idx:
            end_price = available.iloc[-1]['close']
            ret = (end_price - start_price) / start_price * 100
            results[w] = round(ret, 2)
        else:
            results[w] = np.nan

    return results


# ============ 事件回测 ============

@dataclass
class EventBacktestResult:
    """单次事件的回测结果"""
    event: TrendEvent
    returns: Dict[int, float]   # window → return%
    avg_return: float           # 各窗口平均


@dataclass
class ChainValidationResult:
    """某产业链的验证结果"""
    chain: str
    total_events: int
    signal_stats: Dict[str, Dict]   # signal_type → stats
    level_stats: Dict[str, Dict]     # chain_level → stats
    overall_stats: Dict              # 整体统计


from dataclasses import dataclass


def validate_chain(chain_key: str) -> ChainValidationResult:
    """
    验证某产业链的信号有效性

    1. 遍历所有历史事件
    2. 对每个事件，获取相关节点的证券价格
    3. 计算事件后各窗口期收益
    4. 汇总统计
    """
    if chain_key not in INDUSTRY_CHAINS:
        raise ValueError(f"未知产业链: {chain_key}")

    chain = INDUSTRY_CHAINS[chain_key]
    db = IndustryEventDB(chain_key)
    events = db.get_all_events()

    if not events:
        return ChainValidationResult(
            chain=chain.trend,
            total_events=0,
            signal_stats={},
            level_stats={},
            overall_stats={}
        )

    print(f"\n📊 验证 {chain.trend} ({len(events)}个事件)")

    # 按信号类型 + 节点分组计算收益
    signal_groups: Dict[str, List] = {s.value: [] for s in TrendSignal}
    level_groups: Dict[str, List] = {l.value: [] for l in ChainLevel}

    windows = [7, 30, 60, 90]

    for event in events:
        # 获取相关节点的证券
        impacted_nodes = [chain.get_node(n) for n in event.impacted_nodes if chain.get_node(n)]
        if not impacted_nodes:
            # 如果没有明确节点，取全链条
            impacted_nodes = chain.nodes

        node_returns = []

        for node in impacted_nodes:
            for sec_name in node.securities[:2]:  # 每个节点最多2个代表证券
                # 公司名 → 股票代码
                sec_code = name_to_code(sec_name)
                if not sec_code or sec_code in ('DJI', 'EH', 'XPEV', 'EMR', 'HSAI'):
                    continue  # 跳过非A股

                price_df = get_price_data(sec_code, days=365)
                if price_df.empty:
                    continue

                returns = get_returns(price_df, event.date, windows)
                valid_returns = [v for v in returns.values() if not np.isnan(v)]

                if valid_returns:
                    node_returns.append(np.mean(valid_returns))

                    # 按节点层级分组
                    level_groups[node.level.value].extend(valid_returns)

        if node_returns:
            avg_ret = np.mean(node_returns)
            signal_groups[event.signal_type.value].append(avg_ret)
            print(f"  📅 {event.date} [{event.signal_type.value}] {event.title[:40]} → {avg_ret:+.1f}%")

    # 统计
    def calc_stats(groups: Dict[str, List]) -> Dict[str, Dict]:
        stats = {}
        for k, vals in groups.items():
            if vals:
                stats[k] = {
                    'count': len(vals),
                    'mean': round(np.mean(vals), 2),
                    'median': round(np.median(vals), 2),
                    'win_rate': round(np.sum(np.array(vals) > 0) / len(vals) * 100, 1),
                    'std': round(np.std(vals), 2),
                }
        return stats

    signal_stats = calc_stats(signal_groups)
    level_stats = calc_stats(level_groups)

    # 整体统计
    all_returns = []
    for vals in signal_groups.values():
        all_returns.extend(vals)

    overall = {
        'count': len(all_returns),
        'mean': round(np.mean(all_returns), 2) if all_returns else 0,
        'win_rate': round(np.sum(np.array(all_returns) > 0) / len(all_returns) * 100, 1) if all_returns else 0,
    }

    return ChainValidationResult(
        chain=chain.trend,
        total_events=len(events),
        signal_stats=signal_stats,
        level_stats=level_stats,
        overall_stats=overall
    )


def generate_validation_report(chain_key: str = None) -> str:
    """
    生成验证报告
    """
    lines = []
    lines.append("=" * 70)
    lines.append(f"  📈 产业链信号验证报告 | {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("=" * 70)

    chains_to_validate = [chain_key] if chain_key else list_chains()

    for ck in chains_to_validate:
        result = validate_chain(ck)

        lines.append(f"\n{'='*50}")
        lines.append(f"  【{result.chain}】")
        lines.append(f"{'='*50}")

        if result.total_events == 0:
            lines.append("  暂无历史事件数据")
            continue

        lines.append(f"\n  📊 整体表现 (共{result.total_events}个事件)")
        if result.overall_stats:
            o = result.overall_stats
            lines.append(f"    平均收益: {o['mean']:+.2f}%")
            lines.append(f"    胜率: {o['win_rate']:.1f}%")

        # 按信号类型
        if result.signal_stats:
            lines.append(f"\n  📡 按信号类型:")
            for sig_type, stats in sorted(result.signal_stats.items(),
                                          key=lambda x: -x[1]['mean']):
                lines.append(f"    {sig_type}: 均值{stats['mean']:+.2f}% "
                            f"中位数{stats['median']:+.2f}% "
                            f"胜率{stats['win_rate']:.0f}% "
                            f"(n={stats['count']})")

        # 按节点层级
        if result.level_stats:
            lines.append(f"\n  🏭 按节点层级:")
            for level, stats in sorted(result.level_stats.items(),
                                       key=lambda x: -x[1]['mean']):
                lines.append(f"    {level}: 均值{stats['mean']:+.2f}% "
                            f"胜率{stats['win_rate']:.0f}%"
                            f"(n={stats['count']})")

    lines.append("\n" + "=" * 70)
    return '\n'.join(lines)


# ============ 主程序 ============

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='产业链信号验证')
    parser.add_argument('--chain', type=str, default=None, help='指定产业链')
    args = parser.parse_args()

    report = generate_validation_report(args.chain)
    print(report)
