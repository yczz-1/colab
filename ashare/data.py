"""Free BaoStock adapter, resumable CSV cache. No credentials are required."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import socket
import pandas as pd
from .strategy import mainboard


def china_yesterday():
    return (pd.Timestamp.now(tz='Asia/Shanghai').date()-timedelta(days=1)).isoformat()


def _frame(result):
    if result.error_code != '0':
        raise RuntimeError(f'BaoStock {result.error_code}: {result.error_msg}')
    rows=[]
    while result.next():
        rows.append(result.get_row_data())
    if result.error_code != '0':
        raise RuntimeError(f'BaoStock iteration failed: {result.error_msg}')
    return pd.DataFrame(rows,columns=result.fields)


def _close_connection():
    # The SDK keeps a module-global socket even after failed login.
    from baostock.common import context
    connection=getattr(context,'default_socket',None)
    if connection is not None:
        try:
            connection.close()
        except OSError:
            pass
        context.default_socket=None


@contextmanager
def session(login_timeouts=(20,60), query_timeout=30):
    """Retry network login failure once with a fresh socket and longer deadline.

    No retries for authentication errors or exceptions raised by the caller's
    query; successful but empty responses are not treated as connection failures.
    """
    import baostock as bs
    if not 1<=len(login_timeouts)<=3 or any(not 0<t<=120 for t in login_timeouts) or not 0<query_timeout<=120:
        raise ValueError('Invalid connection deadlines')
    previous=socket.getdefaulttimeout()
    connected=False
    last_error='unknown connection error'
    try:
        for attempt,timeout in enumerate(login_timeouts,1):
            _close_connection()
            socket.setdefaulttimeout(timeout)
            print(f'BaoStock login {attempt}/{len(login_timeouts)}; socket timeout={timeout}s',flush=True)
            try:
                login=bs.login()
                if login.error_code=='0':
                    connected=True
                    break
                last_error=f'{login.error_code}: {login.error_msg}'
                # BaoStock reserves 100020xx for network/transport failures.
                if not str(login.error_code).startswith('100020'):
                    break
            except OSError as exc:
                last_error=f'{type(exc).__name__}: {exc}'
        if not connected:
            raise RuntimeError(
                f'BaoStock login failed ({last_error}). '
                'Run `from ashare.connection import diagnose_baostock; print(diagnose_baostock())` '
                'in Colab to separate TCP, login and query failures. '
                'A timeout alone does not prove missing TCP permission. No demo fallback was used.')
        socket.setdefaulttimeout(query_timeout)
        # setdefaulttimeout only affects new sockets; update the connected SDK socket too.
        from baostock.common import context
        connection=getattr(context,'default_socket',None)
        if connection is not None:
            connection.settimeout(query_timeout)
        yield bs
    finally:
        # Close directly: an SDK logout request could itself block or mask a query exception.
        _close_connection()
        socket.setdefaulttimeout(previous)


def cached(path, fetch):
    path=Path(path)
    if path.exists():
        return pd.read_csv(path,dtype=str,keep_default_na=False)
    result=fetch()
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    result.to_csv(tmp,index=False)
    tmp.replace(path)
    return result


def load_free(start='2018-01-01', end=None, cache_dir='data/baostock', max_symbols=30):
    """max_symbols=None requests the entire discoverable main-board universe.

    Current provider security master includes historical securities to the extent
    supplied by BaoStock. Its historical completeness is not independently proven.
    Every cache key includes the requested end date; do not overwrite earlier vintages.
    """
    end=end or china_yesterday()
    if pd.Timestamp(end)>pd.Timestamp(china_yesterday()):
        raise ValueError('Use completed sessions only: end must be before today in China')
    if pd.Timestamp(start)>=pd.Timestamp(end):
        raise ValueError('start must precede end')
    if max_symbols is not None and max_symbols<1:
        raise ValueError('max_symbols must be positive or None')
    root=Path(cache_dir)/f'{start}_{end}'
    with session() as bs:
        master=cached(root/'master.csv',lambda:_frame(bs.query_stock_basic()))
        universe=master[master.type.eq('1') & master.code.map(mainboard)].sort_values('code')
        # Keep currently delisted names; date filtering happens on historical bars.
        universe=universe[universe.ipoDate.ne('') & universe.ipoDate.le(end)]
        if max_symbols is not None:
            universe=universe.head(max_symbols)
        if universe.empty:
            raise ValueError('Provider returned no eligible securities')
        bfields='date,code,open,high,low,close,preclose,volume,amount,tradestatus,isST,peTTM,pbMRQ'
        frames=[]; reports=[]
        for i,row in enumerate(universe.itertuples(),1):
            code=row.code
            print(f'Downloading / reading cache {i}/{len(universe)}: {code}',flush=True)
            raw=cached(root/code/'raw.csv',lambda:_frame(bs.query_history_k_data_plus(code,bfields,start_date=start,end_date=end,frequency='d',adjustflag='3')))
            adj=cached(root/code/'adj.csv',lambda:_frame(bs.query_history_k_data_plus(code,'date,code,close',start_date=start,end_date=end,frequency='d',adjustflag='2')))
            if not raw.empty:
                merged=raw.merge(adj.rename(columns={'close':'adj_close'}),on=['date','code'],how='left',validate='one_to_one')
                if merged.adj_close.isna().any():
                    raise ValueError(f'Incomplete adjusted history for {code}')
                merged['ipoDate']=pd.Timestamp(row.ipoDate)
                merged['date']=pd.to_datetime(merged['date'])
                for column in set(merged.columns)-{'date','code','ipoDate'}:
                    merged[column]=pd.to_numeric(merged[column],errors='coerce')
                frames.append(merged)
                for year in range(pd.Timestamp(start).year-2,pd.Timestamp(end).year+1):
                    # Annual ROE avoids comparing Q1 cumulative ROE against annual ROE.
                    if year < pd.Timestamp(row.ipoDate).year-1:
                        continue
                    annual=cached(root/code/f'profit_{year}_q4.csv',lambda y=year:_frame(bs.query_profit_data(code,year=y,quarter=4)))
                    if not annual.empty:
                        reports.append(annual)
            if i%10==0 or i==len(universe):
                print(f'Data cached: {i}/{len(universe)} stocks',flush=True)
        bench=cached(root/'hs300.csv',lambda:_frame(bs.query_history_k_data_plus('sh.000300','date,close',start_date=start,end_date=end,frequency='d',adjustflag='3')))
    if not frames or bench.empty:
        raise ValueError('No usable price data; download did not validate the workflow')
    prices=pd.concat(frames,ignore_index=True)
    frames.clear()
    prices['code']=prices['code'].astype('category')
    fundamentals=pd.concat(reports,ignore_index=True) if reports else pd.DataFrame(columns=['code','pubDate','statDate','roeAvg'])
    benchmark=pd.Series(pd.to_numeric(bench.close,errors='raise').to_numpy(),index=pd.to_datetime(bench.date),name='HS300').sort_index()
    hasher=hashlib.sha256()
    for frame in (prices,fundamentals,bench):
        hasher.update('|'.join(frame.columns).encode())
        hasher.update(pd.util.hash_pandas_object(frame,index=False).to_numpy().tobytes())
    digest=hasher.hexdigest()
    metadata={'provider':'BaoStock 0.9.4','start':start,'end':end,'downloaded_at_utc':datetime.now(timezone.utc).isoformat(),
              'symbols':len(universe),'requested_max_symbols':max_symbols,'sample_only':max_symbols is not None,
              'sha256':digest,'historical_universe_audited':False,'financial_vintages_verified':False,
              'warning':'Research data only. Revised financials, delisted coverage, historic ST and corporate actions require independent audit.'}
    root.mkdir(parents=True,exist_ok=True)
    (root/'manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    return prices,fundamentals,benchmark,metadata
