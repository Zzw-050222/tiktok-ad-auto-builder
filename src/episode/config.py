"""短剧端计划的路径常量。

浏览器登录态【和商品库共用】。

为什么共用而不是各开一份：实测两个模式对着的是同一个 Business Center
（都是 TT-We Shorts 那家），用商品库的登录态去开端计划测试表里那个广告主
（7654589605936693269）是通的。共用就少让使用者登一次账号。

要是以后端计划换到别的 BC，把下面这一行改成
    EPISODE_BROWSER_PROFILE_DIR = PROJECT_ROOT / "browser_profile_episode"
就变回独立登录态，别的都不用动。
"""

from src.drama.config import DRAMA_BROWSER_PROFILE_DIR

EPISODE_BROWSER_PROFILE_DIR = DRAMA_BROWSER_PROFILE_DIR
