"""Total-return research engine. Fractional positions, NOT an execution simulator."""
from dataclasses import asdict
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .strategy import prepare_prices, targets, fees, metrics


def backtest(prices, fundamentals, benchmark, config, start, end):
    p = prepare_prices(prices)
    benchmark = benchmark.copy().sort_index()
    benchmark.index = pd.to_datetime(benchmark.index)
    if benchmark.index.duplicated().any() or benchmark.isna().any() or (benchmark<=0).any():
        raise ValueError('Benchmark must have unique dates and positive, nonmissing prices')
    calendar = benchmark.loc[pd.Timestamp(start):pd.Timestamp(end)].index
    if len(calendar) and ((calendar[0]-pd.Timestamp(start)).days>7 or (pd.Timestamp(end)-calendar[-1]).days>7):
        raise ValueError('Requested interval is not covered by benchmark data')
    if len(calendar) < 2:
        raise ValueError('At least two benchmark sessions required')
    # Signal on the last session of the previous week; execute at next week's first session.
    full_calendar = benchmark.index[benchmark.index <= pd.Timestamp(end)]
    schedule = {full_calendar[i]:full_calendar[i-1] for i in range(1,len(full_calendar))
                if full_calendar[i].to_period('W-FRI') != full_calendar[i-1].to_period('W-FRI')}
    byday = {d:g.set_index('code') for d,g in p.groupby('date')}
    cash, units, marks = config.capital, {}, {}
    rows, trades, skipped = [], [], []
    for date in calendar:
        day = byday.get(date, pd.DataFrame())
        if day.empty:
            raise ValueError(f'Missing entire stock session {date.date()}')
        # Adjusted open is used for research valuation; never used as a real order quote.
        adjopen = day.open * day.adj_close/day.close
        for code in units:
            if code not in day.index or pd.isna(day.loc[code,'adj_close']):
                raise ValueError(f'Missing held-stock valuation: {date.date()} {code}')
        opening_equity = cash + sum(u*adjopen.loc[c] for c,u in units.items())
        if date in schedule:
            signal = schedule[date]
            selection = targets(p, fundamentals, benchmark, signal, config)
            signal_day = byday.get(signal, pd.DataFrame())
            desired = selection.target_weight.to_dict()
            allcodes = sorted(set(units) | set(desired))
            deltas = {}
            for code in allcodes:
                if code not in day.index or not np.isfinite(adjopen.get(code, np.nan)) or adjopen.get(code, 0) <= 0:
                    skipped.append({'date':str(date.date()),'code':code,'reason':'missing execution quote'})
                    continue
                row = day.loc[code]
                current = units.get(code,0)*adjopen[code]
                delta = desired.get(code,0)*opening_equity-current
                if abs(delta) < 1:
                    continue
                side = 'BUY' if delta > 0 else 'SELL'
                rate = .05 if row.isST == 1 else .10
                # First-year IPOs excluded from selection. Conservatively block opening limits.
                limit = round(float(row.preclose)*(1+rate if side=='BUY' else 1-rate)+1e-8,2)
                blocked = row.tradestatus != 1 or row.volume <= 0 or row.open <= 0
                blocked |= (row.open >= limit-.001 if side=='BUY' else row.open <= limit+.001)
                if blocked:
                    skipped.append({'date':str(date.date()),'code':code,'reason':'suspension / opening price limit'})
                    continue
                # Uses previous signal-day volume only, avoiding today's full-session liquidity.
                cap = float(signal_day.loc[code,'amount20'])*config.max_participation if code in signal_day.index else 0
                deltas[code] = np.sign(delta)*min(abs(delta),cap)
            for side in ('SELL','BUY'):
                for code,delta in deltas.items():
                    if (delta > 0) != (side=='BUY'):
                        continue
                    notional = abs(delta)
                    if side=='BUY':
                        # Reserve fees and slippage, reducing target purchase when cash is short.
                        notional = min(notional, max(0,(cash-config.min_commission)/(1+config.slippage+config.commission_rate+.00002)))
                    else:
                        notional = min(notional,units.get(code,0)*adjopen[code])
                    if notional <= 0:
                        continue
                    cost = fees(notional,side,date,config)+notional*config.slippage
                    if side=='BUY' and notional+cost > cash+1e-7:
                        continue
                    change = notional/adjopen[code] * (1 if side=='BUY' else -1)
                    units[code] = units.get(code,0)+change
                    if abs(units[code]) < 1e-9:
                        units.pop(code,None)
                    cash += -notional-cost if side=='BUY' else notional-cost
                    trades.append({'date':date,'signal_date':signal,'code':code,'side':side,'notional':notional,'estimated_cost':cost})
        for code,u in units.items():
            marks[code] = float(day.loc[code,'adj_close'])
        nav = cash + sum(u*marks[c] for c,u in units.items())
        if not np.isfinite(nav) or cash < -1e-6:
            raise ValueError('Invalid accounting state')
        rows.append({'date':date,'nav':nav,'cash':cash,'positions':len(units)})
    curve = pd.DataFrame(rows).set_index('date')
    # Include initial capital anchor so first-session costs/overnight effects are counted.
    anchor = pd.Series([config.capital],index=[calendar[0]-pd.Timedelta(nanoseconds=1)])
    nav_for_metrics = pd.concat([anchor,curve.nav])
    bench_for_metrics = pd.concat([pd.Series([benchmark.loc[:calendar[0]].iloc[-1]],index=anchor.index),benchmark])
    report = metrics(nav_for_metrics,bench_for_metrics)
    trade_frame = pd.DataFrame(trades,columns=['date','signal_date','code','side','notional','estimated_cost'])
    report['sessions'] = len(curve)
    report['drawdown_alert'] = config.drawdown_alert
    report['drawdown_alert_breached'] = bool(report['max_drawdown'] <= -config.drawdown_alert)
    report.update({'mode':'RESEARCH_ONLY_FRACTIONAL_TOTAL_RETURN',
                   'estimated_cost':float(trade_frame.estimated_cost.sum()),
                   'gross_traded_notional':float(trade_frame.notional.sum()),
                   'config':asdict(config),'config_id':config.identity(),
                   'limitations':[
                       'Fractional positions; cash dividends assumed reinvested through adjusted prices.',
                       'No verified historical disclosure vintages or complete delisted-stock audit.',
                       'No dividend tax, delisting settlement or auction queue simulation.',
                       'No integer-lot execution performance claim; do not use as live approval.']})
    return curve,trade_frame,pd.DataFrame(skipped),report


def save_run(result, path, metadata=None):
    """Use a new directory for each run; refuse to overwrite experiments."""
    path=Path(path)
    path.mkdir(parents=True,exist_ok=False)
    curve,trades,skipped,report=result
    curve.to_csv(path/'nav.csv')
    trades.to_csv(path/'trades.csv',index=False)
    skipped.to_csv(path/'skipped.csv',index=False)
    report['data_metadata']=metadata or {}
    (path/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    returns=curve.nav.resample('YE').last().pct_change()
    # First calendar year starts at configured initial capital.
    if len(returns):
        returns.iloc[0]=curve.nav.resample('YE').last().iloc[0]/report['config']['capital']-1
    returns.rename('return').to_csv(path/'annual_returns.csv')
