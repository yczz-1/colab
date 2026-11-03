"""Portable, checksum-verified CSV bundles. Loading performs no network requests."""
import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

PRICE_COLUMNS={'date','code','open','high','low','close','preclose','adj_close','amount','volume','tradestatus','isST','peTTM','pbMRQ','ipoDate'}
FUND_COLUMNS={'code','pubDate','statDate','roeAvg'}
MEMBERS={'prices.csv','fundamentals.csv','benchmark.csv','manifest.json'}


def _sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def _validate(prices,fundamentals,benchmark):
    if PRICE_COLUMNS-set(prices) or FUND_COLUMNS-set(fundamentals):
        raise ValueError('Missing required price or historical fundamentals columns')
    if prices.empty or benchmark.empty:
        raise ValueError('Price data and benchmark cannot be empty')
    if prices.duplicated(['date','code']).any() or benchmark.index.duplicated().any():
        raise ValueError('Duplicate price keys or benchmark dates')
    for column in ('date','ipoDate'):
        dates=pd.to_datetime(prices[column],errors='raise')
        if dates.isna().any():
            raise ValueError('Missing stock dates')
    if benchmark.index.hasnans:
        raise ValueError('Missing benchmark dates')
    if prices[['date','code','ipoDate']].isna().any().any() or not prices.code.astype(str).str.fullmatch(r'(sh|sz)\.\d{6}').all():
        raise ValueError('Missing dates or invalid stock identifiers')
    if not np.isfinite(benchmark.to_numpy(dtype=float)).all() or (benchmark<=0).any():
        raise ValueError('Invalid benchmark prices')
    usable=pd.to_numeric(prices.adj_close,errors='coerce')
    if not usable.gt(0).any() or usable.le(0).any():
        raise ValueError('No usable positive adjusted stock prices')
    if not fundamentals.empty:
        if fundamentals[['code','pubDate','statDate']].isna().any().any():
            raise ValueError('Financial records require publication and fiscal dates')
        if (pd.to_datetime(fundamentals.pubDate)<pd.to_datetime(fundamentals.statDate)).any():
            raise ValueError('Financial publication precedes fiscal period end')


def export_bundle(prices,fundamentals,benchmark,metadata,output):
    """Write a new archive atomically; never overwrite a previous data vintage."""
    _validate(prices,fundamentals,benchmark)
    output=Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent,prefix='.bundle-') as tmp:
        tmp=Path(tmp)
        prices.to_csv(tmp/'prices.csv',index=False)
        fundamentals.to_csv(tmp/'fundamentals.csv',index=False)
        pd.DataFrame({'date':benchmark.index,'close':benchmark.to_numpy()}).to_csv(tmp/'benchmark.csv',index=False)
        hashes={name:_sha(tmp/name) for name in sorted(MEMBERS-{'manifest.json'})}
        manifest={'schema_version':1,'created_at_utc':datetime.now(timezone.utc).isoformat(),
                  'metadata':metadata,'files_sha256':hashes,
                  'rows':{'prices':len(prices),'fundamentals':len(fundamentals),'benchmark':len(benchmark)}}
        (tmp/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        archive=tmp/'ready.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
            for name in sorted(MEMBERS):
                z.write(tmp/name,name)
        # Exclusive creation protects existing exports, including a concurrent writer.
        try:
            with output.open('xb') as dest,archive.open('rb') as source:
                shutil.copyfileobj(source,dest)
        except FileExistsError:
            raise
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    return output


def load_bundle(path,max_uncompressed_bytes=4*1024**3):
    """Read CSV only; never unpickle, execute archive contents, or contact BaoStock.

    Checksums detect accidental corruption; they do not authenticate a data vendor
    or prove historical data correctness. Only load bundles from trusted sources.
    """
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(MEMBERS) or set(names)!=MEMBERS:
            raise ValueError('Expected only prices.csv, fundamentals.csv, benchmark.csv and manifest.json')
        if sum(info.file_size for info in z.infolist())>max_uncompressed_bytes:
            raise ValueError('Bundle exceeds uncompressed size limit')
        if z.getinfo('manifest.json').file_size>1024*1024:
            raise ValueError('Manifest is unexpectedly large')
        manifest=json.loads(z.read('manifest.json'))
        if manifest.get('schema_version')!=1 or set(manifest.get('files_sha256',{}))!=MEMBERS-{'manifest.json'}:
            raise ValueError('Unsupported bundle manifest')
        for name,expected in manifest['files_sha256'].items():
            h=hashlib.sha256()
            with z.open(name) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):
                    h.update(block)
            if h.hexdigest()!=expected:
                raise ValueError(f'Checksum mismatch: {name}')
        with z.open('prices.csv') as stream:
            prices=pd.read_csv(stream,dtype={'code':str},parse_dates=['date','ipoDate'])
        with z.open('fundamentals.csv') as stream:
            fundamentals=pd.read_csv(stream,dtype={'code':str},parse_dates=['pubDate','statDate'])
        with z.open('benchmark.csv') as stream:
            b=pd.read_csv(stream,parse_dates=['date'])
        if set(b)!= {'date','close'}:
            raise ValueError('Invalid benchmark schema')
    benchmark=pd.Series(pd.to_numeric(b.close,errors='raise').to_numpy(),index=pd.DatetimeIndex(b.date),name='HS300').sort_index()
    _validate(prices,fundamentals,benchmark)
    actual={'prices':len(prices),'fundamentals':len(fundamentals),'benchmark':len(benchmark)}
    if manifest.get('rows')!=actual:
        raise ValueError('Manifest row counts do not match data')
    metadata=dict(manifest.get('metadata',{}))
    metadata['source_dataframe_sha256']=metadata.get('sha256')
    metadata['sha256']=hashlib.sha256(json.dumps(manifest['files_sha256'],sort_keys=True).encode()).hexdigest()
    metadata['loaded_from_bundle']=True
    # Never promote a sample, synthetic source, or unverified financial vintage.
    metadata.setdefault('sample_only',True)
    metadata.setdefault('historical_universe_audited',False)
    metadata.setdefault('financial_vintages_verified',False)
    prices['code']=prices['code'].astype('category')
    return prices,fundamentals,benchmark,metadata
