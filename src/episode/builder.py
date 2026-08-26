"""短剧端计划 —— 一整条计划的搭建。

使用者定的框架就是【照搬小游戏「每组素材不同」那条路】：一个计划里多个广告组，
每个广告组下一个广告，每个广告的素材都不一样。

    计划层   完全复刻小游戏（创建广告 -> 即时增长 -> 推广系列预算 + 预算 -> 继续）
             注意：【不要】打开「设置商品库推广系列」那个开关，那是商品库模式的
    广告组层 见 pages/adgroup_page.fill_adgroup_core
             （名称 -> 优化位置=剧集 -> 身份 -> 剧集 -> 价值类型 -> ROAS -> 地域）
    广告层   ① 身份 + 文案（【没有 URL 这个框】，不填）
             ② 复制广告组（光标放上去出现 + 号，点它）
             ③ 沿「继续」逐个只挑素材
             ④ 全部发布

和小游戏那条路唯一的三处不同：
  1. 不填 URL —— 页面上根本没有这个框。
     顺带说明：小游戏那边把 URL 提到复制之前填，是为了不让平台把页面拽到 URL 区、
     害得顶部「自动选择」跑到视口外（见 src/builder.py 里那段说明）。
     这里没有 URL 框，那个问题自然就不存在。
  2. 素材的搜索词是【剧名】，不是表格里的 CreativeFile 列。
     使用者原话：「素材名称就是计划名称第一个字段，也就是剧名」。
  3. 素材去重的键是 (广告主, 剧名)，小游戏那边是 (广告主, 小游戏ID)。
"""

from src.pages.ad_page import (
    fill_ad_copy,
    select_creative_materials,
    select_identity,
    wait_ad_page_ready,
)
from src.pages.adgroup_page import wait_adgroup_page_ready
from src.pages.campaign_page import (
    add_new_ad_group,
    continue_step,
    fill_campaign_details,
    publish_all,
    select_native_growth_objective,
    start_new_campaign,
)
from src.pages.duplicate import duplicate_ad_group_n_times
from src.pages.step_flow import walk_and_fill_ads
from src.episode.pages.adgroup_page import fill_adgroup_core
from src.identity_lookup import identity_file_exists, resolve_identity
from src.region_lookup import resolve_regions


def series_name_for(campaign_name, name_to_id=None):
    """从计划名开头认出剧名。返回 (剧名, 警告或 None)。

    使用者说的「计划名称第一个字段」。刻意【不】写成按 '-' 拆首段：
    对照表里有剧名本身带连字符，拆了就断（The Seventh-Year Intern -> 'The Seventh'）。
    所以优先用商品库那边已经踩好坑的 resolve_series_from_campaign_name，
    它做的是【最长前缀匹配】，还能处理「一个剧名是另一个的前缀」那 7 对。

    没有 商品库-剧目.xlsx（那是业务数据，不进安装包）时退回按 '-' 拆首段，
    并且【说出来】—— 拆错了会投错剧、也会搜错素材，不能默默用。
    """
    camp = str(campaign_name).strip()
    try:
        from src.drama.series_lookup import resolve_series_from_campaign_name

        name, _sid = resolve_series_from_campaign_name(camp, name_to_id)
        return name, None
    except Exception as e:
        first = camp.split("-")[0].strip()
        if not first:
            raise ValueError(f"计划名 {camp!r} 取不出剧名")
        return first, (
            f"剧名是按 '-' 拆计划名首段得到的「{first}」，没能用剧目对照表核对"
            f"（{str(e).splitlines()[0][:80]}）。"
            "剧名本身带连字符的话这样会拆断，请核对一下选到的剧集和素材对不对。"
        )


def _identity_name_for(rec):
    """表格里的 Identity_ID -> TikTok 上显示的账号名。返回 (名字, 警告或 None)。"""
    ident = str(rec.get("Identity_ID") or "").strip()
    if not ident:
        return "", None
    if not identity_file_exists():
        return "", (
            "这台电脑上没有身份对照表 Identity_id.xlsx，身份这一项会跳过。"
            "在网页第 3 步上传一份就行。"
        )
    handle = resolve_identity(ident)
    if not handle:
        return "", f"Identity_ID {ident!r} 在身份对照表里找不到对应名字"
    return handle, None


