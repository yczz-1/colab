# 交付验证

- Python 3.12.14，BaoStock 0.9.4，NumPy 2.3.5，pandas 2.2.3，Matplotlib 3.10.8。
- 在项目独立venv中按requirements.txt安装直接依赖，版本固定。
- `python -m unittest discover -s tests -v`：15项测试全部通过。
- Notebook的模拟数据代码单元在本地Python环境按顺序执行完成，包括4组基线、图表、因子诊断、模拟订单和ZIP导出；依赖安装与测试单独执行。未在Google Colab服务上执行。
- 研究回测使用模拟数据，不提供真实A股业绩结论。没有尝试用模拟收益选择最优策略。
- 真实BaoStock行情/财报下载未验证：当前云环境的TCP网络授权为空，BaoStock使用public-api.baostock.com:10030。下载器需用户在Colab上验证返回数据及完整性。
- 15%回撤只是警戒线。真实整数手/分红送转账户回测、财务历史版本审计、退市股票覆盖审计、行业约束和前向模拟尚未完成，当前版本不具备实盘验收结论。
