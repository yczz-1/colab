"""Download on a permitted local network, then upload the CSV ZIP to Colab."""
import argparse
from datetime import datetime
from ashare.bundle import export_bundle
from ashare.connection import diagnose_baostock
from ashare.data import load_free


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start',default='2017-01-01')
    parser.add_argument('--end',default='2025-12-31')
    parser.add_argument('--cache-dir',default='data/baostock')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--max-symbols',type=int,default=30)
    group.add_argument('--all-symbols',action='store_true')
    parser.add_argument('--output')
    parser.add_argument('--diagnose-only',action='store_true')
    args=parser.parse_args(argv)
    if args.max_symbols<1:
        parser.error('--max-symbols must be positive')
    if args.diagnose_only:
        result=diagnose_baostock()
        print(result,flush=True)
        return 0 if result['ok'] else 2
    cap=None if args.all_symbols else args.max_symbols
    print('Downloading REAL BaoStock data; no synthetic fallback. A local connection is not guaranteed.',flush=True)
    print('Universe:', 'all provider-discoverable main-board stocks' if cap is None else f'FIRST {cap} STOCKS ONLY — connectivity sample',flush=True)
    p,f,b,m=load_free(start=args.start,end=args.end,cache_dir=args.cache_dir,max_symbols=cap)
    if not m.get('provider','').startswith('BaoStock ') or m.get('not_market_data',False):
        raise RuntimeError('Local downloader must not label synthetic data as real market data')
    if f.empty:
        raise RuntimeError('No annual financial data; refusing to export an incomplete multifactor dataset')
    prefix='market_sample' if cap is not None else 'market_full'
    output=args.output or f'{prefix}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
    path=export_bundle(p,f,b,m,output)
    print(f'REAL DATA BUNDLE: {path}',flush=True)
    print(f'Rows: prices={len(p)}, fundamentals={len(f)}, benchmark={len(b)}',flush=True)
    print('Upload this market_*.zip to Colab in bundle mode. A sample does not validate strategy performance.',flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
