import sys

from playwright.sync_api import sync_playwright

from src.builder import build_campaign_group
from src.config import ACCEPT_LANGUAGE, BROWSER_PROFILE_DIR, LOCALE, LOGS_DIR
from src.excel_loader import group_by_campaign, load_rows

PUBLISH = True


def main(xlsx_path, unique_creatives=False, publish=None):
    # publish 显式传 False 就只搭草稿。加这个开关是为了能【安全地验证流程】——
    # 默认 PUBLISH=True 会真的花钱，调试时不能用。
    if publish is None:
        publish = PUBLISH
    records = load_rows(xlsx_path)
    groups = group_by_campaign(records)
    print(f"共读取到 {len(records)} 行，分成 {len(groups)} 个计划。")
    print("发布模式: " + ("【会真的发布并花钱】" if publish else "只搭草稿（--no-publish）"))
    if unique_creatives:
        print("已开启「每个广告组用不同素材」（--unique-creatives）："
              "带 Ad Group Name Number 的行会先复制出空广告组，再沿「继续」逐个挑素材。")

    results = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=False,
            locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        creative_usage = {}

        for (advertiser_id, campaign_name), rows in groups:
            print(f"\n=== 搭建计划: {campaign_name} ({len(rows)} 个广告组) ===")
            budget = rows[0]["Budget"]
            result = build_campaign_group(
                page,
                str(advertiser_id),
                str(campaign_name),
                budget,
                rows,
                publish=publish,
                creative_usage=creative_usage,
                unique_creatives=unique_creatives,
            )
            result["campaign_name"] = campaign_name
            results.append(result)

            if result["success"]:
                print(f"完成。警告: {len(result['warnings'])} 条")
                for w in result["warnings"]:
                    print(f"  - {w}")
            else:
                print(f"失败: {result['error']}")

        context.close()

    print("\n=== 汇总 ===")
    ok = sum(1 for r in results if r["success"])
    print(f"成功: {ok}/{len(results)}")
    for r in results:
        if not r["success"]:
            print(f"  失败计划: {r['campaign_name']} - {r['error']}")

    return results


if __name__ == "__main__":
    argv = sys.argv[1:]
    unique = "--unique-creatives" in argv
    do_publish = False if "--no-publish" in argv else None
    args = [a for a in argv if not a.startswith("--")]
    xlsx = args[0] if args else "examples/sample_campaign_template.xlsx"
    main(xlsx, unique_creatives=unique, publish=do_publish)
