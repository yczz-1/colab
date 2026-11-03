"""Run in Colab to distinguish TCP reachability from SDK login/query readiness."""
import json
import subprocess
import sys

_PROBE = r'''
import json, socket
from importlib.metadata import version
import baostock as bs
from baostock.common import contants as constants
host,port=constants.BAOSTOCK_SERVER_IP, constants.BAOSTOCK_SERVER_PORT
result={'endpoint':f'{host}:{port}','baostock_version':version('baostock')}
print('STAGE: TCP connection',flush=True)
try:
    with socket.create_connection((host,port),timeout=8):
        pass
except OSError as exc:
    result.update(stage='tcp',ok=False,error_type=type(exc).__name__,error=str(exc))
else:
    print('STAGE: BaoStock login',flush=True)
    socket.setdefaulttimeout(20)
    try:
        login=bs.login()
        if login.error_code!='0':
            result.update(stage='login',ok=False,error_code=login.error_code,error=login.error_msg)
        else:
            print('STAGE: historical query',flush=True)
            query=bs.query_history_k_data_plus('sh.000300','date,close',start_date='2025-12-15',end_date='2025-12-19',frequency='d',adjustflag='3')
            rows=0
            if query.error_code=='0':
                while query.next():
                    query.get_row_data()
                    rows+=1
            result.update(stage='query',ok=(query.error_code=='0' and rows>0),rows=rows,error_code=query.error_code,error=query.error_msg)
    except Exception as exc:
        result.update(stage='sdk',ok=False,error_type=type(exc).__name__,error=str(exc))
print('RESULT: '+json.dumps(result,ensure_ascii=False),flush=True)
'''


def diagnose_baostock(timeout=55):
    """Single bounded probe, not a guarantee that a long data download will succeed.

    This uses the provider's native TCP transport. Run only where that destination
    is permitted. The SDK runs in a child so hung receives cannot hang a notebook.
    No credentials or environment dumps are collected.
    """
    if timeout<1 or timeout>120:
        raise ValueError('timeout must be between 1 and 120 seconds')
    try:
        completed=subprocess.run([sys.executable,'-u','-c',_PROBE],capture_output=True,text=True,timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        output=exc.stdout or b''
        if isinstance(output,bytes):
            output=output.decode(errors='replace')
        stages=[line for line in output.splitlines() if line.startswith('STAGE:')]
        return {'ok':False,'stage':stages[-1] if stages else 'startup',
                'error':'Probe exceeded its overall deadline; child process was stopped.',
                'timeout_seconds':timeout}
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith('RESULT: '):
            return json.loads(line.removeprefix('RESULT: '))
    # Avoid echoing arbitrary library stderr; callers can inspect dependencies separately.
    return {'ok':False,'stage':'probe_startup','returncode':completed.returncode,
            'error':'Diagnostic did not return a result. Confirm requirements.txt is installed.'}


if __name__=='__main__':
    print(json.dumps(diagnose_baostock(),ensure_ascii=False,indent=2))
