"""短剧商品库 —— 批量入口：读表格，一个计划一个计划地搭。

用法：
    venv/bin/python3 -m src.drama.main [表格路径]                    # 搭建并发布
    venv/bin/python3 -m src.drama.main 短剧-excel.xlsx --no-publish  # 只搭草稿
    venv/bin/python3 -m src.drama.main 短剧-excel.xlsx --search xxx  # 测试用

**默认会真的发布并花钱**，和小游戏 main.py 的 PUBLISH = True 一致（使用者明确要求）。
只想搭草稿检查时加 --no-publish。

--search 只用于测试：正式跑素材是按剧名搜的，但有的剧还没上素材，
指定一个库里确实有素材的词就能把整条流程跑通验证。正式跑不要带这个参数。

表格列直接复用小游戏的 excel_loader（短剧表的列名和小游戏完全一致），
按 (Advertiser ID, Campaign Name) 分组，一组一个计划。
"""

import sys

from playwright.sync_api import sync_playwright

from src.account import check_advertiser_access, describe_access
from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.builder import build_drama_campaign
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.pages.campaign_page import ensure_chinese_ui
from src.drama.series_lookup import load_series_map
from src.excel_loader import group_by_campaign, load_rows

REPORT = []


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


def main():
    argv = sys.argv[1:]
    publish = "--no-publish" not in argv
    search_override = None
    if "--search" in argv:
        i = argv.index("--search")
        if i + 1 < len(argv):
            search_override = argv[i + 1].strip()
            del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]
    path = args[0] if args else "短剧-excel.xlsx"

    records = load_rows(path)
    groups = group_by_campaign(records)
    series_map, _ = load_series_map()

    L(f"表格: {path}")
    L(f"共 {len(records)} 行，分成 {len(groups)} 个计划")
    L("发布模式: " + ("【会真的发布并花钱】" if publish else "只搭草稿，不发布（--no-publish）"))
    if search_override:
        L(f"素材搜索词被命令行覆盖为 {search_override!r}（测试用，正式跑不要带 --search）")
    L("")

    results = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR),
            headless=False,
            locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()

        # 先确认登录 + 每个广告主的权限。表格里可能有多个广告主 ID，必须【全部】
        # 先验一遍：这条流程是边建边真发布的，跑到第 2 个广告主才发现没权限，
        # 前面花掉的钱收不回来。
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
                L(describe_access(access, aid, "短剧"))
                context.close()
                sys.exit(1)
            L(f"  广告主 {aid} ✓ 可以打开（界面语言 {access.get('lang')}）")
        L("")

        # 整套定位都依赖中文文案，界面变英文时每一步都会失败，所以在最开头拦住。
        # 实测界面会在中英文之间自己来回切，每次跑都要确认。
        ensure_chinese_ui(page, str(records[0]["Advertiser ID"]).strip())

        creative_usage = {}
        for (advertiser_id, campaign_name), rows in groups:
            L(f"=== {campaign_name}  ({len(rows)} 个广告组) ===")
            result = build_drama_campaign(
                page,
                str(advertiser_id),
                str(campaign_name),
                rows[0]["Budget"],
                rows,
                publish=publish,
                creative_usage=creative_usage,
                series_map=series_map,
                search_override=search_override,
            )
            results.append((campaign_name, result))
            if result["success"]:
                L("  ✓ 成功")
            else:
                L(f"  ✗ 失败: {result['error']}")
            for w in result["warnings"]:
                L(f"    ! {w}")
            L("")

        context.close()

    ok = sum(1 for _, r in results if r["success"])
    L(f"{'=' * 60}")
    L(f"完成: {ok}/{len(results)} 个计划成功")
    if not publish:
        L("（都是草稿，没有发布。确认无误后在后台手动点「全部发布」，"
          "或者重跑时去掉 --no-publish）")

    with open(str(LOGS_DIR / "drama_build.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(REPORT))
    print(f"\n报告已写入 {LOGS_DIR / 'drama_build.txt'}")


if __name__ == "__main__":
    main()