def _extra_copies_for(rec):
    """这一行要额外复制几个广告组。"""
    val = rec.get("Ad Group Name Number")
    try:
        n = int(float(str(val).strip()))
    except (TypeError, ValueError):
        return 0
    return max(0, n)


def _creative_count_for(rec):
    try:
        return int(float(str(rec.get("Creative Number")).strip()))
    except (TypeError, ValueError):
        return 0


def fill_ad_identity_and_copy(page, rec, identity_name):
    """广告层里【除素材以外】的部分：身份 + 文案。没有 URL 这一项。

    身份和文案的操作细节都是照搬小游戏的（使用者原话「操作细节和小游戏一模一样」），
    所以直接调它们的函数，不另写一份。

    身份失败只记警告，不把整条计划弄挂 —— 和小游戏那边同一条规矩
    （见 src/builder.py fill_ad_identity_copy_url 里的说明）：
    身份不是关键项，而且它在广告组层已经选过一次了。
    """
    issue = None
    if identity_name:
        try:
            select_identity(page, identity_name)
        except Exception as e:
            issue = f"广告层选身份失败（不影响其它步骤）: {str(e).splitlines()[0][:120]}"

    fill_ad_copy(page, str(rec["ads_text"]))
    return issue


def fill_ad_creatives(page, rec, advertiser_id, series_name, creative_usage,
                      patient=True):
    """广告层里【只挑素材】的那一半。返回一句警告或 None。

    搜索词用【剧名】而不是 CreativeFile 列 —— 使用者原话：
    「素材名称就是计划名称第一个字段，也就是剧名」。

    patient=True：使用者要求「选素材的时候一定要慢，要往下滚动找素材，
    尽量不要选择重复的」。宁可慢，也别选重复。和小游戏那条路取值一致。
    """
    count = _creative_count_for(rec)
    if count <= 2:
        return None

    key = (str(advertiser_id), str(series_name))
    used = creative_usage.setdefault(key, set())
    kwargs = {"batch_wait_seconds": 40, "batch_settle_ms": 3000} if patient else {}
    selected, wrapped = select_creative_materials(
        page, series_name, count, used_ids=used, **kwargs
    )
    if selected < count:
        return (
            f"素材库搜索「{series_name}」只选到 {selected}/{count} 个素材"
            f"（整个素材库连一轮都凑不满 {count} 个）"
        )
    if wrapped:
        return (
            f"素材库搜索「{series_name}」的素材已全部用过一轮，"
            "本条广告开始复用（素材不够，这是预期的兜底行为）"
        )
    return None


def _build_row_ads(page, rec, advertiser_id, series_name, identity_name,
                   creative_usage, extra_copies, warnings):
    """广告层这一段：① 身份+文案 ② 复制广告组 ③ 沿「继续」逐个挑素材。

    顺序照搬小游戏「每组素材不同」那条路，一步都没改：
        先把除素材以外的写完 -> 再复制（副本继承文案，素材是空的）
        -> 沿「继续」一个个只挑素材
    先复制再填素材，是为了让每个广告组挑到【不同】的素材；反过来先填素材再复制，
    副本会把素材一起带走，所有广告组用同一批。

    调用前提：page 已经停在【第一个广告组的广告层】。
    """
    total_ads = extra_copies + 1
    tag = rec["Ad Group Name"]

    if _creative_count_for(rec) <= 2:
        warnings.append(
            f"[{tag}] Creative Number 是 {rec.get('Creative Number')!r}"
            "（<=2 时不手动挑素材，用的是 TikTok 的「自动选择」）。"
            "素材由平台决定，「每组素材不同」等于没生效。"
            "要让它起作用，请把 Creative Number 填成大于 2 的数。"
        )

    # ① 除素材以外先写完（没有 URL 这一项）
    print("      [广告层] ① 先写身份/文案（没有 URL 框；素材留到后面逐个挑）",
          flush=True)
    issue = fill_ad_identity_and_copy(page, rec, identity_name)
    if issue:
        warnings.append(f"[{tag}] {issue}")

    # ② 再复制。
    # 复制之前先静置几秒 —— 这一条是小游戏那边实测出来的：复制紧挨在「刚填完」
    # 后面时，页面可能还在跑自动保存/校验，左侧那一行正在重渲染，
    # hover 上去点不到复制图标。复制本身用的还是原来那个函数，一个字没改。
    if extra_copies > 0:
        page.wait_for_timeout(3000)
        print(f"      [广告层] ② 复制 {extra_copies} 个广告组"
              f"（文案会被继承，素材是空的），共 {total_ads} 个广告要挑素材",
              flush=True)
        duplicate_ad_group_n_times(page, tag, extra_copies)

    # ③ 沿「继续」逐个只挑素材
    def fill_one(index):
        got = fill_ad_creatives(
            page, rec, advertiser_id, series_name, creative_usage, patient=True
        )
        return f"[{tag} 第{index + 1}个广告] {got}" if got else None

    filled, chain_warnings = walk_and_fill_ads(
        page, fill_one, expected_ads=total_ads,
        log=lambda m: print(m, flush=True),
    )
    warnings.extend(chain_warnings)
    return filled, total_ads


