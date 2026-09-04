"""自动共享素材 —— 编排：一部剧一部剧地共享给指定的账号。

一次运行做的事：
    打开源账号素材库 -> 改成 100/页
    -> 对每一部剧：搜索 -> 全选 -> 共享 -> 勾目标账号 -> 确认

超过 100 条素材的情况，使用者说解决办法在后面（还没给）。
现在的行为是【明确说出来】：筛出多少条、这一轮只共享了当前页的多少条。
接口留在 share_one_drama 的返回值里，补的时候在那里加翻页就行。
"""

from src.share import pages as P


def share_one_drama(page, drama_name, account_names):
    """把一部剧的素材共享给一批账号。返回 {"drama","found","shared_to","warnings"}。"""
    warnings = []

    found = P.search_by_video_name(page, drama_name)
    if found == 0:
        return {
            "drama": drama_name,
            "found": 0,
            "shared_to": [],
            "warnings": [f"按视频名称搜「{drama_name}」一条素材都没搜到，跳过"],
        }

    # 全选只选【当前页】。100/页 的情况下，超过 100 条就有剩下的没共享到。
    # 使用者说这个情况的处理办法在后面 —— 先如实报出来，不假装全共享了。
    if found >= 100:
        warnings.append(
            f"「{drama_name}」筛出 {found} 条（已经到当前页上限 100），"
            "本轮只共享了当前页这一批，后面还有没共享到的。"
            "翻页共享的做法使用者还没给，补上之后这里要改。"
        )

    P.select_all_on_page(page)
    P.open_share_modal(page)

    if not P.scroll_modal_to_account_section(page):
        raise ValueError(
            "在「共享视频」弹窗里滚到底也没看到「与选定的广告账号共享」那一块"
        )

    picked, warn = P.add_target_accounts(page, account_names)
    warnings.extend(warn)
    if not picked:
        raise ValueError(
            f"一个目标账号都没勾上（要共享给：{list(account_names)}），"
            "没有点确认，什么都没共享出去"
        )

    P.collapse_account_dropdown(page)
    P.confirm_share(page)

    print(f"      ✓ 「{drama_name}」{found} 条素材已共享给 {len(picked)} 个账号",
          flush=True)
    return {
        "drama": drama_name,
        "found": found,
        "shared_to": picked,
        "warnings": warnings,
    }


def share_materials(page, source_advertiser_id, drama_names, account_names,
                    on_progress=None):
    """一次运行：一个源账号 -> 多部剧 -> 多个目标账号。

    返回每部剧一条的结果列表。某一部剧失败不影响后面的 —— 共享是幂等的
    （同一个素材共享两次没有坏处），所以单条失败就记下来继续走。
    """
    from src.share.config import CREATIVE_LIBRARY_URL

    url = CREATIVE_LIBRARY_URL.format(str(source_advertiser_id).strip())
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(3000)

    if not P.set_page_size_100(page):
        print("      [素材库] 没能把每页条数改成 100，继续按当前页数跑", flush=True)

    results = []
    for i, drama in enumerate(drama_names, 1):
        if on_progress:
            on_progress(i, len(drama_names), drama)
        print(f"    === [{i}/{len(drama_names)}] {drama} ===", flush=True)
        try:
            results.append(share_one_drama(page, drama, account_names))
        except Exception as e:
            results.append({
                "drama": drama,
                "found": None,
                "shared_to": [],
                "warnings": [],
                "error": f"{type(e).__name__}: {e}",
            })
            print(f"      ✗ 失败: {type(e).__name__}: {str(e).splitlines()[0][:160]}",
                  flush=True)
            # 下一部剧要从干净的列表开始：弹窗可能还开着，先关掉
            try:
                if P.share_modal_open(page):
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(1000)
            except Exception:
                pass
    return results
