import re

from src.identity_lookup import resolve_identity
from src.pages.ad_page import (
    fill_ad_copy,
    fill_landing_url,
    select_creative_materials,
    select_identity,
    wait_ad_page_ready,
)
from src.pages.adgroup_page import (
    fill_ad_group_name,
    fill_adgroup_budget_if_present,
    select_all_available_regions,
    select_all_available_regions_except,
    select_mini_game,
    set_regions,
    set_target_roas,
    wait_adgroup_page_ready,
)
from src.pages.campaign_page import (
    add_new_ad_group,
    continue_step,
    fill_campaign_details,
    publish_all,
    select_native_growth_objective,
    start_new_campaign,
)
from src.pages.common import exit_draft
from src.pages.duplicate import duplicate_ad_group_n_times, duplicate_ad_n_times
from src.region_lookup import resolve_regions

# Exact Region value that signals "the old API-based tool wanted broad targeting but
# was capped" - only THIS specific combination means "select every available region
# in the picker". Any other Region value (including other long lists) is honored
# literally as the specific ids the user wants targeted.
ALL_REGIONS_SENTINEL_IDS = frozenset(
    x.strip()
    for x in "6252001,1861060,1605651,1733045,298795,3469034,1694008,1643084".split(",")
)

# Excel cells sometimes use a full-width Chinese comma "，" (easy to type by accident
# with a Chinese IME) instead of ",". Accept either wherever a Region cell is split.
_REGION_SPLIT_RE = re.compile("[,，]")


def _is_select_all_sentinel(region_value):
    ids = frozenset(x.strip() for x in _REGION_SPLIT_RE.split(str(region_value)) if x.strip())
    return ids == ALL_REGIONS_SENTINEL_IDS


# Region cell value like "ex6252001" (or "ex6252001,1861060" for more than one)
# means "every available region EXCEPT these ids" - e.g. "非美国地区" via ex6252001.
def _parse_exclude_sentinel(region_value):
    s = str(region_value).strip()
    if not s.lower().startswith("ex"):
        return None
    ids = [x.strip() for x in _REGION_SPLIT_RE.split(s[2:]) if x.strip()]
    if not ids or not all(x.isdigit() for x in ids):
        return None
    return ids


def fill_adgroup_core(page, rec, budget=None, needs_adgroup_budget=False):
    fill_ad_group_name(page, rec["Ad Group Name"])
    select_mini_game(page, rec["Mini Game Name"], str(rec["TT Mini ID"]))
    set_target_roas(page, rec["roas_bid"])

    if needs_adgroup_budget:
        fill_adgroup_budget_if_present(page, budget)

    region_value = rec["Region"]
    exclude_ids = _parse_exclude_sentinel(region_value)
    if exclude_ids is not None:
        checked_count, missing_ids, failed_regions = select_all_available_regions_except(
            page, exclude_ids
        )
        return {
            "mode": "all_except",
            "checked": checked_count,
            "missing": missing_ids,
            "failed": failed_regions,
        }

    if _is_select_all_sentinel(region_value):
        checked_count = select_all_available_regions(page)
        return {"mode": "all", "checked": checked_count, "missing": [], "failed": []}

    region_pairs, missing_regions = resolve_regions(str(region_value))
    failed_regions = set_regions(page, region_pairs)
    return {
        "mode": "exact",
        "checked": len(region_pairs) - len(failed_regions),
        "missing": missing_regions,
        "failed": failed_regions,
    }


def _creative_count_for(rec):
    val = rec.get("Creative Number")
    try:
        return int(val) if val not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def fill_ad_creatives(page, rec, advertiser_id, creative_usage, patient=False):
    """广告层里【只挑素材】的那一半。返回一句警告或 None。

    patient=True 时给素材库更多耐心（每批等 40 秒、每批加载完静置 3 秒再选）。
    「每组素材不同」那条路会开这个：使用者的要求是「选素材的时候一定要慢，要往下
    滚动找素材，尽量不要选择重复的」——宁可慢，也别选重复。这个值和短剧那边一致。
    """
    count = _creative_count_for(rec)
    if count <= 2:
        return None

    search_term = str(rec.get("CreativeFile") or "").strip()
    if not search_term:
        return "Creative Number 大于2但 CreativeFile 是空的，跳过手动选素材"

    key = (str(advertiser_id), str(rec["TT Mini ID"]))
    used = creative_usage.setdefault(key, set())
    kwargs = {"batch_wait_seconds": 40, "batch_settle_ms": 3000} if patient else {}
    selected, wrapped = select_creative_materials(
        page, search_term, count, used_ids=used, **kwargs
    )
    if selected < count:
        return (
            f"素材库搜索 '{search_term}' 只选到 {selected}/{count} 个素材"
            f"（整个素材库连一轮都凑不满 {count} 个）"
        )
    if wrapped:
        return (
            f"素材库搜索 '{search_term}' 的素材已全部用过一轮，"
            f"本条广告开始复用（素材不够，这是预期的兜底行为）"
        )
    return None


