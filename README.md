# TikTok 广告自动搭建工具 / TikTok Ads Auto Builder

一个自己写着玩、顺便解决自己工作问题的小工具。代码大部分是跟 AI（Claude）一起写出来的，架构比较朴素，没有什么工程上的花活，欢迎随便看、随便改、随便提意见。

---

## 中文说明

### 这是什么

我是做 TikTok 投放的，日常需要在 TikTok Ads Manager 里手动搭建大量广告计划（尤其是"TikTok 即时增长" / Mini Game 这类需要自动挑创意的计划）。这个工具用 Python + Playwright 模拟真人操作浏览器，按 Excel 表格里的数据，一行一行把计划 / 广告组 / 广告搭出来，省得自己天天手点。

### 为什么不直接用官方 API

TikTok Marketing API 目前不支持"自动挑创意"这个功能（Mini Game / Native Growth 场景下必须走网页后台才能用这个功能），所以没法完全走 API，只能做浏览器自动化。

### 环境要求

- Python 3.10 及以上
- Windows 10/11 或 macOS
- 一个已经能正常登录 TikTok Ads Manager 的账号（脚本会用真实浏览器登录，不是破解/绕过登录）

### 安装步骤

先把仓库下载到本地，然后：

**Windows（在项目文件夹里打开命令行）**

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\playwright install chromium
```

**macOS（在项目文件夹里打开终端）**

```
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/playwright install chromium
```

### 第一次使用：先登录一次

工具用的是"持久化浏览器"，登录状态会保存在本地 `browser_profile/` 文件夹里（这个文件夹已经在 `.gitignore` 里，不会被提交，也别手动分享给别人，里面等于是你的登录凭证）。

先跑一下登录脚本，手动登录一次（扫码/输密码，跟平时登录一样）：

```
venv\Scripts\python -m src.login_setup      # Windows
venv/bin/python3 -m src.login_setup          # macOS
```

登录一次之后，后面跑网页版/命令行版都不用再登了。

### 怎么用

**方式一：网页版（推荐，比较直观）**

- Windows：双击 `run_web.bat`
- macOS：在终端里执行 `bash run_web.sh`（如果提示权限问题，先执行一次 `chmod +x run_web.sh`）

打开的网页里：上传你的 Excel 表格 → 点"开始搭建"→ 看进度和报错信息。

**方式二：命令行**

```
venv\Scripts\python main.py 你的表格.xlsx      # Windows
venv/bin/python3 main.py 你的表格.xlsx          # macOS
```

⚠️ **注意：默认会真实发布广告，会真实花钱投放**。网页版有个"自动发布"的勾选框，不勾就只搭建到草稿、不会真的发布，建议第一次用先不勾，确认搭出来的东西没问题再打开自动发布。命令行版本目前默认是自动发布（`main.py` 里的 `PUBLISH = True`），如果不想直接发布，改成 `False` 再跑。

### Excel 表格需要哪些列

必须要有的（缺一个会报错）：

`Campaign Name`、`Budget`、`Advertiser ID`、`Ad Group Name`、`TT Mini ID`、`roas_bid`、`TT Mini URL`、`Region`、`Mini Game Name`、`ads_text`、`Identity_ID`

可以不填的（留空或整列不加都行）：

`Business Center Account ID`（没用到，纯备注）、`optimization_event`（没用到，TikTok 选完小游戏会自动定）、`Ad Group Name Number`（要在这一行基础上额外复制几份广告组/广告，不填默认 0）

`examples/sample_campaign_template.xlsx` 是一个示例表格，可以照着这个格式改成自己的数据。

同一个 `Campaign Name` + `Advertiser ID` 的多行会被当成同一个计划下的多个广告组，自动依次搭建。

### 两个对照表

- `REGION.xlsx`：地区 ID 对照表（TikTok 用数字 ID 表示国家/地区），仓库里自带的这份是通用数据，不涉及任何账号信息，直接用就行，也可以自己加更多国家（跑 `scripts/add_regions.py` 改一改就行）。
- `Identity_id.xlsx`：身份（发布者）对照表，把 `Identity_ID` 映射到 TikTok 上显示的账号名。**这个需要你自己按自己账号的实际身份填**，仓库里没有提供真实数据（因为这是账号隐私信息），可以参考 `examples/sample_identity_id.xlsx` 的格式自己建一份。

Region 这一列还支持两个特殊写法：
- 填一串特定的 8 个国家 ID（具体见 `src/builder.py` 里的 `ALL_REGIONS_SENTINEL_IDS`）→ 会自动把这个小游戏当前能投的所有地区都选上
- 填 `ex` 开头 + 国家 ID，比如 `ex6252001` → 选上除了这个 ID（美国）以外的所有能投地区，多个用逗号隔开，比如 `ex6252001,1861060`

### 已知的坑 / 使用注意

- TikTok 的广告后台会时不时卡顿，脚本里已经加了不少"最多等一分钟"的重试逻辑，遇到卡顿正常，耐心等就行。
- 不同 TikTok 账号的后台界面有一些细节差异（比如有的账号预算填在计划层级，有的填在广告组层级；有的小游戏选择框能搜索，有的不能只能滚动列表），代码里已经适配了几种我自己遇到的情况，但不保证覆盖所有账号类型，遇到没见过的情况大概率会直接报错退出（不会瞎点），把报错信息发出来就能继续排查。
- 这是我自己业务上顺手写的工具，不是专业软件工程做出来的产品，代码里还留着不少调试用的痕迹，肯定还有没发现的 bug，用之前建议先在小预算/测试计划上跑一遍确认没问题。

### 免责声明

这个工具是模拟浏览器操作 TikTok Ads Manager 网页版，不是通过官方开放的 API，理论上可能不完全符合 TikTok 的服务条款，使用风险自己承担。这个项目跟 TikTok / ByteDance 没有任何官方关联。

### License

MIT，随便用、随便改，出了问题不负责（见 `LICENSE` 文件）。

---

## English

### What is this

I run TikTok ad campaigns for a living, and building campaigns manually in TikTok Ads Manager (especially "TikTok Native Growth" / Mini Game campaigns) got repetitive. This tool uses Python + Playwright to drive a real browser and build campaigns / ad groups / ads row-by-row from an Excel file, instead of clicking through everything by hand.

### Why not just use the official API

TikTok's Marketing API doesn't currently support the "auto-select creative" feature that Native Growth / Mini Game campaigns rely on - that only works through the web UI, so browser automation is the only option.

### Requirements

- Python 3.10+
- Windows 10/11 or macOS
- A TikTok Ads Manager account you can already log into normally (this drives a real browser login, it does not bypass or crack authentication)

### Setup

Clone/download this repo, then:

**Windows (open a terminal in the project folder)**

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\playwright install chromium
```

