"""短剧商品库的路径常量。

只覆盖「浏览器身份目录」这一项，其余（地区表、身份表、日志目录等）沿用
src/config.py，没必要各存一份。

单独一个 profile 的原因：短剧的广告主属于另一个 Business Center，用小游戏那个
登录态访问会被跳到 /i18n/forbidden。两个 profile 并存，互不影响 —— 小游戏那边
已经在跑的登录态不会被短剧登录覆盖掉。
"""

from src.config import PROJECT_ROOT

DRAMA_BROWSER_PROFILE_DIR = PROJECT_ROOT / "browser_profile_drama"

DRAMA_BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
