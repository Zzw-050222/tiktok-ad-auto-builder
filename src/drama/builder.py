"""短剧商品库 —— 把一个计划（含它下面的若干广告组/广告）整条搭出来。

结构照着 src/builder.py 的 build_campaign_group 写，返回同样的
{"success", "error", "warnings"}，这样两条线的调用方式一致。

和小游戏的差别只有三处，其余步骤全部复用小游戏的函数（地域、ROAS、选素材、
文案、URL）——那些函数里装着实测踩出来的处理，复制一份等于以后每个 bug 修两遍：
  1. 计划层多一个「设置商品库推广系列」开关，默认关闭，必须打开
  2. 广告组层多了「关联商品库」和「特定剧集」，且短剧要按【短剧ID】搜
  3. 广告组层的 TikTok Mini 和 ROAS 结构与小游戏不同（见 drama/pages/adgroup_page），
     选完 Mini 还要把「选择价值类型」改成「广告收入价值」
  4. 一个计划下有多个广告组时【不用复制功能】：建一个就发布一个，发布完页面会
     回到计划列表，再从列表点进原计划、点右上「创建」建下一个。使用者指定的顺序。

短剧从计划名用最长前缀匹配推出（见 src/drama/series_lookup.py），不按 '-' 切：
商品库里有 4 个剧名自身带连字符，切了会断。
"""

from src.drama.pages.ad_page import (
    fill_drama_ad_copy,
    fill_drama_minis_url,
    select_drama_creatives,
)
from src.drama.pages.adgroup_page import (
    add_specific_episode,
    fill_ad_group_name,
    select_ad_revenue_value_type,
    select_product_catalog,
    set_regions_drama,
    select_target_roas_drama,
    select_tiktok_mini,
)
from src.drama.pages.campaign_page import (
    enable_catalog_campaign,
    open_campaign_and_create_adgroup,
    publish_all,
)
from src.drama.series_lookup import load_series_map, resolve_series_from_campaign_name
from src.pages.ad_page import wait_ad_page_ready
from src.pages.campaign_page import (
    continue_step,
    fill_campaign_details,
    select_native_growth_objective,
    start_new_campaign,
)
from src.pages.adgroup_page import wait_adgroup_page_ready
from src.pages.common import exit_draft
from src.region_lookup import resolve_regions


def _creative_count(rec):
    """这一行要手动挑几个素材。空或 <1 当作 1。

    注意和小游戏不同：小游戏是「Creative Number > 2 才切成手动挑，否则保留
    TikTok 的自动选择」。短剧这边使用者明确要求【一律手动搜索挑选】，
    所以这里不做那个阈值判断。
    """
    try:
        n = int(rec.get("Creative Number") or 1)
    except (TypeError, ValueError):
        n = 1
    return max(n, 1)


