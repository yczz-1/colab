import unittest
from dataclasses import replace
import numpy as np
import pandas as pd
from ashare.demo import synthetic_data
from ashare.strategy import Config,prepare_prices,snapshot,targets,fees,mainboard
from ashare.orders import plan_orders
from ashare.research import backtest


class StrategyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p,cls.f,cls.b,_=synthetic_data()
        cls.prepared=prepare_prices(cls.p)

    def test_mainboard(self):
        self.assertTrue(mainboard('sz.002001'))
        self.assertFalse(mainboard('sz.300001'))
        self.assertFalse(mainboard('sh.688001'))
        self.assertFalse(mainboard('bj.920001'))

    def test_disclosure_delay(self):
        f=self.f.copy()
        row={'code':'sh.600000','pubDate':'2023-05-05','statDate':'2022-12-31','roeAvg':999}
        f=pd.concat([f,pd.DataFrame([row])],ignore_index=True)
        a=snapshot(self.prepared,f,'2023-05-05',Config())
        b=snapshot(self.prepared,f,'2023-05-08',Config())
        self.assertLess(a.loc['sh.600000','roe'],1)
        self.assertEqual(b.loc['sh.600000','roe'],999)

    def test_no_future_price_leakage(self):
        p=self.p.copy()
        p.loc[p.date>pd.Timestamp('2023-05-05'),'adj_close'] *=100
        a=targets(self.prepared,self.f,self.b,'2023-05-05',Config())
        b=targets(prepare_prices(p),self.f,self.b,'2023-05-05',Config())
        pd.testing.assert_series_equal(a.target_weight,b.target_weight)
        pd.testing.assert_series_equal(a.score,b.score)

    def test_missing_quality_fails(self):
        with self.assertRaises(ValueError):
            snapshot(self.prepared,None,'2023-05-05',Config())

    def test_historical_fees(self):
        cfg=Config()
        self.assertAlmostEqual(fees(10000,'SELL','2023-08-25',cfg)-fees(10000,'SELL','2023-08-28',cfg),5)
        self.assertGreater(fees(1000,'BUY','2024-01-01',cfg),5)
        self.assertEqual(fees(0,'BUY','2024-01-01',cfg),0)

    def test_st_ipo_and_liquidity_excluded(self):
        p=self.prepared.copy()
        p.loc[p.code.eq('sh.600000'),'isST']=1
        p.loc[p.code.eq('sh.600001'),'ipoDate']=pd.Timestamp('2023-05-01')
        p.loc[p.code.eq('sh.600002'),'amount20']=100
        x=snapshot(p,self.f,'2023-05-05',Config())
        self.assertTrue(set(['sh.600000','sh.600001','sh.600002']).isdisjoint(x.index))

    def quotes(self):
        return pd.DataFrame({'price':[10.,20.],'upper':[11.,22.],'lower':[9.,18.],'tradable':[True,True]},index=['sh.600000','sh.600001'])

    def test_cash_lots_t1(self):
        selection=pd.DataFrame({'target_weight':[.2]},index=['sh.600001'])
        h=pd.DataFrame({'code':['sh.600000'],'shares':[1000],'sellable':[0]})
        orders,status=plan_orders(selection,h,self.quotes(),100,'2024-01-01',Config())
        self.assertEqual(orders.shares.sum(),0)
        self.assertGreaterEqual(status['cash_after_buys_without_sales'],0)
        # Pending sell proceeds must not finance buys.
        h.sellable=1000
        orders,status=plan_orders(selection,h,self.quotes(),100,'2024-01-01',Config())
        self.assertEqual(orders[orders.side.eq('BUY')].shares.sum(),0)
        self.assertEqual(orders[orders.side.eq('SELL')].shares.sum(),1000)

    def test_lots_and_upper_limit(self):
        selection=pd.DataFrame({'target_weight':[.2]},index=['sh.600000'])
        h=pd.DataFrame(columns=['code','shares','sellable'])
        orders,status=plan_orders(selection,h,self.quotes(),20000,'2024-01-01',Config())
        self.assertEqual(int(orders.shares.iloc[0])%100,0)
        self.assertEqual(int(orders.shares.iloc[0]),300)
        q=self.quotes();q.loc['sh.600000','price']=11.
        orders,_=plan_orders(selection,h,q,20000,'2024-01-01',Config())
        self.assertEqual(orders.shares.sum(),0)

    def test_weekly_research_accounting(self):
        result=backtest(self.p,self.f,self.b,Config(),'2023-01-01','2023-06-30')
        curve,trades,_,report=result
        self.assertGreater(len(trades),10)
        self.assertTrue((trades.signal_date<trades.date).all())
        self.assertTrue((trades.date.dt.to_period('W-FRI')!=trades.signal_date.dt.to_period('W-FRI')).all())
        self.assertTrue((curve.cash>=0).all())
        self.assertTrue((curve.positions<=8).all())
        self.assertTrue(np.isfinite(curve.nav).all())
        self.assertGreater(report['estimated_cost'],0)
        self.assertIn('RESEARCH_ONLY',report['mode'])

    def test_cost_drag(self):
        cfg=Config()
        a=backtest(self.p,self.f,self.b,cfg,'2023-01-01','2023-02-28')[0]
        b=backtest(self.p,self.f,self.b,replace(cfg,commission_rate=.05,min_commission=50),'2023-01-01','2023-02-28')[0]
        self.assertLess(b.nav.iloc[-1],a.nav.iloc[-1])

    def test_duplicate_prices_rejected(self):
        with self.assertRaises(ValueError):
            prepare_prices(pd.concat([self.p,self.p.iloc[:1]]))


if __name__=='__main__':
    unittest.main()
