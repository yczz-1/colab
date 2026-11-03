import socket
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
import baostock as bs
from baostock.common import context
from ashare.data import session
from ashare.connection import diagnose_baostock


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.previous=socket.getdefaulttimeout()
        self.original=getattr(context,'default_socket',None)
        context.default_socket=None
        self.connections=[]
        self.deadlines=[]

    def tearDown(self):
        context.default_socket=self.original
        socket.setdefaulttimeout(self.previous)

    def login(self,code):
        self.deadlines.append(socket.getdefaulttimeout())
        sock=MagicMock()
        self.connections.append(sock)
        context.default_socket=sock
        return SimpleNamespace(error_code=code,error_msg='test response')

    def test_network_retry_uses_fresh_socket_and_longer_deadline(self):
        responses=iter(['10002007','0'])
        with patch.object(bs,'login',side_effect=lambda:self.login(next(responses))) as login:
            with session() as provider:
                self.assertIs(provider,bs)
                self.assertEqual(socket.getdefaulttimeout(),30)
            self.assertEqual(login.call_count,2)
        self.assertEqual(self.deadlines,[20,60])
        self.connections[1].settimeout.assert_called_once_with(30)
        for connection in self.connections:
            connection.close.assert_called_once()
        self.assertEqual(socket.getdefaulttimeout(),self.previous)
        self.assertIsNone(context.default_socket)

    def test_auth_failure_is_not_retried(self):
        with patch.object(bs,'login',side_effect=lambda:self.login('10001005')) as login:
            with self.assertRaisesRegex(RuntimeError,'10001005'):
                with session():
                    self.fail('Must not enter session')
            self.assertEqual(login.call_count,1)
        self.assertTrue(self.connections[0].close.called)
        self.assertEqual(socket.getdefaulttimeout(),self.previous)

    def test_failed_retries_preserve_error_and_cleanup(self):
        with patch.object(bs,'login',side_effect=lambda:self.login('10002007')):
            with self.assertRaisesRegex(RuntimeError,'10002007'):
                with session():
                    self.fail('Must not enter session')
        self.assertEqual(len(self.connections),2)
        self.assertTrue(all(s.close.called for s in self.connections))
        self.assertEqual(socket.getdefaulttimeout(),self.previous)

    def test_query_error_not_retried_or_masked(self):
        with patch.object(bs,'login',side_effect=lambda:self.login('0')) as login:
            with self.assertRaisesRegex(ValueError,'original query error'):
                with session():
                    raise ValueError('original query error')
            self.assertEqual(login.call_count,1)
        self.assertTrue(self.connections[0].close.called)

    def test_diagnostic_parses_staged_result(self):
        result=subprocess.CompletedProcess([],0,stdout='STAGE: TCP connection\nRESULT: {"ok":false,"stage":"tcp"}\n',stderr='')
        with patch('ashare.connection.subprocess.run',return_value=result):
            self.assertEqual(diagnose_baostock(),{'ok':False,'stage':'tcp'})

    def test_diagnostic_timeout_reports_last_stage(self):
        error=subprocess.TimeoutExpired('probe',55,output=b'STAGE: TCP connection\nSTAGE: BaoStock login\n')
        with patch('ashare.connection.subprocess.run',side_effect=error):
            result=diagnose_baostock()
        self.assertFalse(result['ok'])
        self.assertEqual(result['stage'],'STAGE: BaoStock login')
        self.assertEqual(result['timeout_seconds'],55)


if __name__=='__main__':
    unittest.main()
