from dataclasses import dataclass, asdict
import hashlib
import json
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Config:
    capital: float = 20000
    holdings: int = 8
    max_weight: float = .20
    value_weight: float = .35
    quality_weight: float = .35
    momentum_weight: float = .30
    min_listing_days: int = 365
    min_amount: float = 20_000_000
    max_roe_age: int = 400
    trend_filter: bool = True
    defensive_exposure: float = .50
    commission_rate: float = .0003
    min_commission: float = 5.0
    slippage: float = .001
    max_participation: float = .01
    cash_buffer: float = .02
    drawdown_alert: float = .15

    def __post_init__(self):
        if self.capital <= 0 or self.holdings < 1 or not 0 < self.max_weight <= 1:
            raise ValueError('Invalid capital / holdings / max_weight')
        if any(x < 0 for x in (self.value_weight, self.quality_weight, self.momentum_weight)):
            raise ValueError('Factor weights must be nonnegative')
        if self.value_weight + self.quality_weight + self.momentum_weight <= 0:
            raise ValueError('At least one factor must be active')
        if not 0 < self.drawdown_alert < 1:
            raise ValueError('Invalid drawdown warning threshold')
        if not 0 <= self.defensive_exposure <= 1 or not 0 <= self.cash_buffer < 1:
            raise ValueError('Invalid exposure / buffer')
        if any(x < 0 for x in (self.commission_rate, self.min_commission, self.slippage)):
            raise ValueError('Costs must be nonnegative')
        if not 0 < self.max_participation <= 1:
            raise ValueError('Invalid participation')

    def identity(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:12]


def mainboard(code):
    return str(code).startswith(('sh.600', 'sh.601', 'sh.603', 'sh.605', 'sz.000', 'sz.001', 'sz.002', 'sz.003'))


def prepare_prices(prices):
    p = prices.copy()
    required = {'date','code','open','high','low','close','preclose','adj_close','amount','volume','tradestatus','isST','peTTM','pbMRQ','ipoDate'}
    if required - set(p):
        raise ValueError(f'Missing price columns: {sorted(required-set(p))}')
    p['date'] = pd.to_datetime(p['date'])
    p['ipoDate'] = pd.to_datetime(p['ipoDate'])
    if p.duplicated(['date','code']).any():
        raise ValueError('Duplicate date / stock observations')
    for col in required - {'date','code','ipoDate'}:
        p[col] = pd.to_numeric(p[col], errors='coerce')
    p = p.sort_values(['code','date'])
    for _, g in p.groupby('code', observed=True):
        if (g.adj_close.dropna() <= 0).any():
            raise ValueError('Nonpositive adjusted prices')
    groups = p.groupby('code', sort=False, observed=True)
    p['momentum'] = groups.adj_close.transform(lambda s: s.shift(20) / s.shift(120) - 1)
    p['volatility'] = groups.adj_close.transform(lambda s: s.pct_change(fill_method=None).rolling(60, min_periods=60).std() * np.sqrt(252))
    p['amount20'] = groups.amount.transform(lambda s: s.rolling(20, min_periods=20).mean())
    return p.set_index('date', drop=False).rename_axis('_date_index').sort_index()


def zscore(s):
    s = s.replace([np.inf, -np.inf], np.nan)
    lo, hi = s.quantile([.025, .975])
    clipped = s.clip(lo, hi)
    sd = clipped.std(ddof=0)
    return (clipped-clipped.mean()) / sd if pd.notna(sd) and sd > 0 else clipped*0


