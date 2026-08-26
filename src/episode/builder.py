"""短剧端计划 —— 一整条计划的搭建。

使用者定的框架就是【照搬小游戏「每组素材不同」那条路】：一个计划里多个广告组，
每个广告组下一个广告，每个广告的素材都不一样。

    计划层   完全复刻小游戏（创建广告 -> 即时增长 -> 推广系列预算 + 预算 -> 继续）
             注意：【不要】打开「设置商品库推广系列」那个开关，那是商品库模式的
    广告组层 见 pages/adgroup_page.fill_adgroup_core
             （名称 -> 优化位置=剧集 -> 身份 -> 剧集 -> 价值类型 -> ROAS -> 地域）
    广告层   ① 身份 + 文案（【没有 URL 这个框】，不填）
             ② 复制【广告】（光标放在广告那一行上出现 + 号，点它）
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
from src.pages.duplicate import duplicate_ad_n_times
from src.episode.pages.adgroup_page import fill_adgroup_core
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


# 广告组层和广告层的身份是【两个不同的东西】（使用者明确说的），所以是两列。
# 列里存的直接就是【身份名字】（表里是 WeShorts_US），不是 Identity_ID，
# 所以【不用】查 Identity_id.xlsx —— 小游戏那边才需要那张对照表。
_IDENTITY_ADGROUP_COLS = ("Identity_drama",)
# accoount 是使用者表里的实际拼写（多一个 o）；正确拼写也认，免得哪天改回来就读不到了
_IDENTITY_AD_COLS = ("Identity_accoount", "Identity_account")


def _identity_from(rec, cols, what):
    """从这几列里取身份名字。返回 (名字, 警告或 None)。"""
    for c in cols:
        v = str(rec.get(c) or "").strip()
        if v:
            return v, None
    return "", f"表格里没有{what}的身份（列 {' / '.join(cols)} 都是空的），这一项会跳过"


# 一个广告组里要建几个【广告】。这一列由人手填，叫法不固定，所以多认几种写法 ——
# excel_loader 会把不在它名单里的列【整列丢掉】，名字对不上就等于这一列不存在。
# 和商品库那边用的是同一组键名。
_AD_COUNT_KEYS = ("Ad Number", "Ads Number", "Ad Name Number", "ad_number", "广告数量")


def _ad_count_for(rec):
    """这一行（= 这一个广告组）里要建几个广告。空或 <1 当作 1。

    结构是使用者用截图定下来的：复制出来的 5 个广告【都在同一个广告组下】。
    所以：
        表格一行  = 一个广告组
        Ad Number = 这个广告组里建几个广告，第 2 个起用【复制广告】生成
    我一开始按「N 行 = N 个广告组、第 2 个起靠复制」写，那是错的 ——
    复制的是广告不是广告组，两者不是一回事。
    """
    for k in _AD_COUNT_KEYS:
        v = rec.get(k)
        if v in (None, ""):
            continue
        try:
            return max(1, int(float(str(v).strip())))
        except (TypeError, ValueError):
            continue
    return 1


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
        # 用小游戏那个 select_identity，不用本模块广告组层那个。
        #
        # 理由是真机观察出来的：没加复制功能时，小游戏这个在广告层是【选上了】的
        # （使用者也确认「你之前没操作复制功能的时候我看你还选上了」）。
        # 我一度改成本模块的选择器，结果它按字段标题「身份（TikTok 账号）」找不到 ——
        # 探针实测广告层那个标题就是「身份」两个字，我的标题写错了。
        # 与其在这儿再赌一个标题，不如用已经在广告层跑通过的那一个。
        #
        # 加重试：探针里打开下拉后 WeShorts_US 是可见的（匹配4 可见3），
        # 说明账号在列表里，失败多半是列表还没加载完就判了。
        last = None
        for k in range(3):
            try:
                select_identity(page, identity_name)
                last = None
                break
            except Exception as e:
                last = e
                if k < 2:
                    print(f"        [广告层身份] 第{k + 1}次没选上，等 5 秒重试",
                          flush=True)
                    page.wait_for_timeout(5000)
        if last is not None:
            issue = (f"广告层选身份失败（不影响其它步骤）: "
                     f"{str(last).splitlines()[0][:140]}")

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
    # 把这一步的实际结果打出来。商品库那边本来就打，我这边漏了，
    # 结果第一次真机跑完只看到「✓ 成功」，而截图上创意素材那块还是「自动选择」——
    # 到底选了几个、去重集合有没有涨，全靠猜。
    before = len(used)
    print(f"        [素材] 搜「{series_name}」，要 {count} 个"
          f"（这个账号+剧目已用过 {before} 个）", flush=True)
    selected, wrapped = select_creative_materials(
        page, series_name, count, used_ids=used, **kwargs
    )
    print(f"        [素材] 选到 {selected} 个，去重集合 {before} → {len(used)}"
          f"，绕回头复用={wrapped}", flush=True)
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

    # ② 再复制 —— 复制的是【广告】，不是广告组。
    #
    # 使用者明确纠正过：这个模式要复制的是广告层级，把光标放在【广告】那一行上
    # 出现 + 号再点，操作细节和复制广告组一样。所以用 duplicate_ad_n_times
    # （它认的是左侧的 creation_1nn_sidebar_creative_node，TikTok 内部把「广告」
    # 叫 creative，和广告层的 URL .../create/spc-creative 对得上），
    # 不是 duplicate_ad_group_n_times。
    #
    # 复制完怎么在多个广告之间走：还是点右下角「继续」。商品库那条流程已经验证过
    # 同一个广告组里的多个广告就是靠「继续」跳的，最后一个没有「继续」只有「发布」。
    # 所以下面继续用 walk_and_fill_ads，它每到一站先读自己在哪一层，不数点击次数。
    #
    # 复制之前先静置几秒 —— 小游戏那边实测出来的：复制紧挨在「刚填完」后面时，
    # 页面可能还在跑自动保存/校验，左侧那一行正在重渲染，hover 上去点不到复制图标。
    if extra_copies > 0:
        page.wait_for_timeout(3000)
        print(f"      [广告层] ② 复制 {extra_copies} 个【广告】"
              f"（文案会被继承，素材是空的），共 {total_ads} 个广告要挑素材",
              flush=True)
        duplicate_ad_n_times(page, extra_copies)

    # ③ 逐个挑素材，中间用「继续」跳到同一个广告组里的下一个广告
    #
    # 这里【不能】用 step_flow.walk_and_fill_ads。那个走链器是为
    # 「广告组层 → 广告层 → 广告组层 → …」那种交替链条写的，靠【层级变化】
    # 判断有没有走动。而这个模式复制的是广告，3 个广告都在【同一个广告组】里，
    # 每一站都是广告层 —— 它分不清「跳到了下一个广告」和「压根没动」，
    # 真机上就报「点了继续但 90 秒内层级没变」，然后判定链条走完，只填了 1 个。
    #
    # 改用商品库那边验证过的写法：知道要填几个，就老老实实循环几次，
    # 不是最后一个就点「继续」+ 等广告页就绪。最后一个没有「继续」只有「全部发布」。
    filled = 0
    for k in range(total_ads):
        got = fill_ad_creatives(
            page, rec, advertiser_id, series_name, creative_usage, patient=True
        )
        if got:
            warnings.append(f"[{tag} 第{k + 1}/{total_ads}个广告] {got}")
        filled += 1

        if k < total_ads - 1:
            print(f"      [广告层] 第{k + 1}/{total_ads}个填完，点「继续」跳下一个广告",
                  flush=True)
            continue_step(page)
            wait_ad_page_ready(page)
            page.wait_for_timeout(1500)

    # 收尾截一张广告层的图。这一步默认是要真发布的，发之前能有一张
    # 「程序最后看到的样子」可以对，比只有一行日志强得多。
    try:
        from src.config import LOGS_DIR

        shot = LOGS_DIR / "episode_ad_layer.png"
        page.screenshot(path=str(shot))
        print(f"      [广告层] 收尾截图: {shot}", flush=True)
    except Exception:
        pass

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

        # 每一行 = 一个广告组。第 2 个广告组起用计划左侧的「+」新建
        # （不是复制 —— 复制的是广告层，见 _ad_count_for）。
        for i, rec in enumerate(rows):
            tag = rec["Ad Group Name"]
            if i > 0:
                print(f"      从计划里新建第 {i + 1} 个广告组…", flush=True)
                add_new_ad_group(page, campaign_name)
                wait_adgroup_page_ready(page)

            # 两个身份分开取：广告组层用 Identity_drama，广告层用 Identity_accoount
            ident_adgroup, w1 = _identity_from(
                rec, _IDENTITY_ADGROUP_COLS, "广告组层")
            ident_ad, w2 = _identity_from(rec, _IDENTITY_AD_COLS, "广告层")
            for w in (w1, w2):
                if w:
                    warnings.append(f"[{tag}] {w}")

            region_pairs, missing = resolve_regions(str(rec["Region"]).strip())
            for rid in missing:
                warnings.append(f"[{tag}] 地区ID {rid} 在对照表里找不到")
            if not region_pairs:
                raise ValueError(
                    f"[{tag}] 没有任何可用地区（TikTok 要求至少选一个地区才能继续）"
                )

            # ---- 广告组层 ----
            warnings.extend(
                fill_adgroup_core(page, rec, ident_adgroup, series_name, region_pairs)
            )

            continue_step(page)
            wait_ad_page_ready(page)

            # ---- 广告层 ----
            ad_count = _ad_count_for(rec)
            if ad_count > 1:
                print(f"      这个广告组要建 {ad_count} 个广告"
                      f"（第 2 个起用复制广告生成，每个挑不同素材）", flush=True)
            filled, total_ads = _build_row_ads(
                page, rec, advertiser_id, series_name, ident_ad,
                creative_usage, ad_count - 1, warnings,
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
