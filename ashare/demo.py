"""Deterministic SYNTHETIC data for software tests, never investment evidence."""
import numpy as np
import pandas as pd


def synthetic_data():
    rng=np.random.default_rng(17)
    dates=pd.bdate_range('2018-01-01','2024-12-31')
    rows=[];fund=[]
    market=rng.normal(.00015,.009,len(dates))
    for k in range(16):
        code=f'sh.{600000+k:06d}'
        close=(10+k/2)*np.exp(np.cumsum(market*.6+rng.normal(.0001,.012,len(dates))))
        opens=close*np.exp(rng.normal(0,.003,len(dates)))
        for i,d in enumerate(dates):
            rows.append({'date':d,'code':code,'open':opens[i],'high':max(opens[i],close[i])*1.01,'low':min(opens[i],close[i])*.99,
                         'close':close[i],'preclose':close[max(0,i-1)],'adj_close':close[i],
                         'amount':80e6,'volume':8e6,'tradestatus':1,'isST':0,'peTTM':8+k,'pbMRQ':1+k/10,'ipoDate':'2000-01-01'})
        for y in range(2016,2025):
            fund.append({'code':code,'statDate':f'{y}-12-31','pubDate':f'{y+1}-04-20','roeAvg':.06+k*.005})
    benchmark=pd.Series(3500*np.exp(np.cumsum(market)),index=dates,name='HS300')
    return pd.DataFrame(rows),pd.DataFrame(fund),benchmark,{'provider':'SYNTHETIC','not_market_data':True}
