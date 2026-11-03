import unittest
import urllib.error
from unittest.mock import patch
from check_https_data import validate,run_checks


class HttpsProbeTests(unittest.TestCase):
    def test_price_rows_required(self):
        with self.assertRaisesRegex(ValueError,'No historical'):
            validate('prices_raw',{'data':None})
        result=validate('prices_adjusted',{'data':{'klines':['2025-12-19,10,11,12,9,100,1100']}})
        self.assertEqual(result['rows'],1)

    def test_financial_disclosure_required(self):
        with self.assertRaisesRegex(ValueError,'NOTICE_DATE'):
            validate('financials',{'result':{'data':[{'REPORT_DATE':'2024-12-31','ROEJQ':10}]}})

    def test_current_valuation_not_accepted_without_historical_date(self):
        with self.assertRaisesRegex(ValueError,'TRADE_DATE'):
            validate('valuation',{'result':{'data':[{'PE_TTM':10,'PB_MRQ':1}]}})

    def test_missing_required_values_fail(self):
        with self.assertRaisesRegex(ValueError,'empty'):
            validate('financials',{'result':{'data':[{'REPORT_DATE':'2024-12-31','NOTICE_DATE':None,'ROEJQ':10}]}})

    def test_valid_financial_data(self):
        result=validate('financials',{'result':{'data':[{'REPORT_DATE':'2024-12-31','NOTICE_DATE':'2025-04-20','ROEJQ':10}]}})
        self.assertEqual(result['publication_field'],'NOTICE_DATE')

    def test_http_denial_is_reported_not_retried(self):
        calls=[]
        def fetch(url,params,timeout):
            calls.append(url)
            raise urllib.error.HTTPError(url,403,'Forbidden',{},None)
        result=run_checks(fetch=fetch)
        self.assertEqual(len(calls),4)
        self.assertFalse(result['all_checks_passed'])
        self.assertTrue(all(r['http_status']==403 for r in result['results']))

    def test_success_does_not_promote_unverified_coverage(self):
        def fetch(url,params,timeout):
            if 'push2his' in url:return {'data':{'klines':['2025-12-19,10,11,12,9,100,1100']}}
            if 'datacenter-web' in url:return {'result':{'data':[{'TRADE_DATE':'2025-12-19','PE_TTM':10,'PB_MRQ':1}]}}
            return {'result':{'data':[{'REPORT_DATE':'2024-12-31','NOTICE_DATE':'2025-04-20','ROEJQ':10}]}}
        result=run_checks(fetch=fetch)
        self.assertTrue(result['all_checks_passed'])
        self.assertFalse(result['historical_ST_available'])
        self.assertFalse(result['historical_universe_audited'])
        self.assertFalse(result['financial_vintages_verified'])


if __name__=='__main__':unittest.main()