def snapshot(prepared, fundamentals, signal_date, config):
    """Only rows available at signal close; publication date is excluded conservatively."""
    date = pd.Timestamp(signal_date)
    x = (prepared.loc[[date]] if date in prepared.index else prepared.iloc[:0]).copy().set_index('code')
    x = x[x.index.map(mainboard)]
    x = x[(date-x.ipoDate).dt.days.ge(config.min_listing_days) & x.isST.eq(0) & x.tradestatus.eq(1) & x.amount20.ge(config.min_amount) & x.close.gt(0)]
    x['roe'] = np.nan
    if config.quality_weight:
        if fundamentals is None or fundamentals.empty:
            raise ValueError('Quality factor requires historical pubDate / statDate / roeAvg data')
        f = fundamentals.copy()
        f['pubDate'] = pd.to_datetime(f['pubDate'])
        f['statDate'] = pd.to_datetime(f['statDate'])
        f['roeAvg'] = pd.to_numeric(f['roeAvg'], errors='coerce')
        # Use annual ROE only: quarterly cumulative ROE is not comparable across quarters.
        f = f[f.pubDate.lt(date) & f.statDate.dt.month.eq(12) & f.statDate.dt.day.eq(31)]
        f = f.sort_values(['statDate','pubDate']).drop_duplicates('code', keep='last').set_index('code')
        f = f[(date-f.pubDate).dt.days.le(config.max_roe_age)]
        # Annual reports are normally current for a year; reject fiscal periods older than 550 days.
        f = f[(date-f.statDate).dt.days.le(550)]
        x['roe'] = f.roeAvg.reindex(x.index)
    active = {}
    if config.value_weight:
        x = x[x.peTTM.gt(0) & x.pbMRQ.gt(0)]
        active['value'] = config.value_weight
    if config.quality_weight:
        x = x[x.roe.gt(0)]
        active['quality'] = config.quality_weight
    if config.momentum_weight:
        x = x[x.momentum.notna()]
        active['momentum'] = config.momentum_weight
    x = x[x.volatility.notna()]
    if x.empty:
        return x.assign(score=pd.Series(dtype=float))
    x['value'] = (zscore(1/x.peTTM) + zscore(1/x.pbMRQ))/2
    x['quality'] = zscore(x.roe)
    x['momentum_score'] = zscore(x.momentum)
    names = {'value':'value', 'quality':'quality', 'momentum':'momentum_score'}
    x['score'] = sum(w*x[names[k]] for k,w in active.items()) / sum(active.values())
    return x.sort_values(['score'], ascending=False, kind='stable')


def targets(prepared, fundamentals, benchmark, signal_date, config):
    ranked = snapshot(prepared, fundamentals, signal_date, config)
    selected = ranked.head(config.holdings).copy()
    exposure = 1-config.cash_buffer
    if config.trend_filter:
        b = benchmark.loc[:pd.Timestamp(signal_date)].dropna()
        if len(b) < 120:
            raise ValueError('Trend filter requires 120 benchmark sessions before signal')
        if b.iloc[-1] < b.iloc[-120:].mean():
            exposure *= config.defensive_exposure
    if not selected.empty:
        # Inverse volatility within the selected names, with an absolute weight cap.
        raw = (1/selected.volatility.clip(lower=.10))
        w = raw/raw.sum()*exposure
        # Do not redistribute capped weight: leave the remainder in cash.
        selected['target_weight'] = w.clip(upper=config.max_weight)
    else:
        selected['target_weight'] = pd.Series(dtype=float)
    return selected


def stamp_rate(date):
    return .0005 if pd.Timestamp(date) >= pd.Timestamp('2023-08-28') else .001


def fees(notional, side, date, config):
    if notional <= 0:
        return 0.0
    transfer = .00001 if pd.Timestamp(date) >= pd.Timestamp('2022-04-29') else .00002
    return max(config.min_commission, notional*config.commission_rate) + notional*transfer + (notional*stamp_rate(date) if side == 'SELL' else 0)


def metrics(nav, benchmark):
    r = nav.pct_change(fill_method=None).dropna()
    years = (nav.index[-1]-nav.index[0]).days/365.25
    b = benchmark.reindex(nav.index).ffill()
    return {
        'total_return': float(nav.iloc[-1]/nav.iloc[0]-1),
        'annualized_return': float((nav.iloc[-1]/nav.iloc[0])**(1/years)-1) if years > 0 else None,
        'max_drawdown': float((nav/nav.cummax()-1).min()),
        'sharpe_rf0': float(r.mean()/r.std()*np.sqrt(252)) if r.std() > 0 else None,
        'benchmark_return': float(b.iloc[-1]/b.iloc[0]-1),
        'sessions': len(nav),
    }
