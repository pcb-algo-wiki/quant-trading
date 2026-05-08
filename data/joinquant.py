"""
聚宽数据接口
使用 jqdatasdk 免费获取A股基本面数据

聚宽账号注册: https://www.joinquant.com
免费额度: 日线数据、财务数据、因子数据

用法:
    from data.joinquant import JoinQuantData
    jq = JoinQuantData()
    jq.auth('你的账号', '密码')
    
    # 获取ETF成分股财务数据
    df = jq.get_financial_data(['510300'])
    
    # 获取估值因子
    factors = jq.get_valuation_factors(['510300', '510500'])
"""

import jqdatasdk as jq
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import os

# 聚宽ETF代码映射（jqdatasdk使用不同格式）
JQ_ETF_MAP = {
    '510300': '510300.XSHG',  # 沪深300ETF
    '510500': '510500.XSHG',  # 中证500ETF
    '159915': '159915.XSHE',  # 创业板ETF
    '510050': '510050.XSHG',  # 上证50ETF
    '512100': '512100.XSHG',  # 中证100ETF
    '159919': '159919.XSHE',  # 沪深300ETF(实物)
}

# A股市场代码
MARKET_CODE = {
    'XSHG': 'sh',  # 上海
    'XSHE': 'sz',  # 深圳
}

# 财务因子列表
FINANCIAL_FACTORS = {
    # 估值因子
    'pe_ratio': '市盈率(PE)',
    'pb_ratio': '市净率(PB)',
    'ps_ratio': '市销率(PS)',
    'pcf_ratio': '市现率(PCF)',
    
    # 财务因子
    'roe': '净资产收益率(ROE)',
    'roa': '资产收益率(ROA)',
    'gross_margin': '毛利率',
    'net_margin': '净利率',
    'debt_to_assets': '资产负债率',
    'current_ratio': '流动比率',
    'quick_ratio': '速动比率',
    
    # 成长因子
    'revenue_growth': '营收增长率',
    'profit_growth': '利润增长率',
    'asset_growth': '资产增长率',
    'equity_growth': '净资产增长率',
    
    # 股息因子
    'dividend_ratio': '股息率',
    'dividend_yield': '分红收益率',
}


