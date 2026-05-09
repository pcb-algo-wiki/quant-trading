"""
data/realtime_news.py
======================
多源实时新闻聚合 + 情感分析
数据源:
  1. 东方财富快讯 (50条/次, 实时滚动)
  2. 新浪财经实时 (20条/次, 实时)
  3. 同花顺财经 (30条/次, 实时)
  4. 财联社 (100条, 深度)

用法:
  python data/realtime_news.py
"""

import subprocess
import json
import re
import time
import pandas as pd
import numpy as np
from datetime import datetime
from snownlp import SnowNLP
from typing import List, Dict, Optional
from pathlib import Path

# A股专用情感词典
POSITIVE_WORDS = [
    '利好', '大涨', '突破', '创新高', '增持', '买入', '推荐', '超配', '业绩增长',
    '订单爆满', '份额增加', '资金流入', '看多', '做多', '涨停', '拉升', '反弹',
    '拐点', '景气', '超预期', '政策支持', '护盘', '维稳', '增量资金', '国家队',
    '净买入', '大幅增长', '超预期', '突破', '领涨', '涨停', '爆发', '爆发式',
    '史上最强', '创纪录', '新高', '加仓', '积极', '乐观', '强劲', '稳健'
]

NEGATIVE_WORDS = [
    '利空', '大跌', '破位', '创新低', '减持', '卖出', '降级', '低配', '业绩下滑',
    '亏损', '份额减少', '资金流出', '看空', '做空', '跌停', '砸盘', '杀跌',
    '风险', '暴雷', '违约', '不及预期', '清仓', '撤退', '出逃', '恐慌', '踩踏',
    '净卖出', '大幅下滑', '不及预期', '破发', '领跌', '跌停', '崩盘', '危机',
    '史上最差', '创新低', '减仓', '消极', '悲观', '疲软', '风险', '警示'
]


def sentiment_score(text: str) -> float:
    """情感得分 0~1"""
    if not text or len(str(text).strip()) < 4:
        return 0.5
    text_lower = str(text)
    
    pos = sum(1 for w in POSITIVE_WORDS if w in text_lower)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text_lower)
    
    if pos + neg > 0:
        delta = (pos - neg) / max(pos + neg, 1)
        base = 0.5 + delta * 0.5
    else:
        base = 0.5
    
    try:
        snownlp_score = SnowNLP(text_lower).sentiments
        combined = base * 0.6 + snownlp_score * 0.4
    except:
        combined = base
    
    return max(0.0, min(1.0, combined))


def _curl(url: str, headers: dict = None, timeout: int = 10) -> str:
    """curl封装"""
    cmd = ["curl", "-s", "--noproxy", "*", "-L",
           "--max-time", str(timeout),
           "-w", "\n%{http_code}",
           url]
    if headers:
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
    output = result.stdout.strip()
    # 分离body和状态码
    lines = output.split('\n')
    http_code = lines[-1] if lines else '000'
    body = '\n'.join(lines[:-1])
    return body


# ============ 东方财富快讯 ============

def fetch_eastmoney_news(pages: int = 1, pagesize: int = 50) -> List[Dict]:
    """东方财富快讯 (实时滚动)"""
    news_list = []
    for page in range(1, pages + 1):
        url = f"https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_{pagesize}_{page}_.html"
        text = _curl(url, {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://www.eastmoney.com"
        })
        if not text or text.startswith("var ajaxResult="):
            try:
                json_str = re.sub(r'^var ajaxResult=', '', text)
                data = json.loads(json_str)
                lives = data.get('LivesList', [])
                for item in lives:
                    news_list.append({
                        'source': '东方财富',
                        'title': item.get('title', ''),
                        'time': item.get('showtime', ''),
                        'url': item.get('url_w', ''),
                        'datetime': pd.to_datetime(item.get('showtime', ''), errors='coerce')
                    })
            except:
                pass
        time.sleep(0.1)
    return news_list


# ============ 新浪财经实时 ============

