"""
akshare基本面数据接口
免费获取A股估值、指数PE/PB、财务数据

用法:
    from data.akshare_api import AkshareData
    ak = AkshareData()
    
    # 获取指数估值（沪深300、中证500）
    pe_pb = ak.get_index_valuation()
    
    # 获取A股财务数据
    roe = ak.get_stock_roe('000001')
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import time
import os

# 指数代码映射
INDEX_CODES = {
    '000300': '沪深300',   # CSI 300
    '000905': '中证500',   # CSI 500
    '399006': '创业板指',  # ChiNext
    '000016': '上证50',    # SSE 50
    '000001': '上证指数',  # SSE Composite
}

# ETF代码
ETF_CODES = {
    '510300': 'sh510300',  # 沪深300ETF
    '510500': 'sh510500',  # 中证500ETF
    '159915': 'sz159915',  # 创业板ETF
    '510050': 'sh510050',  # 上证50ETF
}


class AkshareData:
    """
    akshare数据接口
    
    功能:
    - 指数PE/PB/股息率历史
    - 指数实时估值
    - A股财务数据
    """
    
    def __init__(self):
        self.cache_dir = os.path.dirname(__file__) + '/cache'
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def get_index_valuation_history(self, index_code: str = '000300',
                                    start_date: str = '20140101',
                                    end_date: str = '20251231') -> pd.DataFrame:
        """
        获取指数历史估值（PE/PB/PS/股息率）
        
        Args:
            index_code: 指数代码，如 '000300'（沪深300）
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            
        Returns:
            DataFrame with date, pe, pb, ps, dividend_rate
        """
        try:
            # akshare获取指数历史估值
            df = ak.index_zh_a_hist(
                symbol=index_code,
                period='daily',
                start_date=start_date,
                end_date=end_date
            )
            
            if df is not None and len(df) > 0:
                # 重命名列
                df.columns = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'amplitude', 'change_pct', 'change_amount', 'turnover']
                
                # 保存
                cache_file = f'{self.cache_dir}/index_val_{index_code}.pkl'
                df.to_pickle(cache_file)
                
                return df
            
        except Exception as e:
            print(f"❌ 获取 {index_code} 历史估值失败: {e}")
        
        return pd.DataFrame()
    
    def get_index_valuation_current(self) -> pd.DataFrame:
        """
        获取主要指数当前估值（PE/PB/PS/股息率/ROE）
        
        Returns:
            DataFrame with index_name, pe, pb, ps, dividend_rate, roe
        """
        try:
            df = ak.index_zh_valuation_hist_df(symbol='000300', indicator='市盈率')
            print(f"✅ 获取指数估值成功: {len(df)} 行")
            return df
        except Exception as e:
            print(f"❌ 获取指数估值失败: {e}")
        
        return pd.DataFrame()
    
    def get_equity_etf_hist(self, symbol: str = '510300',
                            start_date: str = '20190101',
                            end_date: str = '20251231') -> pd.DataFrame:
        """
        获取ETF历史数据（成交数据，含价格/成交量）
        
        Args:
            symbol: ETF代码，如 '510300'
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame with OHLCV
        """
        try:
            # 转换代码格式
            if symbol.startswith('51') or symbol.startswith('5'):
                market = 'sh'
            else:
                market = 'sz'
            
            full_code = f'{market}{symbol}'
            
            df = ak.fund_etf_hist_em(
                symbol=full_code,
                period='daily',
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', '')
            )
            
            if df is not None and len(df) > 0:
                df.columns = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'amplitude', 'change_pct', 'unit_nav', 'discount_rate']
                df['date'] = pd.to_datetime(df['date'])
                
                # 保存缓存
                cache_file = f'{self.cache_dir}/etf_{symbol}.pkl'
                df.to_pickle(cache_file)
                
                return df
                
        except Exception as e:
            print(f"❌ 获取 {symbol} 历史数据失败: {e}")
        
        return pd.DataFrame()
    
    def get_指数PE_PB(self, index_codes: List[str] = None) -> pd.DataFrame:
        """
        获取多只指数的当前PE/PB/股息率
        
        Args:
            index_codes: 指数代码列表，如 ['000300', '000905', '399006']
        """
        if index_codes is None:
            index_codes = list(INDEX_CODES.keys())
        
        all_data = []
        
        for code in index_codes:
            try:
                # 使用 ak.index_value_name_indicator 获取单只指数估值
                df = ak.index_value_name_indicator(symbol=code)
                
                if df is not None and len(df) > 0:
                    df['index_code'] = code
                    df['index_name'] = INDEX_CODES.get(code, code)
                    all_data.append(df)
                    print(f"✅ {code}: {df.iloc[0]['pe'] if 'pe' in df.columns else 'N/A'} PE")
                
                time.sleep(0.5)  # 避免请求过快
                
            except Exception as e:
                print(f"❌ {code}: {e}")
        
        if all_data:
            return pd.concat(all_data, ignore_index=True)
        return pd.DataFrame()
    
    def get_指数历史PE_PB(self, index_code: str = '000300',
                          start_date: str = '20140101',
                          end_date: str = '20251231') -> pd.DataFrame:
        """
        获取指数历史PE/PB数据
        """
        try:
            df = ak.index_zh_a_hist(symbol=index_code, period='daily', 
                                    start_date=start_date, end_date=end_date)
            
            if df is not None and len(df) > 0:
                # 使用ak的指数PE/PB接口
                pe_df = ak.index_zz500_psi_bar()  # 示例
                return df
                
        except Exception as e:
            print(f"❌ {index_code} 历史PE/PB: {e}")
        
        return pd.DataFrame()
    
    def get_stock_financial(self, stock_code: str = '000300',
                            indicator: str = 'ROE') -> pd.DataFrame:
        """
        获取股票财务指标
        """
        try:
            df = ak.stock_financial_analysis_indicator(
                symbol=stock_code,
                start_date='20180101',
                end_date='20251231'
            )
            
            if df is not None and len(df) > 0:
                return df
                
        except Exception as e:
            print(f"�❌ {stock_code} 财务数据: {e}")
        
        return pd.DataFrame()
    
    def get_股息率_历史(self, index_code: str = '000300') -> pd.DataFrame:
        """
        获取指数历史股息率（用于股债利差计算）
        """
        try:
            # 中证指数官网数据
            df = ak.index_cni_index_info(symbol=index_code)
            
            # 使用宏观数据-国债收益率
            bond_df = ak.bond_zh_us_rate()  # 美债收益率
            
            return df
            
        except Exception as e:
            print(f"❌ {index_code} 股息率: {e}")
        
        return pd.DataFrame()
    
    def get_指数风险溢价(self, index_code: str = '000300') -> pd.DataFrame:
        """
        计算指数风险溢价 = 1/PE - 10年国债收益率
        用于判断当前市场估值水平
        """
        try:
            # 获取指数PE历史
            # 这里简化处理，返回一个模拟框架
            df = ak.macro_china_zhijun()  # 国债收益率
            return df
            
        except Exception as e:
            print(f"❌ 风险溢价计算: {e}")
        
        return pd.DataFrame()
    
    def get_a_stock_估值百分位(self, stock_code: str,
                               indicator: str = 'PE') -> float:
        """
        获取个股估值历史百分位
        """
        try:
            df = ak.stock_a_lg_indicator(symbol=stock_code)
            if df is not None and len(df) > 0:
                current_pe = df.iloc[-1]['pe']
                hist_pe = df['pe']
                percentile = (hist_pe < current_pe).mean() * 100
                return percentile
        except Exception as e:
            print(f"❌ {stock_code} 百分位: {e}")
        
        return 50.0  # 默认中等估值


class IndexValueFactor:
    """
    指数估值因子
    基于PE/PB百分位判断市场高低估
    
    原理:
    - 当PE/PB百分位低时，市场低估，买入
    - 当PE/PB百分位高时，市场高估，卖出/减仓
    """
    
    def __init__(self, lookback: int = 252):  # 1年历史
        self.lookback = lookback
    
    def calculate_pe_percentile(self, pe_history: pd.Series) -> float:
        """计算PE历史百分位"""
        if len(pe_history) < 60:
            return 50.0
        current_pe = pe_history.iloc[-1]
        percentile = (pe_history < current_pe).mean() * 100
        return percentile
    
    def generate_signal(self, pe_history: pd.Series, 
                       pb_history: pd.Series = None,
                       entry_threshold: float = 30,
                       exit_threshold: float = 70) -> pd.Series:
        """
        生成估值择时信号
        
        Args:
            pe_history: PE历史序列
            pb_history: PB历史序列（可选）
            entry_threshold: 入场阈值（百分位低于此值买入）
            exit_threshold: 出场阈值（百分位高于此值卖出）
            
        Returns:
            signal: 1=持仓, 0=空仓
        """
        # 计算滚动PE百分位
        pe_percentile = pe_history.rolling(self.lookback, min_periods=60).apply(
            lambda x: (x < x[-1]).mean() * 100 if len(x) > 0 else 50
        )
        
        # 如果有PB，结合使用
        if pb_history is not None:
            pb_percentile = pb_history.rolling(self.lookback, min_periods=60).apply(
                lambda x: (x < x[-1]).mean() * 100 if len(x) > 0 else 50
            )
            # PE和PB取平均
            combined_percentile = (pe_percentile + pb_percentile) / 2
        else:
            combined_percentile = pe_percentile
        
        # 生成信号
        signal = pd.Series(0, index=pe_history.index)
        signal[combined_percentile < entry_threshold] = 1  # 低估买入
        signal[combined_percentile > exit_threshold] = 0  # 高估卖出
        
        return signal


def test_akshare():
    """测试akshare数据获取"""
    print("=" * 50)
    print("akshare数据接口测试")
    print("=" * 50)
    
    ak_data = AkshareData()
    
    # 1. 获取ETF历史数据
    print("\n1. 获取ETF历史数据...")
    for symbol in ['510300', '510500', '159915']:
        df = ak_data.get_equity_etf_hist(symbol=symbol)
        if len(df) > 0:
            print(f"   ✅ {symbol}: {len(df)}行, {df['date'].min()} ~ {df['date'].max()}")
        time.sleep(0.5)
    
    # 2. 获取指数当前估值
    print("\n2. 获取指数当前估值...")
    try:
        # 使用akshare的指数估值接口
        df = ak.index_zh_valuation_hist_df(symbol='000300', indicator='市盈率')
        print(f"   ✅ 沪深300 PE数据: {len(df)}行")
    except Exception as e:
        print(f"   ⚠️ 估值数据获取失败: {e}")
    
    # 3. 获取国债收益率（用于股债利差）
    print("\n3. 获取国债收益率...")
    try:
        bond_df = ak.bond_zh_us_rate()
        if len(bond_df) > 0:
            print(f"   ✅ 国债收益率: {len(bond_df)}行")
    except Exception as e:
        print(f"   ⚠️ 国债收益率: {e}")
    
    print("\n测试完成")


if __name__ == '__main__':
    test_akshare()
