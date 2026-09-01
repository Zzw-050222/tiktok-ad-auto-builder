"""短剧端计划 —— 批量入口：读表格，一个计划一个计划地搭。

用法：
    venv/bin/python3 -m src.episode.main 表格.xlsx --no-publish   # 只搭草稿
    venv/bin/python3 -m src.episode.main 表格.xlsx                # 搭建并发布

**不带 --no-publish 就会真的发布并花钱**，和另外两个模式一致。

表格：每一行相当于【一个广告组】，按 (Advertiser ID, Campaign Name) 分组，
一组一个计划。剧名从 Campaign Name 开头认（最长前缀匹配，见 builder）。
广告组层的身份读 Identity_drama，广告层的身份读 Identity_accoount ——
这是两个不同的东西。
"""

import sys

from playwright.sync_api import sync_playwright

from src.account import check_advertiser_access, describe_access
from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.pages.campaign_page import ensure_chinese_ui
from src.episode.builder import build_episode_campaign
from src.episode.config import EPISODE_BROWSER_PROFILE_DIR
from src.excel_loader import group_by_campaign, load_rows

REPORT = []


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


def main():
    argv = sys.argv[1:]
    publish = "--no-publish" not in argv
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print("用法: python3 -m src.episode.main 表格.xlsx [--no-publish]")
        sys.exit(2)
    path = args[0]

    records = load_rows(path, mode="episode")
    groups = group_by_campaign(records)

    # 剧目对照表是业务数据、不进安装包，没有也能跑（退回按 '-' 拆首段并警告）。
    series_map = None
    try:
        from src.drama.series_lookup import load_series_map

        series_map, _ = load_series_map()
        L(f"剧目对照表：{len(series_map)} 部")
    except Exception as e:
        L(f"剧目对照表读不到（{str(e).splitlines()[0][:70]}），"
          "剧名会按 '-' 拆计划名首段，注意核对")

    L(f"表格: {path}")
    L(f"共 {len(records)} 行（= {len(records)} 个广告组），分成 {len(groups)} 个计划")
    L("发布模式: " + ("【会真的发布并花钱】" if publish else "只搭草稿，不发布（--no-publish）"))
    L("")

    results = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(EPISODE_BROWSER_PROFILE_DIR),
            headless=False,
            locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()

        # 先把所有广告主的权限验一遍再动手 —— 这条流程默认是边建边发布的，
        # 跑到第 2 个广告主才发现没权限，前面花掉的钱收不回来。
        ids = []
        for (aid, _cn), _rows in groups:
            aid = str(aid).strip()
            if aid and aid not in ids:
                ids.append(aid)
        L(f"表格里共 {len(ids)} 个广告主 ID: {', '.join(ids)}")
        for aid in ids:
            access = check_advertiser_access(page, aid)
            if access.get("state") != "ok":
                L("")
                L(describe_access(access, aid, "短剧端计划"))
                context.close()
                sys.exit(1)
            L(f"  广告主 {aid} ✓ 可以打开（界面语言 {access.get('lang')}）")
        L("")

        # 整套定位都依赖中文文案，界面变英文时每一步都会失败，所以在最开头拦住。
        ensure_chinese_ui(page, str(records[0]["Advertiser ID"]).strip())

        creative_usage = {}
        for (advertiser_id, campaign_name), rows in groups:
            L(f"=== {campaign_name}  ({len(rows)} 个广告组) ===")
            result = build_episode_campaign(
                page,
                str(advertiser_id),
                str(campaign_name),
                rows[0]["Budget"],
                rows,
                publish=publish,
                creative_usage=creative_usage,
                series_name_map=series_map,
            )
            results.append((campaign_name, result))
            L("  ✓ 成功" if result["success"] else f"  ✗ 失败: {result['error']}")
            for w in result["warnings"]:
                L(f"    ! {w}")
            L("")

        context.close()

    ok = sum(1 for _, r in results if r["success"])
    L("=" * 60)
    L(f"完成: {ok}/{len(results)} 个计划成功")
    if not publish:
        L("（都是草稿，没有发布。确认无误后在后台手动点「全部发布」）")

    with open(str(LOGS_DIR / "episode_build.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(REPORT))
    print(f"\n报告已写入 {LOGS_DIR / 'episode_build.txt'}")


if __name__ == "__main__":
    main()
