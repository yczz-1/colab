from datetime import datetime
from ashare.demo import synthetic_data
from ashare.strategy import Config
from ashare.research import backtest,save_run

if __name__=='__main__':
    p,f,b,m=synthetic_data()
    result=backtest(p,f,b,Config(), '2023-01-01','2024-12-31')
    path='outputs/SYNTHETIC_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    save_run(result,path,m)
    print('SYNTHETIC SOFTWARE CHECK ONLY:',path)
    print(result[3])
