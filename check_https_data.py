"""Check anonymous HTTPS data endpoints without installing another data client.

Requests and schemas are based on the official AKShare 1.20.24 adapters. This
checks a few historical records only, not full universe, ST or vintage coverage.
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


def checks():
    common={'fields1':'f1,f2,f3,f4,f5,f6',
            'fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'ut':'7eea3edcaed734bea9cbfc24409ed989','klt':'101',
            'secid':'1.600000','beg':'20251215','end':'20251219'}
    return [
        ('prices_raw','https://push2his.eastmoney.com/api/qt/stock/kline/get',dict(common,fqt='0')),
        ('prices_adjusted','https://push2his.eastmoney.com/api/qt/stock/kline/get',dict(common,fqt='1')),
        ('valuation','https://datacenter-web.eastmoney.com/api/data/v1/get',{
            'reportName':'RPT_VALUEANALYSIS_DET','columns':'ALL','pageSize':'5','pageNumber':'1',
            'sortColumns':'TRADE_DATE','sortTypes':'-1','source':'WEB','client':'WEB',
            'filter':'(SECURITY_CODE="600000")(TRADE_DATE=\'2025-12-19\')'}),
        ('financials','https://datacenter.eastmoney.com/securities/api/data/get',{
            'type':'RPT_F10_FINANCE_MAINFINADATA','sty':'APP_F10_MAINFINADATA',
            'filter':'(SECUCODE="600000.SH")(REPORT_DATE=\'2024-12-31\')',
            'p':'1','ps':'5','sr':'-1','st':'REPORT_DATE','source':'HSF10','client':'PC'}),
    ]


def get_json(url,params,timeout):
    request=urllib.request.Request(url+'?'+urllib.parse.urlencode(params),headers={
        'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/'})
    with urllib.request.urlopen(request,timeout=timeout) as response:
        blob=response.read(1024*1024+1)
        if len(blob)>1024*1024:
            raise ValueError('Small probe response unexpectedly exceeds 1 MiB')
    return json.loads(blob.decode('utf-8-sig'))


def validate(name,payload):
    if name.startswith('prices_'):
        rows=(payload.get('data') or {}).get('klines') or []
        if not rows:
            raise ValueError('No historical price rows returned')
        for row in rows:
            values=row.split(',')
            if len(values)<7 or float(values[2])<=0:
                raise ValueError('Invalid historical price schema')
            day=datetime.strptime(values[0],'%Y-%m-%d')
            if not datetime(2025,12,15)<=day<=datetime(2025,12,19):
                raise ValueError('Price rows are outside the requested historical window')
        return {'rows':len(rows),'first_date':rows[0].split(',')[0], 'last_date':rows[-1].split(',')[0]}
    rows=(payload.get('result') or {}).get('data') or []
    if not rows:
        raise ValueError('No historical valuation/financial records returned')
    required={'TRADE_DATE','PE_TTM','PB_MRQ'} if name=='valuation' else {'REPORT_DATE','NOTICE_DATE','ROEJQ'}
    missing=required-set(rows[0])
    if missing:
        raise ValueError('Missing required fields: '+','.join(sorted(missing)))
    valid=0
    for row in rows:
        if all(row.get(field) not in (None,'','-','--') for field in required):
            date_field='TRADE_DATE' if name=='valuation' else 'REPORT_DATE'
            datetime.strptime(str(row[date_field])[:10],'%Y-%m-%d')
            if name=='valuation':
                if str(row['TRADE_DATE'])[:10]!='2025-12-19':
                    raise ValueError('Valuation does not match the requested historical date')
                if not all(math.isfinite(float(row[k])) for k in ('PE_TTM','PB_MRQ')):
                    raise ValueError('Nonfinite valuation values')
            else:
                if str(row['REPORT_DATE'])[:10]!='2024-12-31' or not math.isfinite(float(row['ROEJQ'])):
                    raise ValueError('Invalid annual report or ROE')
                pub=datetime.strptime(str(row['NOTICE_DATE'])[:10],'%Y-%m-%d')
                fiscal=datetime.strptime(str(row['REPORT_DATE'])[:10],'%Y-%m-%d')
                if pub<fiscal:
                    raise ValueError('Disclosure precedes fiscal period end')
            valid+=1
    if not valid:
        raise ValueError('Required historical fields are empty')
    result={'rows':len(rows),'valid_rows':valid}
    if name=='financials':result['publication_field']='NOTICE_DATE'
    return result


def run_checks(timeout=10,fetch=get_json):
    if not 0<timeout<=60:raise ValueError('timeout must be in (0,60] seconds')
    results=[]
    for name,url,params in checks():
        print('Checking',name,urllib.parse.urlparse(url).hostname,flush=True)
        result={'check':name,'host':urllib.parse.urlparse(url).hostname}
        try:
            result.update(validate(name,fetch(url,params,timeout)),ok=True)
        except urllib.error.HTTPError as exc:
            result.update(ok=False,error_type='HTTPError',http_status=exc.code)
        except Exception as exc:
            # Do not dump response bodies, cookies, process environment or credentials.
            result.update(ok=False,error_type=type(exc).__name__,error=str(exc)[:300])
        results.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    return {'transport':'HTTPS','all_checks_passed':all(r['ok'] for r in results),
            'results':results,'historical_universe_audited':False,
            'historical_ST_available':False,'financial_vintages_verified':False,
            'note':'Small endpoint probes only. Passing does not validate a complete multifactor dataset or strategy.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout',type=int,default=10)
    parser.add_argument('--output',default='https_probe.json')
    args=parser.parse_args(argv)
    if not 0<args.timeout<=60:parser.error('--timeout must be 1–60')
    result=run_checks(args.timeout)
    output=Path(args.output)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Report:',output.resolve(),flush=True)
    print('All HTTPS checks passed:',result['all_checks_passed'],flush=True)
    return 0 if result['all_checks_passed'] else 2


if __name__=='__main__':
    raise SystemExit(main())