**macOS (open a terminal in the project folder)**

```
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/playwright install chromium
```

### First run: log in once

This uses a persistent browser profile - your login session is stored locally in `browser_profile/` (already in `.gitignore`, never commit or share this folder, it's effectively your login credentials).

Run the login helper first and log in normally (QR code / password, same as usual):

```
venv\Scripts\python -m src.login_setup      # Windows
venv/bin/python3 -m src.login_setup          # macOS
```

Once you've logged in once, neither the web UI nor the command-line version will ask again.

### How to use it

**Option 1: Web UI (recommended)**

- Windows: double-click `run_web.bat`
- macOS: run `bash run_web.sh` in a terminal (run `chmod +x run_web.sh` once first if you get a permission error)

In the page that opens: upload your Excel file → click "开始搭建" (Start Building) → watch progress and error messages.

**Option 2: Command line**

```
venv\Scripts\python main.py your_file.xlsx      # Windows
venv/bin/python3 main.py your_file.xlsx          # macOS
```

⚠️ **Warning: this publishes real ads and spends real money by default.** The web UI has an "自动发布" (auto-publish) checkbox - leave it unchecked the first time to only build drafts without publishing, and verify the result before turning it on. The command-line version currently defaults to auto-publish (`PUBLISH = True` in `main.py`) - set it to `False` if you don't want that.

### Required Excel columns

Required (missing any of these raises an error):

`Campaign Name`, `Budget`, `Advertiser ID`, `Ad Group Name`, `TT Mini ID`, `roas_bid`, `TT Mini URL`, `Region`, `Mini Game Name`, `ads_text`, `Identity_ID`

Optional (fine to leave blank or omit entirely):

`Business Center Account ID` (unused, label only), `optimization_event` (unused - TikTok auto-picks this after the mini game is selected), `Ad Group Name Number` (how many extra identical copies of this row's ad group to duplicate; defaults to 0)

See `examples/sample_campaign_template.xlsx` for the expected format.

Rows sharing the same `Campaign Name` + `Advertiser ID` are treated as multiple ad groups under the same campaign, and built in sequence automatically.

### Two lookup tables

- `REGION.xlsx`: maps TikTok's numeric region IDs to country names. The one included in this repo is generic public data (no account info), so you can use it as-is, or add more countries with `scripts/add_regions.py`.
- `Identity_id.xlsx`: maps `Identity_ID` to the display name TikTok shows for that identity/publisher. **You need to build this yourself** with your own accounts' real identities - this repo does not ship real identity data (that's private account info). See `examples/sample_identity_id.xlsx` for the format.

The `Region` column also supports two special values:
- A specific list of 8 region IDs (see `ALL_REGIONS_SENTINEL_IDS` in `src/builder.py`) → selects every region currently available for that mini game
- `ex` followed by a region ID, e.g. `ex6252001` → selects every available region *except* that one (US); comma-separate for more than one, e.g. `ex6252001,1861060`

### Known gotchas

- TikTok's ad platform can lag noticeably; the script already retries with up to ~1 minute of patience in most places. That's expected, not a bug.
- Different TikTok accounts have slightly different UI flows (e.g. some have budget at the campaign level, some at the ad-group level; some mini-game pickers support search, some are scroll-only lists). A few variants I've personally run into are handled, but not every possible account type is guaranteed to work - if it hits something unexpected it should fail loudly with an error rather than silently clicking the wrong thing. Please open an issue with the error message if you hit one.
- This was written to solve my own workflow problem, not as professional software - there's leftover debug residue in a few places and probably bugs I haven't found. Test on a small budget / test campaign before trusting it with anything real.

### Disclaimer

This tool automates the TikTok Ads Manager web UI through a real browser rather than TikTok's official API, which may not fully align with TikTok's Terms of Service. Use at your own risk. This project has no official affiliation with TikTok or ByteDance.

### License

MIT - use it, modify it, no warranty (see `LICENSE`).