def fetch_sina_news(num: int = 20) -> List[Dict]:
    """新浪财经实时新闻"""
    news_list = []
    url = f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num={num}&page=1&r=0.5"
    text = _curl(url, {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn"
    })
    if text:
        try:
            data = json.loads(text)
            items = data.get('result', {}).get('data', [])
            for item in items:
                ts = int(item.get('ctime', 0))
                dt = datetime.fromtimestamp(ts) if ts > 0 else datetime.now()
                news_list.append({
                    'source': '新浪财经',
                    'title': item.get('title', ''),
                    'time': dt.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': item.get('url', ''),
                    'datetime': dt
                })
        except:
            pass
    return news_list


# ============ 同花顺财经 ============

def fetch_tonghuashun_news(pagesize: int = 30) -> List[Dict]:
    """同花顺财经新闻"""
    news_list = []
    url = f"https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize={pagesize}"
    text = _curl(url, {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.10jqka.com.cn"
    })
    if text:
        try:
            data = json.loads(text)
            items = data.get('data', {}).get('list', [])
            for item in items:
                news_list.append({
                    'source': '同花顺',
                    'title': item.get('title', ''),
                    'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'url': item.get('url', ''),
                    'datetime': datetime.now()
                })
        except:
            pass
    return news_list


# ============ 财联社新闻 ============

def fetch_cls_news() -> List[Dict]:
    """财联社新闻 (akshare)"""
    news_list = []
    try:
        import akshare as ak
        df = ak.stock_news_main_cx()
        for _, row in df.iterrows():
            news_list.append({
                'source': '财联社',
                'title': row.get('summary', ''),
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'url': row.get('url', ''),
                'datetime': datetime.now()
            })
    except Exception as e:
        print(f"财联社获取失败: {e}")
    return news_list


# ============ ETF/个股新闻 ============

def fetch_etf_news(sec_code: str) -> List[Dict]:
    """东方财富个股/ETF新闻"""
    news_list = []
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=sec_code)
        for _, row in df.iterrows():
            news_list.append({
                'source': '东财个股',
                'title': row.get('新闻标题', ''),
                'content': row.get('新闻内容', ''),
                'time': row.get('发布时间', ''),
                'url': row.get('新闻链接', ''),
                'datetime': pd.to_datetime(row.get('发布时间', ''), errors='coerce')
            })
    except Exception as e:
        print(f"ETF新闻获取失败({sec_code}): {e}")
    return news_list


# ============ 综合新闻聚合 ============

def get_realtime_news() -> pd.DataFrame:
    """获取所有实时新闻，合并去重，按时间排序"""
    all_news = []
    
    # 并行获取三大源
    import concurrent.futures
    
    sources = [
        ("东方财富", fetch_eastmoney_news),
        ("新浪财经", fetch_sina_news),
        ("同花顺", fetch_tonghuashun_news),
    ]
    
    for name, fetch_fn in sources:
        try:
            news = fetch_fn()
            all_news.extend(news)
        except Exception as e:
            print(f"{name}获取失败: {e}")
    
    if not all_news:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_news)
    
    # 情感分析
    df['情感得分'] = df['title'].apply(sentiment_score)
    
    # 去重（按标题前50字）
    df['title_short'] = df['title'].str[:50]
    df = df.drop_duplicates(subset=['title_short']).drop(columns=['title_short'])
    
    # 排序
    df = df.sort_values('datetime', ascending=False).reset_index(drop=True)
    
    return df