class JoinQuantData:
    """
    聚宽数据接口
    
    数据类型:
    - get_price: 日线/分钟线行情
    - get_fundamentals: 财务数据
    - get_valuation: 估值数据
    - get_market_cap: 市值数据
    """
    
    def __init__(self):
        self.connected = False
        self._auth_done = False
    
    def auth(self, username: str = None, password: str = None):
        """
        登录聚宽
        
        Args:
            username: 聚宽账号（手机号/邮箱）
            password: 密码
        """
        if username is None:
            username = os.environ.get('JQ_USERNAME')
        if password is None:
            password = os.environ.get('JQ_PASSWORD')
        
        if not username or not password:
            print("[Warn] 未提供聚宽账号密码，尝试从环境变量 JQ_USERNAME/JQ_PASSWORD 读取")
            # 尝试读取配置文件
            config_file = os.path.expanduser('~/.quant/config.json')
            if os.path.exists(config_file):
                import json
                with open(config_file) as f:
                    config = json.load(f)
                    username = config.get('jq_username')
                    password = config.get('jq_password')
        
        if username and password:
            try:
                jq.auth(username, password)
                self._auth_done = True
                print(f"✅ 聚宽登录成功: {username}")
            except Exception as e:
                print(f"❌ 聚宽登录失败: {e}")
                self._auth_done = False
        else:
            print("[Warn] 无聚宽账号，跳过基本面数据")
    
    def get_etf_price(self, symbols: List[str], 
                      start_date: str = '2019-01-01',
                      end_date: str = '2025-12-31',
                      freq: str = 'daily') -> Dict[str, pd.DataFrame]:
        """
        获取ETF价格数据
        
        Args:
            symbols: ETF代码列表，如 ['510300', '510500']
            start_date: 开始日期
            end_date: 结束日期
            freq: 'daily' 或 'weekly'
            
        Returns:
            {symbol: DataFrame} 价格数据
        """
        if not self._auth_done:
            print("[Warn] 未登录聚宽，无法获取数据")
            return {}
        
        result = {}
        
        for symbol in symbols:
            jq_code = JQ_ETF_MAP.get(symbol, f'{symbol}.XSHG')
            
            try:
                df = jq.get_price(
                    jq_code,
                    start_date=start_date,
                    end_date=end_date,
                    frequency='daily' if freq == 'daily' else 'weekly',
                    fields=['open', 'close', 'high', 'low', 'volume', 'money'],
                    skip_paused=True
                )
                
                if df is not None and len(df) > 0:
                    df = df.reset_index()
                    df.columns = ['date', 'open', 'close', 'high', 'low', 'volume', 'money']
                    df['date'] = pd.to_datetime(df['date'])
                    result[symbol] = df
                    print(f"✅ {symbol}: {len(df)}行, {df['date'].min().date()} ~ {df['date'].max().date()}")
                else:
                    print(f"❌ {symbol}: 无数据")
                    
            except Exception as e:
                print(f"❌ {symbol}: {e}")
        
        return result
    
    def get_valuation(self, symbols: List[str],
                      start_date: str = '2019-01-01',
                      end_date: str = '2025-12-31') -> pd.DataFrame:
        """
        获取估值数据（市盈率、市净率、市现率、市销率）
        
        Returns:
            DataFrame with columns: date, symbol, pe, pb, ps, pcf, market_cap
        """
        if not self._auth_done:
            print("[Warn] 未登录聚宽，无法获取估值数据")
            return pd.DataFrame()
        
        all_data = []
        
        for symbol in symbols:
            jq_code = JQ_ETF_MAP.get(symbol, f'{symbol}.XSHG')
            
            try:
                # 使用 get_security_info 获取基本信息
                # 使用财务数据查询
                q = jq.Query(
                    jq.security.Universe.STOCK,
                    jq.data.Valuation(
                        pe_ratio=None, pb_ratio=None, ps_ratio=None, 
                        pcf_ratio=None, market_cap=None
                    )
                )
                
                # 简单方式：使用 get_fundamentals_continuously
                # 但ETF的估值数据需要特殊处理
                
                # 使用 jqdatasdk 的 get_money_flow
                df = jq.get_money_flow(
                    jq_code,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if df is not None and len(df) > 0:
                    df['symbol'] = symbol
                    all_data.append(df)
                    print(f"✅ {symbol} 资金流: {len(df)}行")
                
            except Exception as e:
                print(f"❌ {symbol} 估值: {e}")
        
        if all_data:
            return pd.concat(all_data, ignore_index=True)
        return pd.DataFrame()
    
    def get_financial_metrics(self, symbols: List[str],
                               date: str = None) -> pd.DataFrame:
        """
        获取财务指标（PE、PB、ROE、股息率等）
        
        Args:
            symbols: 股票/ETF代码列表
            date: 查询日期，默认最新
            
        Returns:
            DataFrame with financial metrics
        """
        if not self._auth_done:
            print("[Warn] 未登录聚宽，无法获取财务数据")
            return pd.DataFrame()
        
        if date is None:
            date = datetime.today().strftime('%Y-%m-%d')
        
        all_data = []
        
        for symbol in symbols:
            jq_code = JQ_ETF_MAP.get(symbol, f'{symbol}.XSHG')
            
            try:
                # 获取单只股票/ETF的财务数据
                df = jq.get_fundamentals(
                    jq.Query(jq.security.Security(jq_code)),
                    date=date
                )
                
                if df is not None and len(df) > 0:
                    df['symbol'] = symbol
                    all_data.append(df)
                    
            except Exception as e:
                print(f"❌ {symbol}: {e}")
        
        if all_data:
            result = pd.concat(all_data, ignore_index=True)
            print(f"✅ 获取 {len(result)} 条财务记录")
            return result
        
        return pd.DataFrame()
    
    def get_index_components(self, index_code: str = '000300') -> List[str]:
        """
        获取指数成分股
        
        Args:
            index_code: 指数代码，'000300'=沪深300, '000905'=中证500
            
        Returns:
            成分股代码列表
        """
        if not self._auth_done:
            return []
        
        try:
            stocks = jq.get_index_stocks(index_code)
            print(f"✅ {index_code} 成分股: {len(stocks)} 只")
            return stocks
        except Exception as e:
            print(f"❌ 获取成分股失败: {e}")
            return []
    
    def get_etf_holdings(self, symbol: str, date: str = None) -> pd.DataFrame:
        """
        获取ETF持仓明细（成分股）
        
        Args:
            symbol: ETF代码，如 '510300'
            date: 查询日期
        """
        if not self._auth_done:
            return pd.DataFrame()
        
        jq_code = JQ_ETF_MAP.get(symbol, f'{symbol}.XSHG')
        
        try:
            # 使用 get_security_info 获取ETF持仓
            holdings = jq.get_money_flow(jq_code, date=date)
            return holdings
        except Exception as e:
            print(f"❌ {symbol} 持仓: {e}")
            return pd.DataFrame()
    
    def get_factor_data(self, symbols: List[str],
                         factors: List[str],
                         start_date: str = '2019-01-01',
                         end_date: str = '2025-12-31') -> pd.DataFrame:
        """
        获取指定因子数据
        
        Args:
            symbols: 股票/ETF代码
            factors: 因子列表，如 ['pe_ratio', 'pb_ratio', 'roe']
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame with factor values
        """
        if not self._auth_done:
            return pd.DataFrame()
        
        all_data = []
        
        for symbol in symbols:
            jq_code = JQ_ETF_MAP.get(symbol, f'{symbol}.XSHG')
            
            try:
                # 构建查询
                val_fields = []
                if 'pe_ratio' in factors:
                    val_fields.append('pe_ratio')
                if 'pb_ratio' in factors:
                    val_fields.append('pb_ratio')
                if 'ps_ratio' in factors:
                    val_fields.append('ps_ratio')
                if 'market_cap' in factors:
                    val_fields.append('market_cap')
                
                if val_fields:
                    # 使用循环查询每日数据
                    q = jq.Query(jq.security.Security(jq_code))
                    
                    df = jq.get_fundamentals_continuously(
                        q,
                        end_date=end_date,
                        count=None
                    )
                    
                    if df is not None and len(df) > 0:
                        df['symbol'] = symbol
                        all_data.append(df)
                        
            except Exception as e:
                print(f"❌ {symbol} 因子: {e}")
        
        if all_data:
            return pd.concat(all_data, ignore_index=True)
        return pd.DataFrame()
    
    def save_cache(self, data: Dict[str, pd.DataFrame], name: str):
        """保存数据到缓存"""
        import pickle
        cache_dir = os.path.dirname(__file__) + '/cache'
        os.makedirs(cache_dir, exist_ok=True)
        
        path = f'{cache_dir}/{name}.pkl'
        with open(path, 'wb') as f:
            pickle.dump(data, f)
        print(f"💾 缓存已保存: {path}")
    
    def load_cache(self, name: str) -> Dict[str, pd.DataFrame]:
        """加载缓存数据"""
        import pickle
        cache_dir = os.path.dirname(__file__) + '/cache'
        path = f'{cache_dir}/{name}.pkl'
        
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return pickle.load(f)
        return {}


def test_connection():
    """测试聚宽连接"""
    print("=" * 50)
    print("聚宽数据接口测试")
    print("=" * 50)
    
    jq_data = JoinQuantData()
    
    # 尝试自动读取配置
    config_file = os.path.expanduser('~/.quant/config.json')
    if os.path.exists(config_file):
        import json
        with open(config_file) as f:
            config = json.load(f)
            username = config.get('jq_username')
            password = config.get('jq_password')
            if username and password:
                jq_data.auth(username, password)
            else:
                print("⚠️  配置文件无聚宽账号，跳过登录")
                return jq_data
    else:
        print(f"⚠️  无配置文件 ({config_file})，需要手动设置聚宽账号")
        print("   创建配置文件: ~/.quant/config.json")
        print('   {"jq_username": "你的账号", "jq_password": "你的密码"}')
        return jq_data
    
    # 测试获取数据
    if jq_data._auth_done:
        # 获取沪深300ETF价格
        prices = jq_data.get_etf_price(['510300', '510500', '159915'])
        print(f"\n获取价格数据: {len(prices)} 只ETF")
    
    return jq_data


if __name__ == '__main__':
    test_connection()
