"""自动共享素材 —— 路径常量。

这个功能和搭建完全不搭界：不建计划、不碰广告，只在【创意素材库】里操作。
所以单独一个模块。

登录态直接复用现有的两个 profile —— 小游戏和短剧各一个 BC，
共享素材也是在这两个 BC 下做，没必要再登第三次。
"""

from src.config import BROWSER_PROFILE_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR

# 素材库页面。aadvid 就是【源账号】（素材在谁那儿）的广告主 ID。
CREATIVE_LIBRARY_URL = "https://ads.tiktok.com/i18n/creative-library/own/video?aadvid={}"

PROFILES = {
    "minigame": BROWSER_PROFILE_DIR,
    "drama": DRAMA_BROWSER_PROFILE_DIR,
}
