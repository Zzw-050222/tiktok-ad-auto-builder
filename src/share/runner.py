"""自动共享素材 —— 编排：一部剧一部剧地共享给指定的账号。

一次运行做的事：
    打开源账号素材库 -> 改成 100/页
    -> 对每一部剧：搜索 -> 全选 -> 共享 -> 勾目标账号 -> 确认

超过 100 条素材（一页放不下）的情况：使用者的做法是共享完当前页之后点下一个页码，
再重复一遍「全选 -> 共享」，直到没有多余的页码。share_one_drama 就是这么做的。
"""

from src.share import pages as P


def _share_current_page(page, account_names, warnings):
    """把【当前页】选中的素材共享给这些账号。返回勾上的账号名列表。"""
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
    return picked


def share_one_drama(page, drama_name, account_names, max_pages=60):
    """把一部剧的素材共享给一批账号，【翻页共享到最后一页】。

    使用者的做法：「共享完前一百条…点击右下角的下一个页码，然后回去再重复一遍
    全选然后共享的操作，直到没有多余的页码为止」。换页之后勾选会清空，
    所以每一页都要重新全选、重新在弹窗里勾一遍目标账号。

    max_pages 是个保险丝，不是业务规则：万一分页读错了导致翻不完，
    也不至于无限循环。真撞到上限会明确报出来。
    """
    warnings = []

    found = P.search_by_video_name(page, drama_name)
    if found == 0:
        return {
            "drama": drama_name,
            "found": 0,
            "pages": 0,
            "shared_to": [],
            "warnings": [f"按视频名称搜「{drama_name}」一条素材都没搜到，跳过"],
        }

    total = P.total_pages(page)
    if total and total > 1:
        print(f"      [素材库] 「{drama_name}」共 {total} 页，要一页页共享", flush=True)

    picked_all, pages_done = [], 0
    for _ in range(max_pages):
        # 安全闸：每一页动手之前确认筛选还在。
        # 筛选一旦失效，列表就是【整个素材库】，这个循环会把全库共享出去，
        # 而且很难收回。宁可停在这里让人来看。
        if not P.filter_active(page):
            raise ValueError(
                f"第 {pages_done + 1} 页上筛选条件不见了（搜索框旁边没有「清除」）。"
                "已经停下，没有共享这一页 —— 筛选失效时列表是整个素材库，"
                "继续共享会把全库共享出去。"
            )

        picked = _share_current_page(page, account_names, warnings)
        pages_done += 1
        for a in picked:
            if a not in picked_all:
                picked_all.append(a)
        print(f"      [共享] 第 {pages_done} 页已共享给 {len(picked)} 个账号", flush=True)

        if not P.go_to_next_page(page):
            break
    else:
        warnings.append(
            f"翻了 {max_pages} 页还没到最后一页，已经停下（保险丝）。"
            "剩下的页没有共享，请人工确认。"
        )

    print(f"      ✓ 「{drama_name}」{found} 条起、共 {pages_done} 页素材"
          f"已共享给 {len(picked_all)} 个账号", flush=True)
    return {
        "drama": drama_name,
        "found": found,
        "pages": pages_done,
        "shared_to": picked_all,
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
