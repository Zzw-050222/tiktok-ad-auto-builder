import re

from src.identity_lookup import resolve_identity
from src.pages.ad_page import fill_ad_copy, fill_landing_url, select_identity, wait_ad_page_ready
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


def fill_ad_core(page, rec):
    identity_id = str(rec["Identity_ID"]).strip() if rec["Identity_ID"] else ""
    handle = resolve_identity(identity_id) if identity_id else None
    identity_issue = None
    if handle:
        try:
            select_identity(page, handle)
        except ValueError as e:
            identity_issue = str(e)
    elif identity_id:
        identity_issue = f"Identity_ID '{identity_id}' 在 identity_id.xlsx 里找不到对应名字"

    fill_ad_copy(page, str(rec["ads_text"]))
    fill_landing_url(page, str(rec["TT Mini URL"]))
    return identity_issue


def _extra_copies_for(rec):
    val = rec.get("Ad Group Name Number")
    try:
        return int(val) if val not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def build_campaign_group(page, advertiser_id, campaign_name, budget, rows, publish=False):
    """rows: list of record dicts sharing the same Campaign Name. Each row gets its
    own ad group + ad built from scratch (row 0 uses the ad group created by the
    campaign flow itself; rows 1+ get a fresh BLANK ad group via the campaign's "+"
    icon - NOT a duplicate, since different rows carry different data). Only after
    a row's ad group AND ad are both fully filled in does its own
    'Ad Group Name Number' (if any) get duplicated - duplicating any earlier only
    copies incomplete ad content.
    Returns dict: {"success": bool, "error": str|None, "warnings": [str]}
    """
    warnings = []
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
            issue = fill_ad_core(page, rec)
            if issue:
                warnings.append(f"[{rec['Ad Group Name']}] {issue}")

            extra_copies = _extra_copies_for(rec)
            if extra_copies > 0:
                if budget_set_at_campaign:
                    duplicate_ad_group_n_times(page, rec["Ad Group Name"], extra_copies)
                else:
                    # this account type (no campaign-level budget) has no
                    # "复制广告组" at all - duplicate the ad itself instead,
                    # same confirmed signal as the budget branch
                    duplicate_ad_n_times(page, extra_copies)

        if publish:
            page.get_by_role("button", name="全部发布", exact=True).click(timeout=15000)
            # wait for the "恭喜！广告创建中...X%" progress modal to appear, then
            # wait for the whole publish to actually finish and the page to
            # navigate back to the campaign list ON ITS OWN. Never force-navigate
            # ourselves here - jumping away mid-publish interrupts it and the
            # campaign doesn't actually go live. Slow is fine; premature is not.
            try:
                page.get_by_text("广告创建中", exact=False).wait_for(
                    state="visible", timeout=15000
                )
            except Exception:
                pass
            page.wait_for_url(lambda url: "manage/campaign" in url, timeout=300000)
            page.wait_for_timeout(1500)
        else:
            warnings.append("未发布 - 草稿已保存，需手动检查并点击'全部发布'")

        return {"success": True, "error": None, "warnings": warnings}

    except Exception as e:
        try:
            exit_draft(page)
        except Exception:
            pass
        return {"success": False, "error": str(e), "warnings": warnings}
