import unittest
import tempfile
from pathlib import Path
import pandas as pd
from ashare.demo import synthetic_data
from ashare.strategy import Config
from ashare.diagnostics import factor_diagnostics
from ashare.research import backtest, save_run
from ashare.data import cached


class DiagnosticTests(unittest.TestCase):
    def test_factor_observations_and_forward_dates(self):
        p,f,b,_=synthetic_data()
        detail,summary=factor_diagnostics(p,f,b,Config(),'2023-01-01','2023-04-30')
        self.assertEqual(len(summary),4)
        self.assertTrue((detail.signal_date<detail.entry_date).all())
        self.assertTrue((detail.entry_date<detail.exit_date).all())
        self.assertTrue((detail.n>=10).all())
        self.assertTrue(detail.rank_ic.between(-1,1).all())

    def test_missing_held_quote_fails(self):
        p,f,b,_=synthetic_data()
        _,trades,_,_=backtest(p,f,b,Config(),'2023-01-01','2023-01-20')
        first=trades[trades.side.eq('BUY')].iloc[0]
        missing=pd.Timestamp(first.date)+pd.offsets.BDay(1)
        p=p[~(p.code.eq(first.code)&p.date.eq(missing))]
        with self.assertRaisesRegex(ValueError,'Missing held-stock'):
            backtest(p,f,b,Config(),'2023-01-01','2023-01-20')

    def test_experiment_cannot_overwrite(self):
        p,f,b,m=synthetic_data()
        result=backtest(p,f,b,Config(),'2023-01-01','2023-01-20')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'run'
            save_run(result,path,m)
            self.assertTrue((path/'report.json').exists())
            with self.assertRaises(FileExistsError):
                save_run(result,path,m)

    def test_cache_reuses_successful_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cache.csv'
            expected=pd.DataFrame({'code':['sh.600000']})
            cached(path,lambda:expected)
            def should_not_fetch():
                raise AssertionError('Unexpected repeat API request')
            pd.testing.assert_frame_equal(cached(path,should_not_fetch),expected)


if __name__=='__main__':
    unittest.main()