def get_market_summary(df: pd.DataFrame) -> dict:
    """市场情绪摘要"""
    if df.empty:
        return {}
    
    avg_sentiment = df['情感得分'].mean()
    positive_count = (df['情感得分'] > 0.6).sum()
    negative_count = (df['情感得分'] < 0.4).sum()
    neutral_count = len(df) - positive_count - negative_count
    
    # 来源分布
    source_counts = df['source'].value_counts().to_dict()
    
    # 最新新闻
    latest = df.iloc[0] if len(df) > 0 else {}
    
    # 极值新闻
    top_positive = df.nlargest(3, '情感得分')[['source', 'title', '情感得分']].values.tolist()
    top_negative = df.nsmallest(3, '情感得分')[['source', 'title', '情感得分']].values.tolist()
    
    return {
        '总条数': len(df),
        '平均情感': round(avg_sentiment, 3),
        '偏多': positive_count,
        '偏空': negative_count,
        '中性': neutral_count,
        '市场情绪': '看多' if avg_sentiment > 0.55 else '看空' if avg_sentiment < 0.45 else '中性',
        '情感强度': abs(avg_sentiment - 0.5) * 2,  # 0~1
        '主要来源': source_counts,
        '最新新闻': {
            'source': latest.get('source', ''),
            'title': latest.get('title', ''),
            'time': str(latest.get('datetime', '')),
            'score': latest.get('情感得分', 0.5)
        },
        '最正面新闻': top_positive,
        '最负面新闻': top_negative
    }


def get_policy_news(df: pd.DataFrame) -> pd.DataFrame:
    """筛选政策/宏观相关新闻"""
    keywords = ['央行', '美联储', '降息', '加息', '政策', '统计局', '国务院', '证监会',
                '银保监', '财政部', 'LPR', '存款准备金', '逆回购', 'MLF', 'SLF',
                '量化宽松', '缩表', '国债', 'CPI', 'PMI', '外汇', '汇率', '房地产', '楼市']
    mask = df['title'].str.contains('|'.join(keywords), na=False)
    return df[mask].reset_index(drop=True)


# ============ 主程序 ============

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='实时新闻聚合')
    parser.add_argument('--policy', action='store_true', help='只看政策新闻')
    parser.add_argument('--limit', type=int, default=50, help='显示条数')
    args = parser.parse_args()
    
    print("=" * 70)
    print(f"  多源实时新闻聚合  ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print("=" * 70)
    
    t0 = time.time()
    df = get_realtime_news()
    print(f"\n获取完成: {len(df)}条 (耗时 {time.time()-t0:.1f}s)")
    
    # 情感统计
    summary = get_market_summary(df)
    print(f"\n📊 市场情绪:")
    print(f"   总条数: {summary.get('总条数', 0)} | 平均情感: {summary.get('平均情感', 0.5):.3f}")
    print(f"   🟢偏多: {summary.get('偏多', 0)} | ⚪中性: {summary.get('中性', 0)} | 🔴偏空: {summary.get('偏空', 0)}")
    print(f"   市场情绪: {summary.get('市场情绪', '未知')} (强度: {summary.get('情感强度', 0):.2f})")
    print(f"   来源: {summary.get('主要来源', {})}")
    
    # 政策新闻
    if args.policy:
        policy_df = get_policy_news(df)
        print(f"\n📋 政策/宏观新闻 ({len(policy_df)}条):")
        for _, row in policy_df.head(15).iterrows():
            emoji = '🟢' if row['情感得分'] > 0.6 else '🔴' if row['情感得分'] < 0.4 else '⚪'
            print(f"  {emoji} [{row['source']}] {row['title'][:80]}")
    else:
        # 显示全部
        print(f"\n📰 最新新闻 ({min(args.limit, len(df))}条):")
        for i, row in df.head(args.limit).iterrows():
            emoji = '🟢' if row['情感得分'] > 0.6 else '🔴' if row['情感得分'] < 0.4 else '⚪'
            time_str = str(row.get('datetime', ''))[:19]
            print(f"  {emoji} [{row['source']}] [{time_str[-8:]}] {row['title'][:80]}")
        
        # 最正面/负面
        print(f"\n🟢 最正面新闻:")
        for src, title, score in summary.get('最正面新闻', []):
            print(f"   [{score:.2f}] {title[:80]}")
        
        print(f"\n🔴 最负面新闻:")
        for src, title, score in summary.get('最负面新闻', []):
            print(f"   [{score:.2f}] {title[:80]}")