def fill_ad_identity_copy_url(page, rec, advertiser_id):
    """广告层里【除素材以外】的那一半：身份、文案、落地页链接。返回警告或 None。

    「每组素材不同」那条路会【先】调这个再复制广告组：副本会把文案和 URL 一起继承
    过去（那正是想要的，各广告的文案/URL 本来就一样），只有素材是空的，之后逐个挑。
    这么排还顺带治好了一个老毛病——平台发现落地页链接是空的就会自动把页面拽到
    URL 那一块，害得顶部的「自动选择」框在视口外、甚至卡住不给点。URL 先填好，
    平台就没有理由跳了。
    """
    identity_id = str(rec["Identity_ID"]).strip() if rec["Identity_ID"] else ""
    handle = resolve_identity(identity_id) if identity_id else None
    identity_issue = None
    if handle:
        try:
            select_identity(page, handle)
        except Exception as e:
            # 这里【刻意catch所有异常】而不只是 ValueError。
            # 原来那条路是先选素材再选身份，身份下拉那时已经是就绪的；新顺序把它挪到
            # 了素材之前，下拉可能还没准备好，于是除了我们自己抛的 ValueError，还可能
            # 冒出 Playwright 的 TimeoutError（click / scroll_into_view 超时）。
            # 身份不是关键项——短剧那条流程压根不选它，TikTok 会自己填好——所以它失败
            # 只该变成一句警告，绝不该把整个计划搞挂。
            identity_issue = f"选身份失败（不影响其它步骤）: {str(e).splitlines()[0][:120]}"
    elif identity_id:
        identity_issue = f"Identity_ID '{identity_id}' 在 identity_id.xlsx 里找不到对应名字"

    fill_ad_copy(page, str(rec["ads_text"]))
    fill_landing_url(page, str(rec["TT Mini URL"]))
    return identity_issue


def fill_ad_core(page, rec, advertiser_id, creative_usage):
    """creative_usage: dict shared across an entire run (NOT per-campaign),
    keyed by (advertiser_id, tt_mini_id) -> set of material identities already
    used - so multiple campaigns targeting the same mini game on the same
    account pick different materials. Caller creates one fresh dict per run and
    passes the same one into every build_campaign_group call.

    以前这里存的是「已经用掉多少个」，然后靠 skip=N 跳过列表里前 N 个复选框——
    纯按位置。列表顺序一变（按上传时间排序、中途上传新素材、DOM 混进别的复选框）
    跳过的就不是同一批素材，去重形同虚设，而且只记数量不记身份，无法验证。
    现在存的是【素材身份集合】，由 select_creative_materials 就地增删。

    去重范围是【单次运行】：每次运行新建一个空 dict，所以同一次运行内不会重复，
    跨运行会重新开始。素材不够时会绕回头复用，保证每条广告都选满。

    顺序（素材 -> 身份/文案/URL）刻意保持不变，这是原来一直在跑的那条路。
    「每组素材不同」那条路要的顺序不同，它自己分别调下面那两个函数。
    """
    creative_issue = fill_ad_creatives(page, rec, advertiser_id, creative_usage)
    identity_issue = fill_ad_identity_copy_url(page, rec, advertiser_id)

    issues = [i for i in (creative_issue, identity_issue) if i]
    return "；".join(issues) if issues else None


def _extra_copies_for(rec):
    val = rec.get("Ad Group Name Number")
    try:
        return int(val) if val not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


# 「每个广告组用不同素材」这个开关的 Excel 列名（同义写法都认）。
# 表格里没有这一列、或者格子是空的，就沿用调用方传进来的 unique_creatives 默认值。
# 多写几种拼法是因为这一列由使用者手填、叫法不固定；load_rows 会把不在
# OPTIONAL_COLUMNS 名单里的列【整列丢掉】，名字对不上等于这一列不存在，还很难发现。
_UNIQUE_COLUMNS = (
    "Unique Creative",
    "Unique Creatives",
    "unique_creative",
    "素材不重复",
    "每组素材不同",
)

