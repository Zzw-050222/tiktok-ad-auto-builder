"""短剧端计划的路径常量。

和 drama 一样，只覆盖「浏览器身份目录」这一项，其余（地区表、身份表、日志目录）
沿用 src/config.py。

单独一个 profile 的理由和 drama 相同：三个模式可能对着不同 Business Center 的
广告主，共用一个登录态会互相顶掉（换账号会把另一边的登录态覆盖）。
如果后面确认短剧端计划和商品库用的是同一个 BC、想省一次登录，
把下面这一行改成指向 DRAMA_BROWSER_PROFILE_DIR 就行，别的都不用动。
"""

from src.config import PROJECT_ROOT

EPISODE_BROWSER_PROFILE_DIR = PROJECT_ROOT / "browser_profile_episode"

EPISODE_BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
