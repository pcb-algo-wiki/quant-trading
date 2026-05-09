"""
A股个股数据获取器
================
基于新浪财经API，0代理拦截

支持:
- 日线数据（scale=240）
- 2000条上限（约8-9年历史）
- 沪市(sh)/深市(sz)个股

注意：个股数据量远大于ETF，全部缓存需较大存储空间
"""

import subprocess
import json
import time
import pickle
from pathlib import Path
from typing import Optional
import pandas as pd

CACHE_DIR = Path("data/cache/stocks")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 新浪K线接口
SIINA_KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"


def _fetch_sina_kline(symbol: str, market: str, datalen: int = 2000, timeout: int = 10) -> list:
    """
    获取新浪K线数据

    Args:
        symbol: 股票代码，如 "603986"
        market: "SH" 或 "SZ"
        datalen: 数据条数，默认2000
        timeout: 超时秒数

    Returns:
        list of dicts: [{"day": "2026-05-08", "open": "xxx", "high": "xxx", ...}]
    """
    if market == "SH":
        sym = f"sh{symbol}"
    else:
        sym = f"sz{symbol}"

    url = f"{SIINA_KLINE_URL}?symbol={sym}&scale=240&ma=no&datalen={datalen}"

    result = subprocess.run(
        ["curl", "-s", "--noproxy", "*", "-L", "--max-time", str(timeout), url],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        raise ConnectionError(f"Curl failed: {result.stderr}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON response for {sym}: {result.stdout[:200]}")

    return data


def fetch_stock(symbol: str, market: str, datalen: int = 2000) -> pd.DataFrame:
    """
    获取个股日线数据

    Args:
        symbol: 股票代码，如 "603986"
        market: "SH" 或 "SZ"
        datalen: 数据条数

    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    data = _fetch_sina_kline(symbol, market, datalen)

    if not data:
        raise ValueError(f"No data returned for {market}{symbol}")

    df = pd.DataFrame(data)
    df.columns = ["date", "open", "high", "low", "close", "volume"]
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return df


def fetch_stock_cached(symbol: str, market: str, max_days: int = 2000) -> pd.DataFrame:
    """
    获取个股数据（带缓存）
    缓存路径: data/cache/stocks/{symbol}.pkl
    """
    cache_file = CACHE_DIR / f"{symbol}.pkl"

    if cache_file.exists():
        cached = pd.read_pickle(cache_file)
        cached["date"] = pd.to_datetime(cached["date"])

        # 检查是否需要增量更新（最后一笔数据距今超过7天）
        last_date = cached["date"].max()
        import datetime
        if (datetime.datetime.now() - last_date).days <= 7:
            return cached

        # 增量更新：获取比缓存更新的数据
        try:
            new_data = fetch_stock(symbol, market, datalen=2000)
            new_data["date"] = pd.to_datetime(new_data["date"])

            # 合并：保留缓存中没有的更新数据
            combined = pd.concat([cached, new_data], ignore_index=True)
            combined = combined.drop_duplicates("date").sort_values("date").reset_index(drop=True)
            combined.to_pickle(cache_file)
            return combined
        except Exception:
            return cached  # 更新失败，返回缓存

    # 无缓存，直接获取
    df = fetch_stock(symbol, market, datalen=max_days)
    df.to_pickle(cache_file)
    return df


# ============================================================
# 半导体全产业链个股清单
# ============================================================
SEMI_CONDUCTOR_STOCKS = {
    # --- 设计 ---
    "300223": ("SZ", "北京君正", "设计/SRAM-DRAM"),
    "603986": ("SH", "兆易创新", "设计/NOR-Flash"),
    "688981": ("SH", "中芯国际", "代工/晶圆"),
    "002371": ("SZ", "北方华创", "设备/刻蚀沉积"),
    "688012": ("SH", "中微公司", "设备/刻蚀"),
    "688396": ("SH", "华润微", "设计+制造/功率半导体"),
    "603501": ("SH", "韦尔股份", "设计/CIS图像传感器"),
    "688008": ("SH", "澜起科技", "设计/服务器内存接口"),
    "688107": ("SH", "安路科技", "设计/FPGA"),
    "688256": ("SH", "寒武纪", "设计/AI芯片"),
    "688099": ("SH", "晶晨股份", "设计/多媒体SoC"),
    "688123": ("SH", "聚辰股份", "设计/EEPROM"),
    "688220": ("SH", "翱捷科技", "设计/蜂窝基带"),
    "688521": ("SH", "芯原股份", "设计/芯片定制"),
    "002049": ("SZ", "紫光国微", "设计/FPGA-特种IC"),
    "603160": ("SH", "汇顶科技", "设计/指纹触控"),
    "300474": ("SZ", "景嘉微", "设计/GPU"),
    "688268": ("SH", "华特气体", "材料/电子特气"),
    "688168": ("SH", "安博通", "设计/网络安全芯片"),

    # --- 设备 ---
    "688521": ("SH", "芯原股份", "设计/芯片IP"),
    "002008": ("SZ", "大族激光", "设备/激光切割"),
    "688556": ("SH", "高测股份", "设备/硅片切割"),
    "688700": ("SH", "东威科技", "设备/电镀设备"),
    "688116": ("SH", "天奈科技", "材料/碳纳米管"),
    "688388": ("SH", "嘉元科技", "材料/锂电铜箔"),
    "300661": ("SZ", "圣邦股份", "设计/模拟芯片"),
    "688099": ("SH", "晶晨股份", "设计/多媒体芯片"),
    "688220": ("SH", "翱捷科技", "设计/基带芯片"),

    # --- 材料 ---
    "688126": ("SH", "沪硅产业", "材料/硅片"),
    "301308": ("SZ", "江波龙", "封装/存储模组"),
    "600584": ("SH", "长电科技", "封测/封装"),
    "002185": ("SZ", "华天科技", "封测/封装"),
    "600667": ("SH", "太极实业", "封测/封装"),
    "002156": ("SZ", "通富微电", "封测/封装"),
    "603186": ("SH", "华正新材", "材料/覆铜板"),
    "688499": ("SH", "利元亨", "设备/锂电设备"),

    # --- 存储 ---
    "688123": ("SH", "聚辰股份", "设计/EEPROM"),

    # --- 光伏/功率 ---
    "688032": ("SH", "禾迈股份", "设备/光伏逆变器"),
    "603806": ("SH", "福斯特", "材料/光伏封装"),
    "601012": ("SH", "隆基绿能", "制造/光伏硅片"),
    "002459": ("SZ", "晶澳科技", "制造/光伏电池"),
    "300274": ("SZ", "阳光电源", "设备/光伏逆变器"),
    "601877": ("SH", "正泰电器", "制造/低压电气"),
    "002706": ("SZ", "东方精工", "设备/瓦楞纸设备"),
}


# 核心30只（按行业龙头+流动性筛选）
CORE_30_STOCKS = {
    # 半导体
    "603986": ("SH", "兆易创新", "NOR Flash"),
    "688981": ("SH", "中芯国际", "晶圆代工"),
    "002371": ("SZ", "北方华创", "半导体设备"),
    "688012": ("SH", "中微公司", "刻蚀设备"),
    "603501": ("SH", "韦尔股份", "CIS传感器"),
    "688008": ("SH", "澜起科技", "内存接口"),
    "688256": ("SH", "寒武纪", "AI芯片"),
    "600584": ("SH", "长电科技", "封测"),
    "002185": ("SZ", "华天科技", "封测"),
    "002049": ("SZ", "紫光国微", "FPGA/特种IC"),

    # 消费电子
    "000725": ("SZ", "京东方A", "面板"),
    "002475": ("SZ", "立讯精密", "消费电子"),
    "000100": ("SZ", "TCL科技", "面板"),
    "300866": ("SZ", "安克创新", "消费电子"),

    # 新能源
    "601012": ("SH", "隆基绿能", "光伏硅片"),
    "300274": ("SZ", "阳光电源", "光伏逆变器"),
    "300750": ("SZ", "宁德时代", "动力电池"),
    "002594": ("SZ", "比亚迪", "新能源汽车"),

    # 消费
    "000858": ("SZ", "五粮液", "白酒"),
    "600519": ("SH", "贵州茅台", "白酒"),
    "603288": ("SH", "海天味业", "调味品"),
    "002304": ("SZ", "洋河股份", "白酒"),

    # 金融
    "601318": ("SH", "中国平安", "保险"),
    "600036": ("SH", "招商银行", "银行"),
    "600030": ("SH", "中信证券", "券商"),

    # 医药
    "000538": ("SZ", "云南白药", "中药"),
    "603259": ("SH", "药明康德", "CXO"),
    "300760": ("SZ", "迈瑞医疗", "医疗器械"),

    # 互联网
    "601360": ("SH", "三六零", "网络安全"),
    "300033": ("SZ", "同花顺", "金融科技"),
}


def get_all_stocks() -> dict:
    """返回所有股票池（合并）"""
    all_stocks = {}
    all_stocks.update(SEMI_CONDUCTOR_STOCKS)
    all_stocks.update(CORE_30_STOCKS)
    # 去重
    seen = {}
    for sym, info in all_stocks.items():
        if sym not in seen:
            seen[sym] = info
    return seen


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python stock_fetcher.py <symbol> [market]")
        print("示例: python stock_fetcher.py 603986 SH")
        sys.exit(1)

    sym = sys.argv[1]
    mkt = sys.argv[2] if len(sys.argv) > 2 else ("SH" if sym.startswith(("5", "6", "9")) else "SZ")

    print(f"获取 {sym} ({mkt}) ...")
    df = fetch_stock(sym, mkt)
    print(f"共 {len(df)} 条数据: {df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")
    print(df.tail(3))
