"""Ex-post factor diagnostics; not trading signals or execution returns."""
import numpy as np
import pandas as pd
from .strategy import prepare_prices,snapshot


def factor_diagnostics(prices,fundamentals,benchmark,config,start,end):
    p=prepare_prices(prices)
    calendar=benchmark.loc[:pd.Timestamp(end)].index
    pairs=[(calendar[i-1],calendar[i]) for i in range(1,len(calendar))
           if calendar[i].to_period('W-FRI')!=calendar[i-1].to_period('W-FRI')]
    opens=p.assign(adj_open=p.open*p.adj_close/p.close).pivot(index='date',columns='code',values='adj_open')
    records=[]
    for (signal,entry),(_,exit_date) in zip(pairs,pairs[1:]):
        if signal<pd.Timestamp(start) or exit_date>pd.Timestamp(end):
            continue
        x=snapshot(p,fundamentals,signal,config)
        if len(x)<10 or entry not in opens.index or exit_date not in opens.index:
            continue
        x['forward_return']=(opens.loc[exit_date]/opens.loc[entry]-1).reindex(x.index)
        for col in ('value','quality','momentum_score','score'):
            g=x[[col,'forward_return']].replace([np.inf,-np.inf],np.nan).dropna()
            if len(g)<10 or g[col].nunique()<2:
                continue
            ranks=g[col].rank(method='average')
            ic=float(ranks.corr(g.forward_return.rank(method='average')))
            # First-rank breaks ties deterministically, five equally sized groups.
            bins=pd.qcut(g[col].rank(method='first'),5,labels=False)
            grouped=g.groupby(bins).forward_return.mean()
            records.append({'signal_date':signal,'entry_date':entry,'exit_date':exit_date,'factor':col,
                            'n':len(g),'rank_ic':ic,'bottom_return':grouped.loc[0],
                            'top_return':grouped.loc[4],'top_minus_bottom':grouped.loc[4]-grouped.loc[0]})
    detail=pd.DataFrame(records)
    if detail.empty:
        raise ValueError('No diagnostic observations: need >=10 eligible stocks and several weeks')
    summary=detail.groupby('factor').agg(weeks=('rank_ic','size'),mean_rank_ic=('rank_ic','mean'),
                                       positive_ic_fraction=('rank_ic',lambda s:(s>0).mean()),
                                       mean_weekly_top_bottom=('top_minus_bottom','mean'),mean_coverage=('n','mean'))
    return detail,summary
