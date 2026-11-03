import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import pandas as pd
from ashare.bundle import export_bundle,load_bundle
from ashare.demo import synthetic_data
from ashare.research import backtest
from ashare.strategy import Config
from download_local import main


class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p,f,b,m=synthetic_data()
        cls.p=p[p.date.between('2022-01-01','2023-03-31')].copy()
        cls.f=f.copy()
        cls.b=b.loc['2022-01-01':'2023-03-31'].copy()
        cls.m=m.copy()

    def write(self,path):
        return export_bundle(self.p,self.f,self.b,self.m,path)

    def test_offline_roundtrip_and_synthetic_label_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.write(Path(temp)/'market.zip')
            with patch.object(socket,'create_connection',side_effect=AssertionError('Must not access network')):
                p,f,b,m=load_bundle(path)
            self.assertEqual(len(p),len(self.p))
            self.assertEqual(len(f),len(self.f))
            pd.testing.assert_series_equal(b,self.b,check_names=False,check_freq=False)
            self.assertEqual(m['provider'],'SYNTHETIC')
            self.assertTrue(m['not_market_data'])
            self.assertTrue(m['sample_only'])
            self.assertTrue(m['loaded_from_bundle'])
            self.assertFalse(m['financial_vintages_verified'])

    def test_imported_data_backtest_matches_original(self):
        with tempfile.TemporaryDirectory() as temp:
            p,f,b,m=load_bundle(self.write(Path(temp)/'market.zip'))
            original=backtest(self.p,self.f,self.b,Config(),'2023-01-01','2023-03-31')[0]
            loaded=backtest(p,f,b,Config(),'2023-01-01','2023-03-31')[0]
            pd.testing.assert_frame_equal(original,loaded,rtol=1e-10,atol=1e-7)

    def test_checksum_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.write(Path(temp)/'market.zip')
            with zipfile.ZipFile(path) as z:
                content={n:z.read(n) for n in z.namelist()}
            content['prices.csv']+=b'\n'
            tampered=Path(temp)/'bad.zip'
            with zipfile.ZipFile(tampered,'w') as z:
                for name,data in content.items():z.writestr(name,data)
            with self.assertRaisesRegex(ValueError,'Checksum mismatch'):
                load_bundle(tampered)

    def test_unexpected_archive_member_and_size_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.write(Path(temp)/'market.zip')
            with self.assertRaisesRegex(ValueError,'size limit'):
                load_bundle(path,max_uncompressed_bytes=1)
            with zipfile.ZipFile(path,'a') as z:z.writestr('../untrusted.py','raise RuntimeError()')
            with self.assertRaisesRegex(ValueError,'Expected only'):
                load_bundle(path)

    def test_do_not_overwrite_existing_export(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.write(Path(temp)/'market.zip')
            original=path.read_bytes()
            with self.assertRaises(FileExistsError):self.write(path)
            self.assertEqual(original,path.read_bytes())

    def test_failed_download_does_not_create_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'market.zip'
            with patch('download_local.load_free',side_effect=RuntimeError('offline')):
                with self.assertRaisesRegex(RuntimeError,'offline'):
                    main(['--output',str(path)])
            self.assertFalse(path.exists())

    def test_downloader_refuses_synthetic_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'market.zip'
            with patch('download_local.load_free',return_value=(self.p,self.f,self.b,self.m)):
                with self.assertRaisesRegex(RuntimeError,'synthetic'):
                    main(['--output',str(path)])
            self.assertFalse(path.exists())

    def test_empty_benchmark_and_duplicate_prices_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'market.zip'
            with self.assertRaisesRegex(ValueError,'empty'):
                export_bundle(self.p,self.f,self.b.iloc[:0],self.m,path)
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                export_bundle(pd.concat([self.p,self.p.iloc[:1]]),self.f,self.b,self.m,path)


if __name__=='__main__':
    unittest.main()
