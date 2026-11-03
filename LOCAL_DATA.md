# Mac下载 → Colab离线回测

Colab上的两个BaoStock客户端分别出现登录接收超时和TCP超时；这不能证明本机一定可连。本流程需要本机网络允许连接BaoStock服务；不使用代理绕过限制，不替换数据为模拟数据。

## Mac操作

1. 下载最新版 `ashare_colab.zip`，解压为 `ashare_weekly`。
2. 打开Mac“终端”，输入 `cd `（后面有空格），把解压后的 **ashare_weekly文件夹** 拖入终端，然后按回车。这可避免下载目录、中文或空格路径带来的问题。
3. 运行：

```bash
bash mac_download.sh
```

脚本从本机可用解释器选择Python 3.11–3.13（建议3.12），在项目目录建立 `.venv-local`，按固定requirements安装依赖，检查原生BaoStock 0.9.4连接，再下载2017–2025年服务商返回的前30只主板股票及年度财报、沪深300基准。

若没有合适的Python，脚本会停止并提示从 https://www.python.org/downloads/macos/ 安装Python 3.12。无需Homebrew、sudo或更改系统Python。安装后重新打开终端，再进入项目目录运行脚本。若venv已存在但原解释器已被移除/更换，应在保留其他文件的前提下重新建立该本地环境。

本机连接诊断失败时停止。请保留其阶段和错误码，不反复更换版本或声称本机已成功。

连接成功并下载完成后，会输出类似：

```text
REAL DATA BUNDLE: /.../ashare_weekly/market_sample_YYYYMMDD_HHMMSS.zip
Rows: prices=..., fundamentals=..., benchmark=...
```

只有这条成功提示及完整数据包才代表下载完成。已有成功缓存会复用；错误请求不写入成功缓存。先用30只验证流程；股票按代码排序，样本不能代表全市场。

## 上传Colab

使用最新版Notebook（旧版没有bundle分支）。在数据单元设置：

```python
MODE = 'bundle'
BUNDLE_PATH = None
```

运行数据单元时选择Mac生成的 **market_sample_*.zip**。不要选 `ashare_colab.zip` 或 `demo_*.zip`。

成功导入后，元数据应包含真实来源 `provider='BaoStock 0.9.4'`、`loaded_from_bundle=True`、`sample_only=True`。随后运行回测和诊断单元。若数据源是模拟数据，导入器会保留模拟标记，不把它改成真实数据。数据包不会让历史财报修订或退市覆盖变得已审计。

大型数据建议放在自己的Google Drive，挂载后把BUNDLE_PATH设为该ZIP的路径；无需在Colab重新下载行情。

## 扩展全市场

样本下载、导入和回测都通过后，再在Mac运行：

```bash
bash mac_download.sh --all-symbols
```

生成 `market_full_*.zip`。这是服务商证券主表能发现的全体主板股票，历史完整性仍需审计。下载时间、内存与磁盘开销会明显增加；CSV解压总量默认上限4GiB，导入仍需足够内存，不能假定免费Colab一定容纳全量。

也可以直接使用本机已创建的环境：

```bash
.venv-local/bin/python download_local.py --diagnose-only
.venv-local/bin/python download_local.py --max-symbols 30
```

## 数据格式与边界

数据ZIP只含 `prices.csv`、`fundamentals.csv`、`benchmark.csv`、`manifest.json`。不执行ZIP中的代码，不使用pickle，不提取任意路径。导入检查SHA-256、必需字段、日期、键重复、基准价格和记录数量；哈希用于发现传输损坏，不能证明行情或财报本身正确，也不能认证未知数据供应商。

不能从券商随意导出一份日线就当成完整多因子数据包：估值、复权价格、上市日期、历史ST、公告日期和年度ROE缺一仍可能影响研究。旧版Colab报错和30只抽样结果都不构成真实策略验收。