_TRUE_WORDS = {"1", "true", "yes", "y", "是", "对", "开", "√", "on"}
_FALSE_WORDS = {"0", "false", "no", "n", "否", "不", "关", "off", "×"}


def _unique_creatives_for(rec, default=False):
    """这一行要不要走「每个广告组素材都不同」的搭法。

    行内的列优先于全局开关：一张表里可能只有部分计划需要这么搭。
    读不懂的值当成没填（用 default），不猜——猜错的后果是搭出一堆重复素材的广告，
    而那是要花钱的。
    """
    for name in _UNIQUE_COLUMNS:
        val = rec.get(name)
        if val in (None, ""):
            continue
        s = str(val).strip().lower()
        if s in _TRUE_WORDS:
            return True
        if s in _FALSE_WORDS:
            return False
    return bool(default)


def _build_row_unique_creatives(
    page, rec, advertiser_id, creative_usage, extra_copies, warnings
):
    """一个计划里建多个广告组，每个广告组下一个广告，且每个广告的素材【都不一样】。

    顺序（2026-08-20 使用者定的，比上一版又提前了一步）：

        ① 在第一个广告组的广告层，先把【除素材以外】的都写完：身份、文案、URL
        ② 再复制广告组 —— 副本把文案和 URL 一起继承走（那正是想要的，各广告的
           文案/URL 本来就一样），只有素材是空的
        ③ 沿「继续」一个个广告【只选素材】，慢慢滚动找，尽量不重复

    对比前两版：
        最早：  填广告组 -> 继续 -> 填广告(含素材) -> 复制
                副本把素材也复制走了，所有广告组用同一批素材 ← 使用者要解决的问题
        上一版：填广告组 -> 继续 -> 立刻复制 -> 沿「继续」逐个填全部
                素材是分开的了，但每个广告的 URL 都还是空的，平台就一直把页面拽到
                URL 那一块，顶部的「自动选择」框跑到视口外、甚至卡住不给点
        现在：  URL 先填好，平台没理由再跳，「自动选择」就在眼前

    复制完之后怎么走由 step_flow.walk_and_fill_ads 负责——它每到一站先读清自己在
    广告组层还是广告层，而不是照抄点击次数。理由见那个模块的说明。

    调用前提：page 已经停在【第一个广告组的广告层】（continue_step +
    wait_ad_page_ready 之后）。
    """
    from src.pages.step_flow import walk_and_fill_ads

    total_ads = extra_copies + 1

    # 素材必须是手动挑的，否则「不重复」根本无从谈起：Creative Number <= 2 时
    # 不碰素材，沿用 TikTok 的「自动选择」——那是平台自己挑的，挑成什么样、会不会
    # 重复都不由我们决定。这种情况下这个开关是无效的，必须说出来，不能让人以为
    # 已经生效了。
    if _creative_count_for(rec) <= 2:
        warnings.append(
            f"[{rec['Ad Group Name']}] 开了「每组素材不同」，但 Creative Number 是 "
            f"{rec.get('Creative Number')!r}（<=2 时不手动挑素材，用的是 TikTok 的"
            "「自动选择」）。素材由平台决定，这个开关等于没生效。"
            "要让它起作用，请把 Creative Number 填成大于 2 的数，并填好 CreativeFile。"
        )

    # ① 除素材以外先写完
    print("      [每组素材不同] ① 先写身份/文案/URL（素材留到后面逐个挑）", flush=True)
    issue = fill_ad_identity_copy_url(page, rec, advertiser_id)
    if issue:
        warnings.append(f"[{rec['Ad Group Name']}] {issue}")

    # ② 再复制 —— 此时素材还是空的，副本只继承文案/URL
    #
    # 复制之前先静置几秒。这不是凭空加的等待：原来那条路走到复制这一步时，前面
    # 刚经历了几分钟的选素材过程（搜索、滚动、逐个勾选、保存），页面早就完全安定了；
    # 新顺序把复制紧挨在「填完 URL」后面，页面可能还在跑自动保存/校验，左侧那一行
    # 正在重渲染，于是 hover 上去点复制图标点不到——使用者实测「开着这个功能容易
    # 出现点不到复制按钮」，就是这个时间点。
    # 复制用的还是原来那个 duplicate_ad_group_n_times，一个字没改。
    page.wait_for_timeout(3000)
    print(f"      [每组素材不同] ② 复制 {extra_copies} 个广告组"
          f"（文案/URL 会被继承，素材是空的），共 {total_ads} 个广告要挑素材", flush=True)
    duplicate_ad_group_n_times(page, rec["Ad Group Name"], extra_copies)

    # ③ 沿「继续」逐个只挑素材，patient=True（宁可慢也别选重复）
    def fill_one(index):
        got = fill_ad_creatives(
            page, rec, advertiser_id, creative_usage, patient=True
        )
        return f"[{rec['Ad Group Name']} 第{index + 1}个广告] {got}" if got else None

    filled, chain_warnings = walk_and_fill_ads(
        page, fill_one, expected_ads=total_ads,
        log=lambda m: print(m, flush=True),
    )
    warnings.extend(chain_warnings)
    return filled, total_ads


