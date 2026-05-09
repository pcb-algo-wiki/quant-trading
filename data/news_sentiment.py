"""
data/news_sentiment.py
=====================
新闻+舆情+情感分析模块
利用信息差构建领先信号

数据来源:
- akshare: 新闻、资金流向
- snownlp: 中文情感分析（词典法，无需模型）

核心思路:
  新闻情绪(领先1-3天) + 资金流向(领先价格) → 信息alpha
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from snownlp import SnowNLP
import akshare as ak
import signal
import json
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


# ============ 工具函数 ============

def _timeout_handler(signum, frame):
    raise TimeoutError("API调用超时")


def with_timeout(func, timeout=15, default=None):
    """带超时的函数执行"""
    def wrapper(*args, **kwargs):
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout)
        try:
            return func(*args, **kwargs)
        except TimeoutError:
            print(f"⚠️ {func.__name__} 超时({timeout}s)，返回默认值")
            return default
        except Exception as e:
            print(f"❌ {func.__name__} 错误: {e}")
            return default
        finally:
            signal.alarm(0)
    return wrapper


# ============ 情感分析 ============

def sentiment_score(text: str) -> float:
    """
    使用SnowNLP计算文本情感得分
    返回: 0~1，>0.6正面，<0.4负面，0.5中性
    """
    if not text or len(text.strip()) < 4:
        return 0.5
    try:
        s = SnowNLP(str(text))
        return s.sentiments
    except:
        return 0.5


def batch_sentiment(texts: list[str]) -> list[float]:
    """批量情感分析"""
    return [sentiment_score(t) for t in texts]


# ============ 新闻获取 ============

@with_timeout
def get_etf_news(sec_code: str, days: int = 7) -> pd.DataFrame:
    """
    获取ETF相关新闻
    sec_code: 如 '510300', '159915'
    返回: DataFrame[新闻标题, 发布时间, 情感得分]
    """
    try:
        df = ak.stock_news_em(symbol=sec_code)
        df = df.head(days * 3)  # 每天约3条
        df['情感得分'] = df['新闻标题'].apply(sentiment_score)
        df['发布时间'] = pd.to_datetime(df['发布时间'])
        return df
    except Exception as e:
        print(f"get_etf_news 错误: {e}")
        return pd.DataFrame()


@with_timeout
def get_market_news(days: int = 3) -> pd.DataFrame:
    """
    获取市场主要新闻
    返回: DataFrame[tag, summary, url, 情感得分]
    """
    try:
        df = ak.stock_news_main_cx()
        df = df.head(days * 10)
        df['情感得分'] = df['summary'].apply(sentiment_score)
        df['发布时间'] = datetime.now()  # 无时间戳，用当前时间
        return df
    except Exception as e:
        print(f"get_market_news 错误: {e}")
        return pd.DataFrame()


# ============ 资金流向 ============

@with_timeout
def get_fund_flow(sec_code: str, market: str = None) -> pd.DataFrame:
    """
    获取ETF/个股资金流向
    market: 'sh' 或 'sz'
    返回: DataFrame[日期, 主力净流入, 超大单净流入, ...]
    """
    # 自动推断market
    if market is None:
        market = 'sh' if sec_code.startswith(('51', '58')) else 'sz'

    try:
        df = ak.stock_individual_fund_flow(stock=sec_code, market=market)
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期')
        return df
    except Exception as e:
        print(f"get_fund_flow 错误: {e}")
        return pd.DataFrame()


def analyze_fund_flow(df: pd.DataFrame, lookback: int = 5) -> dict:
    """
    分析资金流向，输出信号
    lookback: 回顾天数
    返回: dict{主力信号, 超大单信号, 情绪得分}
    """
    if df.empty or len(df) < lookback:
        return {'signal': 'neutral', 'score': 0.5, 'detail': '数据不足'}

    recent = df.tail(lookback)

    # 主力净流入天数
    main_net = recent['主力净流入-净额'].values
    positive_days = np.sum(main_net > 0)
    total_flow = np.sum(main_net)

    # 超大单净流入
    super_net = recent['超大单净流入-净额'].values if '超大单净流入-净额' in recent.columns else main_net

    # 信号判断
    if positive_days >= lookback * 0.8 and total_flow > 0:
        signal_str = 'bullish'
        score = min(0.9, 0.5 + positive_days / lookback * 0.4)
    elif positive_days <= lookback * 0.2 and total_flow < 0:
        signal_str = 'bearish'
        score = max(0.1, 0.5 - positive_days / lookback * 0.4)
    else:
        signal_str = 'neutral'
        score = 0.5

    return {
        'signal': signal_str,
        'score': round(score, 3),
        'positive_days': int(positive_days),
        'total_flow': int(total_flow),
        'avg_flow': int(np.mean(main_net)),
        'super_positive_days': int(np.sum(super_net > 0)),
        'detail': f"近{lookback}日主力净流入{positive_days}天/共{int(total_flow/1e8):.1f}亿"
    }


# ============ 综合信息alpha ============

def get_info_alpha(sec_code: str, market: str = None) -> dict:
    """
    综合信息alpha信号
    整合: 新闻情感 + 资金流向 + 短期趋势

    返回:
        {
            'composite_score': float,     # 0~1综合得分
            'news_sentiment': float,      # 新闻情感 0~1
            'fund_flow_signal': str,      # bullish/neutral/bearish
            'fund_flow_score': float,      # 资金得分 0~1
            'action': 'buy'/'sell'/'hold',
            'confidence': float,           # 置信度
            'news_summary': str,           # 最近新闻摘要
            'timestamp': str
        }
    """
    result = {
        'sec_code': sec_code,
        'composite_score': 0.5,
        'news_sentiment': 0.5,
        'fund_flow_signal': 'neutral',
        'fund_flow_score': 0.5,
        'action': 'hold',
        'confidence': 0.0,
        'news_summary': '',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
    }

    # 1. 新闻情感
    news_df = get_etf_news(sec_code, days=3)
    if not news_df.empty:
        result['news_sentiment'] = round(news_df['情感得分'].mean(), 3)
        top_news = news_df.sort_values('情感得分', ascending=False).iloc[0]
        result['news_summary'] = f"[{top_news['情感得分']:.2f}] {top_news['新闻标题'][:50]}"

    # 2. 资金流向
    flow_df = get_fund_flow(sec_code, market)
    if not flow_df.empty:
        flow_analysis = analyze_fund_flow(flow_df, lookback=5)
        result['fund_flow_signal'] = flow_analysis['signal']
        result['fund_flow_score'] = flow_analysis['score']

    # 3. 综合得分（加权）
    # 新闻权重40%，资金权重60%（资金更客观）
    composite = result['news_sentiment'] * 0.4 + result['fund_flow_score'] * 0.6
    result['composite_score'] = round(composite, 3)

    # 4. 行动信号
    if composite > 0.62:
        result['action'] = 'buy'
        result['confidence'] = round((composite - 0.62) / 0.38 * 100, 1)  # 0~100%
    elif composite < 0.38:
        result['action'] = 'sell'
        result['confidence'] = round((0.38 - composite) / 0.38 * 100, 1)
    else:
        result['action'] = 'hold'
        result['confidence'] = 0.0

    return result


def get_multi_etf_info_alpha(sec_codes: list[str]) -> pd.DataFrame:
    """
    获取多只ETF的信息alpha信号
    用于横向比较，选出最强/最弱标的
    """
    results = []
    for code in sec_codes:
        info = get_info_alpha(code)
        results.append(info)

    df = pd.DataFrame(results)
    df = df.sort_values('composite_score', ascending=False)
    return df


# ============ 缓存管理 ============

def cache_info_alpha(sec_code: str, force_refresh: bool = False):
    """缓存信息alpha，避免频繁请求"""
    cache_file = CACHE_DIR / f"info_alpha_{sec_code}.json"
    if not force_refresh and cache_file.exists():
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if (datetime.now() - mtime).seconds < 3600:  # 1小时内用缓存
            with open(cache_file) as f:
                return json.load(f)

    info = get_info_alpha(sec_code)
    with open(cache_file, 'w') as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    return info


# ============ 情感词典扩展 ============

# A股特有词汇（补充SnowNLP的通用情感词典）
POSITIVE_WORDS = [
    '利好', '大涨', '突破', '创新高', '增持', '买入', '推荐', '超配',
    '业绩增长', '订单爆满', '份额增加', '资金流入', '看多', '做多',
    '涨停', '拉升', '反弹', '拐点', '景气', '景气度', '超预期'
]

NEGATIVE_WORDS = [
    '利空', '大跌', '破位', '创新低', '减持', '卖出', '降级', '低配',
    '业绩下滑', '亏损', '份额减少', '资金流出', '看空', '做空',
    '跌停', '砸盘', '杀跌', '风险', '暴雷', '违约', '不及预期'
]


def lexicon_sentiment(text: str) -> float:
    """
    基于词典的情感分析（A股专用）
    对SnowNLP结果进行修正
    """
    if not text:
        return 0.5

    text_lower = str(text)
    pos_count = sum(1 for w in POSITIVE_WORDS if w in text_lower)
    neg_count = sum(1 for w in NEGATIVE_WORDS if w in text_lower)

    if pos_count + neg_count == 0:
        # 无关键词，返回SnowNLP结果
        return sentiment_score(text)

    # 词典信号强度
    delta = (pos_count - neg_count) / max(pos_count + neg_count, 1)
    snownlp_score = sentiment_score(text)

    # 混合：词典权重60%，SnowNLP权重40%
    combined = snownlp_score * 0.4 + (0.5 + delta * 0.5) * 0.6
    return max(0.0, min(1.0, combined))


# ============ 主程序测试 ============

if __name__ == '__main__':
    print("=" * 60)
    print("信息Alpha信号测试")
    print("=" * 60)

    test_codes = ['510300', '510500', '159915']

    for code in test_codes:
        print(f"\n📊 {code} 信息分析...")
        info = get_info_alpha(code)
        print(f"   新闻情感: {info['news_sentiment']:.2f} | 资金信号: {info['fund_flow_signal']} | 综合得分: {info['composite_score']:.2f}")
        print(f"   操作: {info['action']} ({info['confidence']:.0f}%置信度)")
        if info['news_summary']:
            print(f"   最新: {info['news_summary']}")

    print("\n" + "=" * 60)
    print("横向对比")
    print("=" * 60)
    df = get_multi_etf_info_alpha(test_codes)
    print(df[['sec_code', 'composite_score', 'action', 'confidence', 'fund_flow_signal']].to_string(index=False))