def build_episode_campaign(page, advertiser_id, campaign_name, budget, rows,
                           publish=False, creative_usage=None,
                           series_name_map=None):
    """建一条短剧端计划。返回 {"success", "error", "warnings"}。

    creative_usage: 整个运行期共享的一个 dict，用来保证素材不重复。调用方每次
    运行新建一个空 dict，然后一直传同一个进来。
    """
    if creative_usage is None:
        creative_usage = {}
    warnings = []
    skip_publish_reason = None

    try:
        series_name, name_warn = series_name_for(campaign_name, series_name_map)
        if name_warn:
            warnings.append(name_warn)
        print(f"      剧名（用于选剧集和搜素材）：{series_name!r}", flush=True)

        # ---- 计划层：完全复刻小游戏，一行新代码都没有 ----
        start_new_campaign(page, advertiser_id)
        select_native_growth_objective(page)
        budget_at_campaign = fill_campaign_details(page, campaign_name, budget)
        if not budget_at_campaign:
            warnings.append(
                "这个账号在计划层级没有预算区域，预算会改到广告组层级去填"
                "（少数账号类型，正常现象）"
            )
        continue_step(page)
        wait_adgroup_page_ready(page)

        for i, rec in enumerate(rows):
            tag = rec["Ad Group Name"]
            if i > 0:
                print(f"      从计划里新建第 {i + 1} 个广告组…", flush=True)
                add_new_ad_group(page, campaign_name)
                wait_adgroup_page_ready(page)

            identity_name, id_warn = _identity_name_for(rec)
            if id_warn:
                warnings.append(f"[{tag}] {id_warn}")

            region_pairs, missing = resolve_regions(str(rec["Region"]).strip())
            for rid in missing:
                warnings.append(f"[{tag}] 地区ID {rid} 在对照表里找不到")
            if not region_pairs:
                raise ValueError(
                    f"[{tag}] 没有任何可用地区（TikTok 要求至少选一个地区才能继续）"
                )

            # ---- 广告组层 ----
            warnings.extend(
                fill_adgroup_core(page, rec, identity_name, series_name, region_pairs)
            )

            continue_step(page)
            wait_ad_page_ready(page)

            # ---- 广告层 ----
            filled, total_ads = _build_row_ads(
                page, rec, advertiser_id, series_name, identity_name,
                creative_usage, _extra_copies_for(rec), warnings,
            )
            if filled < total_ads:
                # 有广告是空的就别发布 —— 发出去也会失败，还不如把草稿留着让人去看。
                skip_publish_reason = (
                    f"[{tag}] 预期填 {total_ads} 个广告，实际只填了 {filled} 个，"
                    "有广告是空的，已跳过发布，草稿留在后台"
                )
                break

        if publish and skip_publish_reason:
            return {"success": False, "error": skip_publish_reason,
                    "warnings": warnings}
        if publish:
            publish_all(page)
        elif skip_publish_reason:
            warnings.append(skip_publish_reason)

        return {"success": True, "error": None, "warnings": warnings}

    except Exception as e:
        return {
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "warnings": warnings,
        }
