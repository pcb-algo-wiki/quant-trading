import pandas as pd

etf = pd.read_pickle('/Users/tanwei/quant-trading/data/cache/yahoo_510300.pkl')
tnx = pd.read_pickle('/Users/tanwei/quant-trading/data/cache/yahoo_TNX.pkl')

print('ETF date dtype:', etf['date'].dtype)
print('ETF sample:', etf['date'].iloc[0], '...', etf['date'].iloc[-1])
print()
print('TNX date dtype:', tnx['date'].dtype)
print('TNX sample:', tnx['date'].iloc[0], '...', tnx['date'].iloc[-1])
print()

etf_dates = set(etf['date'])
tnx_dates = set(tnx['date'])
common = etf_dates & tnx_dates
print('Common:', len(common))
if len(common) == 0:
    print('No overlap!')
    print('ETF first 3:', sorted(list(etf_dates))[:3])
    print('TNX first 3:', sorted(list(tnx_dates))[:3])