def build_campaign_group(
    page,
    advertiser_id,
    campaign_name,
    budget,
    rows,
    publish=False,
    creative_usage=None,
    unique_creatives=False,
):
    """rows: list of record dicts sharing the same Campaign Name. Each row gets its
    own ad group + ad built from scratch (row 0 uses the ad group created by the
    campaign flow itself; rows 1+ get a fresh BLANK ad group via the campaign's "+"
    icon - NOT a duplicate, since different rows carry different data). Only after
    a row's ad group AND ad are both fully filled in does its own
    'Ad Group Name Number' (if any) get duplicated - duplicating any earlier only
    copies incomplete ad content.
    creative_usage: shared dict across a whole run for the manual-creative-material
    de-duplication offset (see fill_ad_core) - pass the SAME dict into every call
    within one run; a fresh dict is created here only if the caller doesn't
    care about that (e.g. building a single standalone campaign).

    unique_creatives: 「每个广告组用不同素材」。默认 False = 保持原有行为不变。
    开启后，带 'Ad Group Name Number' 的行改成「先复制空广告组，再沿「继续」逐个
    填广告」——这样每个广告组下的广告各自挑自己的素材，而不是复制同一批。
    可以被表格里的 Unique Creative 列按行覆盖（见 _unique_creatives_for）。

    Returns dict: {"success": bool, "error": str|None, "warnings": [str]}
    """
    if creative_usage is None:
        creative_usage = {}
    warnings = []
    # 不为 None 时表示「这个计划有空广告，别发布」——见下面 _build_row_unique_creatives
    # 的返回值处理。发布前检查它，而不是发出去再失败。
    skip_publish_reason = None
    try:
        start_new_campaign(page, advertiser_id)
        select_native_growth_objective(page)
        budget_set_at_campaign = fill_campaign_details(page, campaign_name, budget)
        if not budget_set_at_campaign:
            warnings.append(
                "这个账号在计划层级没有预算区域，预算会改到广告组层级去填（少数账号类型，正常现象）"
            )
        continue_step(page)
        wait_adgroup_page_ready(page)

        for i, rec in enumerate(rows):
            if i > 0:
                add_new_ad_group(page, campaign_name)
                wait_adgroup_page_ready(page)

            region_result = fill_adgroup_core(
                page, rec, budget=budget, needs_adgroup_budget=not budget_set_at_campaign
            )
            for rid in region_result["missing"]:
                warnings.append(f"[{rec['Ad Group Name']}] 地区ID {rid} 在对照表里找不到")
            for rid, name in region_result["failed"]:
                warnings.append(f"[{rec['Ad Group Name']}] 地区 {name}({rid}) 未能在页面上选中")
            if region_result["checked"] == 0:
                raise RuntimeError(
                    f"[{rec['Ad Group Name']}] 没有任何地区被选中，无法继续（TikTok要求至少选一个地区才能进入下一步）"
                )

            continue_step(page)
            wait_ad_page_ready(page)

            extra_copies = _extra_copies_for(rec)
            row_unique = _unique_creatives_for(rec, default=unique_creatives)

            # 「每组素材不同」这条路要在【素材还没加之前】复制广告组，所以它必须
            # 抢在 fill_ad_core 前面分岔——一旦填了素材就晚了，副本会把素材带走。
            #
            # 只在【这个计划只有一行】时走：这条路靠「沿「继续」走到第 k 个广告层
            # 就挑第 k 个广告的素材」来防重复，前提是链条上的广告层都是本行刚复制
            # 出来的。一个计划里有多行时，链条会先经过前面那些行【已经挑好素材】的
            # 广告组，按数就会数到它们头上，给已经有素材的广告再加一遍。
            # 本来想靠「这个广告填过没有」来分辨，但那个判据是错的（小游戏的落地页
            # 平台会自己带出来，而且新顺序下文案/URL 是复制前就填好的），
            # 详见 step_flow 里那段说明。所以这里不赌，直接降级并说清楚。
            if row_unique and extra_copies > 0 and budget_set_at_campaign:
                if len(rows) > 1:
                    warnings.append(
                        f"[{rec['Ad Group Name']}] 这个计划在表格里有 {len(rows)} 行，"
                        "「每组素材不同」这次没有生效（按原来的方式搭，副本的素材会一样）。"
                        "原因：那条路要沿「继续」把整个计划的广告组走一遍逐个挑素材，"
                        "多行时会走到别行已经挑好素材的广告上、给它重复加素材。"
                        "想用这个功能的话，把同一个计划拆成一行、用 Ad Group Name Number "
                        "指定广告组数量。"
                    )
                else:
                    filled, wanted = _build_row_unique_creatives(
                        page, rec, advertiser_id, creative_usage, extra_copies, warnings
                    )
                    if filled < wanted:
                        # 有广告没挑到素材。这时候【不要去发布】：平台一定会因为
                        # 空广告报错，而发布重试要点 6 轮、每轮等 90 秒，白耗好几分钟
                        # 最后还是失败（2026-08-20 实测就是这样）。
                        # 也不抛异常——抛了会走到 exit_draft 把草稿整个丢掉，
                        # 而这里已经建好的广告组是有价值的，留着让人手动补完更划算。
                        incomplete = (
                            f"[{rec['Ad Group Name']}] 只有 {filled}/{wanted} 个广告"
                            "挑到了素材，剩下的是空广告。已跳过发布（空广告一定发不出去），"
                            "草稿留在后台，请手动补完素材再发布。"
                        )
                        warnings.append(incomplete)
                        skip_publish_reason = incomplete
                    continue

            if row_unique and extra_copies > 0 and not budget_set_at_campaign:
                # 这类账号（计划层没有预算区）压根没有「复制广告组」这个功能，
                # 只能复制广告本身——而复制广告一定会把素材一起带走，做不到不重复。
                # 明确降级并说清楚，不要假装开关生效了。
                warnings.append(
                    f"[{rec['Ad Group Name']}] 这个账号在计划层级没有预算区，"
                    "也就没有「复制广告组」功能，只能复制广告本身（素材会一样）。"
                    "「每组素材不同」这次没能生效。"
                )

            issue = fill_ad_core(page, rec, advertiser_id, creative_usage)
            if issue:
                warnings.append(f"[{rec['Ad Group Name']}] {issue}")

            if extra_copies > 0:
                if budget_set_at_campaign:
                    duplicate_ad_group_n_times(page, rec["Ad Group Name"], extra_copies)
                else:
                    # this account type (no campaign-level budget) has no
                    # "复制广告组" at all - duplicate the ad itself instead,
                    # same confirmed signal as the budget branch
                    duplicate_ad_n_times(page, extra_copies)

        if publish and skip_publish_reason:
            return {"success": False, "error": skip_publish_reason, "warnings": warnings}

        if publish:
            # 2026-08-19 换成共用的 publish_all（原来是直接 click「全部发布」再等
            # 页面自己跳回计划列表）。两个原因，都由新的「多广告组、每组素材不同」
            # 暴露出来：
            #  * 使用者的截图里，单个广告组时「全部发布」是普通按钮，多个广告组时
            #    旁边多了下拉箭头——命中多个元素时 .click() 会抛 strict mode
            #    violation。publish_all 逐个挑可见的，不会撞。
            #  * 一个计划里广告数量大于 1 时，点发布有概率弹报错框（使用者实测的
            #    平台 bug），要点「修复」等它消失再发。原来的代码遇到这个只会
            #    干等 300 秒然后超时，整次搭建白费。
            # 「等页面自己跳回计划列表、绝不自己强行跳转」这条关键行为没有变。
            publish_all(page)
        else:
            warnings.append("未发布 - 草稿已保存，需手动检查并点击'全部发布'")

        return {"success": True, "error": None, "warnings": warnings}

    except Exception as e:
        try:
            exit_draft(page)
        except Exception:
            pass
        return {"success": False, "error": str(e), "warnings": warnings}