def _extra_copies(rec):
    """这一行要【再建】几个一样的广告组（表格 Ad Group Name Number）。

    语义和小游戏不同：小游戏是用 TikTok 的「复制」功能复制几份，短剧这边使用者
    要求不用复制，每一个都真建一遍（建完发布、回列表、进原计划再建下一个）。
    """
    val = rec.get("Ad Group Name Number")
    try:
        return int(val) if val not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def build_drama_campaign(
    page,
    advertiser_id,
    campaign_name,
    budget,
    rows,
    publish=False,
    creative_usage=None,
    series_map=None,
    search_override=None,
):
    """搭一个短剧计划。rows 是同一个 Campaign Name 下的所有行。

    creative_usage: 整次运行共用的一个 dict，键是 (广告主, 剧名)，值是已经用过的
        素材身份集合。同一个 dict 一路传下去，才能做到跨计划不重复用素材、
        库用完了才开始复用。

    publish: True 会真的发布并花钱。批量入口 src/drama/main.py 默认打开
        （使用者明确要求），要只搭草稿就在命令行加 --no-publish。

    search_override: 只用于测试——正式跑素材按剧名搜，但有的剧还没上素材，
        指定一个库里确实有素材的词能把整条流程跑通验证。正式跑传 None。

    返回 {"success": bool, "error": str|None, "warnings": [str]}。
    """
    if creative_usage is None:
        creative_usage = {}
    if series_map is None:
        series_map, _ = load_series_map()

    warnings = []
    try:
        series_name, series_id = resolve_series_from_campaign_name(
            campaign_name, series_map
        )
        if not series_id:
            raise ValueError(
                f"计划名 {campaign_name!r} 在「商品库-剧目」表里匹配不到剧目。"
                "搭建要用短剧ID去搜，匹配不到就没法继续。"
            )

        # 把这个计划要建的广告组摊平成一个列表：每一行贡献 1 个，
        # 表格 Ad Group Name Number 再额外贡献 N 个（内容和这一行一样）。
        # 注意语义变了：以前这一列是「复制几份」，现在是「再【建】几个」——
        # 使用者要求不用复制功能，每个广告组都真建一遍。
        units = []
        for rec in rows:
            units.append(rec)
            units.extend([rec] * _extra_copies(rec))

        if not publish and len(units) > 1:
            warnings.append(
                f"这个计划要建 {len(units)} 个广告组，但没开发布。新流程是"
                "「建一个→发布→回列表→进原计划再建一个」，不发布就回不到列表，"
                "所以只建了第 1 个。要建全部请打开发布。"
            )
            units = units[:1]

        budget_at_campaign = None
        for i, rec in enumerate(units):
            tag = str(rec.get("Ad Group Name") or f"第{i + 1}个")

            if i == 0:
                # 第 1 个：走新建计划的流程
                start_new_campaign(page, advertiser_id)
                select_native_growth_objective(page)
                # 短剧独有：这个开关默认关闭，不打开后面根本没有「关联商品库」
                enable_catalog_campaign(page)
                budget_at_campaign = fill_campaign_details(page, campaign_name, budget)
                if not budget_at_campaign:
                    warnings.append(
                        "这个账号在计划层级没有预算区域，预算需要改到广告组层级去填"
                        "（短剧这条线还没验证过这种账号类型）"
                    )
                continue_step(page)
                # 必须等广告组页真的就绪再往下。之前这里【没有等】，
                # 全靠页面加载得快侥幸过关——慢一次就会在「商品库还没加载出来」
                # 的状态下去点特定剧集的「添加」，报「没找到添加按钮」。
                # 小游戏 builder 和探针都有这一步，只有短剧 builder 漏了。
                wait_adgroup_page_ready(page)
                page.wait_for_timeout(1500)
            else:
                # 第 2 个起：回到刚发布的那个计划里再建一个广告组。
                # 不用复制功能——使用者要求每个都真建一遍。
                open_campaign_and_create_adgroup(page, advertiser_id, campaign_name)

            fill_ad_group_name(page, str(rec["Ad Group Name"]))
            select_product_catalog(page, catalog_id=None)
            add_specific_episode(page, series_id=series_id, series_name=series_name)
            select_tiktok_mini(
                page,
                tt_mini_id=str(rec.get("TT Mini ID") or "").strip(),
                mini_name=str(rec.get("Mini Game Name") or "").strip(),
            )
            # 选完 Mini 才会出现「选择价值类型」，默认是「应用内购价值」，
            # 短剧要改成「广告收入价值」，改完再填 ROAS。
            select_ad_revenue_value_type(page)
            select_target_roas_drama(page, rec["roas_bid"])

            region_pairs, missing = resolve_regions(str(rec["Region"]).strip())
            for rid in missing:
                warnings.append(f"[{tag}] 地区ID {rid} 在对照表里找不到")
            if not region_pairs:
                raise ValueError(
                    f"[{tag}] 没有任何可用地区（TikTok 要求至少选一个地区才能继续）"
                )
            failed = set_regions_drama(page, region_pairs)
            if failed:
                # 地域没选中时把现场留下来。这一块在小游戏那边一直是好的，
                # 短剧这边出问题多半跟【上一步是否滚动过页面】有关：
                # ROAS 如果已经是目标值就会被跳过，页面就停在别的位置。
                # 不留现场只会又靠猜。
                try:
                    from src.config import LOGS_DIR

                    page.screenshot(path=str(LOGS_DIR / "drama_region_FAIL.png"))
                    from src.drama.pages.adgroup_page import _visible_placeholders

                    warnings.append(
                        f"[{tag}] 地域失败现场：可见输入框 {_visible_placeholders(page)}；"
                        f"截图 logs/drama_region_FAIL.png"
                    )
                except Exception:
                    pass
            for rid, name in failed or []:
                warnings.append(f"[{tag}] 地区 {name}({rid}) 未能在页面上选中")
            if failed and len(failed) == len(region_pairs):
                raise ValueError(f"[{tag}] 所有地区都没能选中，无法继续")

            continue_step(page)
            wait_ad_page_ready(page)

            # 素材按 (广告主, 剧名) 分桶去重，整次运行共用同一个集合：
            # 同一个计划下的第 2、3… 个广告组不会选到前面用过的素材，
            # 整个库用完了才绕回头复用。
            used = creative_usage.setdefault((str(advertiser_id), series_name), set())
            before = len(used)
            picked, wrapped = select_drama_creatives(
                page, search_override or series_name, _creative_count(rec),
                used_ids=used
            )
            want = _creative_count(rec)
            if picked < want:
                warnings.append(f"[{tag}] 只选到 {picked} 个素材，少于要求的 {want} 个")
            if wrapped:
                warnings.append(
                    f"[{tag}] 素材库不够用，已绕回头复用之前用过的素材"
                )
            elif len(used) - before < picked:
                warnings.append(
                    f"[{tag}] 选中 {picked} 个素材，但去重集合只新增了 "
                    f"{len(used) - before} 个——可能选到了重复素材，请人工核对"
                )

            # 身份（TikTok 账号）不碰：选完素材后 TikTok 会自动填好，
            # 页面上也写着「自定义身份已不再可用」，动它只有改错的风险。
            fill_drama_ad_copy(page, str(rec.get("ads_text") or "").strip())
            fill_drama_minis_url(page, str(rec.get("TT Mini URL") or "").strip())

            if publish:
                # 每个广告组建完就发布。新流程必须这样——发布完页面才会回到
                # 计划列表，才能从列表进原计划去建下一个。
                publish_all(page)
            else:
                warnings.append("未发布 —— 草稿已保存，需人工检查后手动点「全部发布」")

        return {"success": True, "error": None, "warnings": warnings}

    except Exception as e:
        try:
            exit_draft(page)
        except Exception:
            pass
        return {"success": False, "error": str(e), "warnings": warnings}
