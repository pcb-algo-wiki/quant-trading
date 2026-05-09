"""
data/macro_event.py
====================
宏观事件 + 政策信号驱动策略
整合：宏观数据(CPI/PMI/LPR/RRR) + 市场情绪 + 资金流向 → 事件信号

核心思路:
  - 宏观数据公布日（每月）→ 市场预期差 → 短期方向
  - 政策事件（降准/加息）→ 历史规律 → 概率化交易
  - 资金流向（近5日）→ 机构行为 → 领先价格

⚠️ 注意:
  - 新闻情感无法历史回测，只能获取当前信号做实时决策
  - 资金流向有120天历史，可以做模拟回测
  - 宏观数据事件可基于历史数据回测（已知结果）
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from snownlp import SnowNLP
import akshare as ak
import signal as signal_module
import json
from pathlib import Path
from typing import Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True, parents=True)

# ============ 超时装饰器 ============

def _timeout_handler(signum, frame):
    raise TimeoutError("API调用超时")

def with_timeout(func, timeout=15, default=None):
    """带超时的函数执行"""
    def wrapper(*args, **kwargs):
        signal_module.signal(signal_module.SIGALRM, _timeout_handler)
        signal_module.alarm(timeout)
        try:
            return func(*args, **kwargs)
        except TimeoutError:
            print(f"⚠️ {func.__name__} 超时({timeout}s)")
            return default
        except Exception as e:
            print(f"❌ {func.__name__}: {e}")
            return default
        finally:
            signal_module.alarm(0)
    return wrapper


# ============ 情感分析 ============

POSITIVE_WORDS = [
    '利好', '大涨', '突破', '创新高', '增持', '买入', '推荐', '超配',
    '业绩增长', '订单爆满', '份额增加', '资金流入', '看多', '做多',
    '涨停', '拉升', '反弹', '拐点', '景气', '超预期', '政策支持',
    '护盘', '维稳', '增量资金', '国家队'
]

NEGATIVE_WORDS = [
    '利空', '大跌', '破位', '创新低', '减持', '卖出', '降级', '低配',
    '业绩下滑', '亏损', '份额减少', '资金流出', '看空', '做空',
    '跌停', '砸盘', '杀跌', '风险', '暴雷', '违约', '不及预期',
    '清仓', '撤退', '出逃', '恐慌', '踩踏'
]


def sentiment_score(text: str) -> float:
    """基于词典+SnowNLP的情感得分 0~1"""
    if not text or len(str(text).strip()) < 4:
        return 0.5
    text_lower = str(text)
    
    # 词典计数
    pos = sum(1 for w in POSITIVE_WORDS if w in text_lower)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text_lower)
    
    if pos + neg > 0:
        delta = (pos - neg) / max(pos + neg, 1)
        base = 0.5 + delta * 0.5
    else:
        base = 0.5
    
    # SnowNLP修正
    try:
        snownlp_score = SnowNLP(text_lower).sentiments
        combined = base * 0.6 + snownlp_score * 0.4
    except:
        combined = base
    
    return max(0.0, min(1.0, combined))


def batch_sentiment(texts: list) -> list:
    return [sentiment_score(t) for t in texts]


# ============ 宏观数据获取 ============

@with_timeout
def get_cpi(months: int = 24) -> pd.DataFrame:
    """获取CPI数据（月频）"""
    try:
        df = ak.macro_china_cpi()
        df['月份'] = pd.to_datetime(df['月份'].str.replace('年', '-').str.replace('月份', ''))
        df = df.sort_values('月份').tail(months)
        return df
    except:
        return pd.DataFrame()


@with_timeout
def get_pmi(months: int = 24) -> pd.DataFrame:
    """获取PMI数据（月频）"""
    try:
        df = ak.macro_china_pmi()
        df['月份'] = pd.to_datetime(df['月份'].str.replace('年', '-').str.replace('月份', ''))
        df = df.sort_values('月份').tail(months)
        return df
    except:
        return pd.DataFrame()


@with_timeout
def get_lpr(months: int = 24) -> pd.DataFrame:
    """获取LPR数据（月频）"""
    try:
        df = ak.macro_china_lpr()
        df['TRADE_DATE'] = pd.to_datetime(df['TRADE_DATE'])
        df = df.sort_values('TRADE_DATE').tail(months)
        return df
    except:
        return pd.DataFrame()


@with_timeout
def get_rrr_events(years: int = 10) -> pd.DataFrame:
    """获取存款准备金率调整事件（历史 + 最新）"""
    try:
        df = ak.macro_china_reserve_requirement_ratio()
        df['公布时间'] = pd.to_datetime(df['公布时间'].str.replace('年', '-').str.replace('月', '').str.replace('日', ''))
        df = df.sort_values('公布时间').tail(years * 12)
        # 计算调整方向
        df['direction'] = np.sign(df['大型金融机构-调整幅度'].fillna(0))
        return df
    except:
        return pd.DataFrame()


# ============ 资金流向 ============

@with_timeout
def get_fund_flow(sec_code: str, market: str = None) -> pd.DataFrame:
    """获取资金流向（120天）"""
    if market is None:
        market = 'sh' if sec_code.startswith(('51', '58')) else 'sz'
    try:
        df = ak.stock_individual_fund_flow(stock=sec_code, market=market)
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期')
        return df
    except Exception as e:
        print(f"get_fund_flow error: {e}")
        return pd.DataFrame()


def analyze_fund_flow(df: pd.DataFrame, lookback: int = 5) -> dict:
    """分析资金流向，输出信号"""
    if df.empty or len(df) < lookback:
        return {'signal': 'neutral', 'score': 0.5, 'detail': '数据不足'}
    
    recent = df.tail(lookback)
    main_net = recent['主力净流入-净额'].values
    
    positive_days = np.sum(main_net > 0)
    total_flow = np.sum(main_net)
    
    if positive_days >= lookback * 0.8 and total_flow > 0:
        signal_str = 'bullish'
        score = min(0.9, 0.5 + positive_days / lookback * 0.4)
    elif positive_days <= lookback * 0.2 and total_flow < 0:
        signal_str = 'bearish'
        score = max(0.1, 0.5 - (lookback - positive_days) / lookback * 0.4)
    else:
        signal_str = 'neutral'
        score = 0.5
    
    return {
        'signal': signal_str,
        'score': round(float(score), 3),
        'positive_days': int(positive_days),
        'total_flow': int(total_flow),
        'detail': f"近{lookback}日主力净流入{positive_days}天/共{total_flow/1e8:.1f}亿"
    }


# ============ 新闻获取 ============

@with_timeout
def get_etf_news(sec_code: str, days: int = 7) -> pd.DataFrame:
    """获取ETF相关新闻"""
    try:
        df = ak.stock_news_em(symbol=sec_code)
        df = df.head(days * 5)
        df['情感得分'] = batch_sentiment(df['新闻标题'].tolist())
        df['发布时间'] = pd.to_datetime(df['发布时间'])
        return df
    except Exception as e:
        print(f"get_etf_news error: {e}")
        return pd.DataFrame()


@with_timeout
def get_market_news(days: int = 7) -> pd.DataFrame:
    """获取市场主要新闻（财联社）"""
    try:
        df = ak.stock_news_main_cx()
        df = df.head(days * 10)
        df['情感得分'] = batch_sentiment(df['summary'].tolist())
        return df
    except Exception as e:
        print(f"get_market_news error: {e}")
        return pd.DataFrame()


@with_timeout
def get_policy_news(days: int = 7) -> pd.DataFrame:
    """获取政策相关新闻（宏观/央行/财政部/证监会）"""
    keywords = ['央行', '美联储', '降息', '加息', '政策', '统计局', '国务院', '证监会', 
                '银保监', '财政部', 'LPR', '存款准备金', '逆回购', 'MLF', 'SLF', '量化宽松']
    try:
        df = ak.stock_news_main_cx()
        mask = df['summary'].str.contains('|'.join(keywords), na=False)
        df = df[mask].head(days * 10)
        df['情感得分'] = batch_sentiment(df['summary'].tolist())
        return df
    except Exception as e:
        print(f"get_policy_news error: {e}")
        return pd.DataFrame()


# ============ 综合事件信号 ============

def get_macro_signal() -> dict:
    """
    综合宏观信号（基于最新数据）
    返回: {cpi_signal, pmi_signal, lpr_signal, rrr_signal, composite}
    """
    result = {
        'cpi_signal': 'neutral', 'cpi_value': None, 'cpi_change': None,
        'pmi_signal': 'neutral', 'pmi_manufacturing': None, 'pmi_services': None,
        'lpr_signal': 'neutral', 'lpr_1y': None, 'lpr_5y': None,
        'rrr_signal': 'neutral', 'rrr_last_change': None,
        'composite': 0.5, 'timestamp': datetime.now().strftime('%Y-%m-%d')
    }
    
    # CPI
    cpi = get_cpi(months=3)
    if not cpi.empty and '全国-同比增长' in cpi.columns:
        latest = cpi.iloc[-1]
        prev = cpi.iloc[-2] if len(cpi) > 1 else latest
        yoy = float(latest['全国-同比增长'])
        mom = float(latest['全国-环比增长'])
        result['cpi_value'] = yoy
        result['cpi_change'] = mom
        if yoy > 3:
            result['cpi_signal'] = 'inflationary'  # 通胀压力
        elif yoy < 0.5:
            result['cpi_signal'] = 'deflationary'  # 通缩风险
    
    # PMI
    pmi = get_pmi(months=3)
    if not pmi.empty:
        latest = pmi.iloc[-1]
        mfg = float(latest['制造业-指数'])
        svcs = float(latest['非制造业-指数'])
        result['pmi_manufacturing'] = mfg
        result['pmi_services'] = svcs
        if mfg > 50 and svcs > 50:
            result['pmi_signal'] = 'expansion'
        elif mfg < 45:
            result['pmi_signal'] = 'contraction'
    
    # LPR
    lpr = get_lpr(months=3)
    if not lpr.empty:
        latest = lpr.iloc[-1]
        lpr1y = float(latest['LPR1Y']) if pd.notna(latest.get('LPR1Y')) else None
        lpr5y = float(latest['LPR5Y']) if pd.notna(latest.get('LPR5Y')) else None
        result['lpr_1y'] = lpr1y
        result['lpr_5y'] = lpr5y
    
    # RRR
    rrr = get_rrr_events(years=2)
    if not rrr.empty:
        last = rrr.iloc[-1]
        direction = int(last['direction'])
        result['rrr_last_change'] = direction
        if direction > 0:
            result['rrr_signal'] = 'tightening'  # 收紧
        elif direction < 0:
            result['rrr_signal'] = 'easing'  # 宽松
    
    # 综合宏观信号
    # PMI扩张 + RRR宽松 → +0.5分
    # CPI通缩风险 → +0.3分（政策宽松预期）
    score = 0.5
    if result['pmi_signal'] == 'expansion':
        score += 0.1
    if result['rrr_signal'] == 'easing':
        score += 0.2
    if result['cpi_signal'] == 'deflationary':
        score += 0.1
    if result['cpi_signal'] == 'inflationary':
        score -= 0.1
    result['composite'] = round(max(0.1, min(0.9, score)), 3)
    
    return result


def get_event_alpha(sec_code: str = None) -> dict:
    """
    综合事件alpha信号
    整合：新闻情感(30%) + 资金流向(40%) + 宏观信号(30%)
    
    ⚠️ 注意：新闻情感只能获取当前值，无法历史回测
    """
    result = {
        'sec_code': sec_code or 'market',
        'news_sentiment': 0.5,
        'news_summary': '',
        'fund_flow_signal': 'neutral',
        'fund_flow_score': 0.5,
        'macro_signal': 0.5,
        'macro_summary': '',
        'composite_score': 0.5,
        'action': 'hold',
        'confidence': 0.0,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
    }
    
    # 1. 新闻情感（30%权重）- 优先使用realtime_news
    try:
        from data.realtime_news import get_realtime_news, sentiment_score as rt_sentiment_score
        news_df = get_realtime_news()
        if not news_df.empty:
            result['news_sentiment'] = round(float(news_df['情感得分'].mean()), 3)
            top = news_df.sort_values('情感得分', ascending=False).iloc[0]
            result['news_summary'] = f"[{top['情感得分']:.2f}] {top.get('title', '')[:60]}"
        else:
            raise Exception("no realtime news")
    except:
        # 降级到ETF新闻
        if sec_code:
            news_df = get_etf_news(sec_code, days=3)
            if not news_df.empty:
                result['news_sentiment'] = round(float(news_df['情感得分'].mean()), 3)
                top = news_df.sort_values('情感得分', ascending=False).iloc[0]
                result['news_summary'] = f"[{top['情感得分']:.2f}] {top.get('新闻标题', '')[:60]}"
    
    # 2. 资金流向（40%权重）
    if sec_code:
        flow_df = get_fund_flow(sec_code)
        if not flow_df.empty:
            flow = analyze_fund_flow(flow_df, lookback=5)
            result['fund_flow_signal'] = flow['signal']
            result['fund_flow_score'] = flow['score']
    
    # 3. 宏观信号（30%权重）
    try:
        macro = get_macro_signal()
        result['macro_signal'] = macro['composite']
        macro_parts = []
        if macro.get('pmi_manufacturing'):
            macro_parts.append(f"PMI={macro['pmi_manufacturing']:.1f}")
        if macro.get('cpi_value') is not None:
            macro_parts.append(f"CPI={macro['cpi_value']:.1f}%")
        if macro.get('lpr_1y'):
            macro_parts.append(f"LPR={macro['lpr_1y']:.2f}%")
        result['macro_summary'] = ' '.join(macro_parts) if macro_parts else ''
    except:
        pass
    
    # 4. 综合得分
    composite = (
        result['news_sentiment'] * 0.30 +
        result['fund_flow_score'] * 0.40 +
        result['macro_signal'] * 0.30
    )
    result['composite_score'] = round(composite, 3)
    
    # 5. 行动信号
    if composite > 0.62:
        result['action'] = 'buy'
        result['confidence'] = round((composite - 0.62) / 0.38 * 100, 1)
    elif composite < 0.38:
        result['action'] = 'sell'
        result['confidence'] = round((0.38 - composite) / 0.38 * 100, 1)
    else:
        result['action'] = 'hold'
        result['confidence'] = 0.0
    
    return result


def get_multi_etf_event_alpha(sec_codes: List[str]) -> pd.DataFrame:
    """获取多ETF事件alpha信号"""
    results = [get_event_alpha(code) for code in sec_codes]
    df = pd.DataFrame(results)
    df = df.sort_values('composite_score', ascending=False)
    return df


# ============ 主程序测试 ============

if __name__ == '__main__':
    print("=" * 70)
    print("  宏观 + 事件alpha信号")
    print("=" * 70)
    
    import time
    t0 = time.time()
    
    # 宏观信号
    print("\n📊 宏观信号:")
    try:
        macro = get_macro_signal()
        print(f"   PMI: 制造业={macro.get('pmi_manufacturing')} 服务={macro.get('pmi_services')}")
        print(f"   CPI: {macro.get('cpi_value')}% 环比={macro.get('cpi_change')}%")
        print(f"   LPR: 1Y={macro.get('lpr_1y')}% 5Y={macro.get('lpr_5y')}%")
        rrr = macro.get('rrr_signal', 'neutral')
        print(f"   RRR: {'宽松' if rrr=='easing' else '收紧' if rrr=='tightening' else '中性'}")
        print(f"   宏观综合: {macro.get('composite', 0.5):.2f}")
    except Exception as e:
        print(f"   (获取失败: {e})")
    
    # ETF事件信号
    print(f"\n📊 ETF事件信号 (已耗时 {time.time()-t0:.1f}s):")
    sec_codes = ['510300', '510500', '159915']
    results = []
    
    for code in sec_codes:
        t1 = time.time()
        try:
            # 新闻
            news_df = get_etf_news(code, days=3)
            news_score = 0.5
            news_summary = ''
            if not news_df.empty:
                news_score = round(float(news_df['情感得分'].mean()), 3)
                top = news_df.sort_values('情感得分', ascending=False).iloc[0]
                news_summary = f"[{top['情感得分']:.2f}] {top.get('新闻标题', '')[:60]}"
            
            # 资金流
            flow_df = get_fund_flow(code)
            fund_score = 0.5
            fund_signal = 'neutral'
            if not flow_df.empty:
                flow = analyze_fund_flow(flow_df, lookback=5)
                fund_score = flow['score']
                fund_signal = flow['signal']
            
            # 综合
            composite = news_score * 0.3 + fund_score * 0.7
            action = 'buy' if composite > 0.62 else 'sell' if composite < 0.38 else 'hold'
            elapsed = time.time() - t1
            print(f"   {code}: 新闻={news_score:.2f} 资金={fund_score:.2f}({fund_signal}) → 综合={composite:.2f} {action} ({elapsed:.1f}s)")
            if news_summary:
                print(f"      {news_summary[:80]}")
            results.append({'code': code, 'news': news_score, 'fund': fund_score, 
                         'fund_signal': fund_signal, 'news_summary': news_summary})
        except Exception as e:
            print(f"   {code}: (获取失败: {e})")
            results.append({'code': code, 'news': 0.5, 'fund': 0.5, 
                          'fund_signal': 'neutral', 'news_summary': ''})
    
    # 横向对比
    print("\n📊 横向对比:")
    print(f"{'代码':<10} {'新闻':>6} {'资金':>6} {'综合':>6} {'信号':<8} {'操作':<6}")
    print("-" * 50)
    for r in results:
        composite = r['news'] * 0.3 + r['fund'] * 0.7
        action = 'buy' if composite > 0.62 else 'sell' if composite < 0.38 else 'hold'
        print(f"{r['code']:<10} {r['news']:>6.2f} {r['fund']:>6.2f} {composite:>6.2f} {r['fund_signal']:<8} {action:<6}")
    
    print(f"\n总耗时: {time.time()-t0:.1f}s")
