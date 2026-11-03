"""Indicative pre-market limit orders. Always reconcile against the broker."""
import math
import pandas as pd
from .strategy import fees


def plan_orders(selection, holdings, quotes, cash, date, config):
    """holdings: code/shares/sellable. quotes indexed code: price, upper, lower, tradable.

    Buy sizing uses current cash only. Pending sells do NOT fund the buy list.
    Selection weights come from the last completed signal session.
    """
    if cash < 0 or holdings.duplicated('code').any() or selection.index.duplicated().any() or quotes.index.duplicated().any():
        raise ValueError('Negative cash or duplicate codes')
    if not {'shares','sellable','code'} <= set(holdings):
        raise ValueError('holdings requires code, shares, sellable')
    if not {'price','upper','lower','tradable'} <= set(quotes):
        raise ValueError('quotes requires price, upper, lower, tradable')
    for col in ('shares','sellable'):
        if holdings[col].isna().any() or (holdings[col] < 0).any() or (holdings[col] % 1 != 0).any():
            raise ValueError('Holdings must be nonnegative integer shares')
    if (holdings.sellable > holdings.shares).any():
        raise ValueError('Sellable exceeds holdings')
    if selection.target_weight.isna().any() or (selection.target_weight < 0).any() or selection.target_weight.sum() > 1+1e-8 or (selection.target_weight > config.max_weight+1e-8).any():
        raise ValueError('Invalid target weights')
    if not quotes.tradable.isin([True, False, 0, 1]).all():
        raise ValueError('tradable must be boolean / 0 / 1, not CSV strings')
    h=holdings.set_index('code')
    codes=set(h.index)|set(selection.index)
    if codes-set(quotes.index):
        raise ValueError(f'Missing quotes: {sorted(codes-set(quotes.index))}')
    if any(not math.isfinite(float(quotes.loc[c,k])) for c in codes for k in ('price','upper','lower')) or any(quotes.loc[c,'price']<=0 for c in codes):
        raise ValueError('Invalid valuation quote')
    equity=cash+sum(float(row.shares)*float(quotes.loc[c,'price']) for c,row in h.iterrows())
    budget=cash
    result=[]
    # Preserve ranking: better-ranked buys receive the available current cash first.
    ordered=list(selection.index)+sorted(set(h.index)-set(selection.index))
    for code in ordered:
        q=quotes.loc[code]
        current=int(h.loc[code,'shares']) if code in h.index else 0
        sellable=int(h.loc[code,'sellable']) if code in h.index else 0
        weight=float(selection.loc[code,'target_weight']) if code in selection.index else 0
        buy_limit=math.ceil(float(q.price)*(1+config.slippage)*100-1e-8)/100
        sell_limit=math.floor(float(q.price)*(1-config.slippage)*100+1e-8)/100
        desired=math.floor(equity*weight/buy_limit/100)*100
        delta=desired-current
        if delta >= 100:
            side='BUY'; price=buy_limit
            qty=math.floor(delta/100)*100
        elif delta < 0:
            side='SELL'; price=sell_limit
            # Only an entire residual position may be sold as an odd lot.
            wanted=min(-delta,sellable)
            qty=wanted if wanted==current else math.floor(wanted/100)*100
        else:
            side='HOLD'; price=float(q.price); qty=0
        reason='lot_constraint' if side=='HOLD' and (delta>0 or (weight>0 and current==0 and desired==0)) else 'manual_review_required'
        if not bool(q.tradable) or not (0 < q.lower <= q.price <= q.upper):
            qty=0;reason='quote_untradable_or_invalid'
        elif (side=='BUY' and price>=q.upper) or (side=='SELL' and price<=q.lower):
            qty=0;reason='opening_limit_or_price_buffer'
        if side=='BUY':
            while qty > 0 and qty*price+fees(qty*price,side,date,config)>budget:
                qty-=100
            if qty==0 and reason=='manual_review_required':
                reason='cash_or_lot_constraint'
            budget-=qty*price+fees(qty*price,side,date,config)
        elif side=='SELL' and qty==0 and current>desired and reason=='manual_review_required':
            reason='T1_or_lot_constraint'
        result.append({'code':code,'side':side,'shares':qty,'limit_price':price,
                       'estimated_fee':fees(qty*price,side,date,config),'current_shares':current,
                       'target_weight':weight,'reason':reason})
    return pd.DataFrame(result),{'equity':equity,'cash_before':cash,'cash_after_buys_without_sales':budget,
                                 'status':'INDICATIVE_ONLY_REPLACE_QUOTES_AND_REVIEW_WITH_BROKER'}
