"""精确挖「设置商品库推广系列」开关的【状态表示方式】。

上一版探针暴露了两个问题：
  1. 页面上有 4 个 role="switch"，用页面级选择器点到了左上角的「推广系列已启用」
     ——那个一点就会把整个推广系列停用。必须限定在 #catalog-campaign 里。
  2. 目标开关的 aria-checked 属性【不存在】，读不到当前是开还是关。而开关跟按钮
     不同：不知道状态就点，可能把本来开着的关掉。

本探针只碰 #catalog-campaign 里那一个开关，把它点击前后的完整 outerHTML 和全部
属性都打出来，用来找出「开/关」到底体现在哪里（多半在 class 上）。

会点两次（关->开->关）以便对比，最后退出草稿，不留下任何设置。

用法：
    venv/bin/python3 -m src.drama.dev_probe_toggle_state <广告主ID>
"""

import sys
import traceback

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.pages.campaign_page import ensure_chinese_ui
from src.pages.campaign_page import select_native_growth_objective, start_new_campaign
from src.pages.common import exit_draft

REPORT = []

# 只看 #catalog-campaign 这个区块里的开关，绝不用页面级 [role="switch"]
SWITCH_CSS = '#catalog-campaign [role="switch"]'


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


_DUMP_SWITCH_JS = """
() => {
  const box = document.querySelector('#catalog-campaign');
  if (!box) return {found: false};
  const sw = box.querySelector('[role="switch"]');
  if (!sw) return {found: false, boxHtml: box.outerHTML.slice(0, 600)};

  const attrsOf = (el) => {
    const o = {};
    for (const a of el.attributes || []) o[a.name] = a.value;
    return o;
  };
  // 开关本体、它的父级、以及所有子孙的 class —— 状态多半体现在其中之一
  const kids = [];
  for (const k of sw.querySelectorAll('*')) {
    kids.push({tag: k.tagName.toLowerCase(), cls: k.className && k.className.toString
                 ? k.className.toString() : '', attrs: attrsOf(k)});
  }
  return {
    found: true,
    switchTag: sw.tagName.toLowerCase(),
    switchClass: sw.className && sw.className.toString ? sw.className.toString() : '',
    switchAttrs: attrsOf(sw),
    parentClass: sw.parentElement ? (sw.parentElement.className || '').toString() : '',
    kids: kids.slice(0, 8),
    outerHTML: sw.outerHTML.slice(0, 900),
    boxHtml: box.outerHTML.replace(/\\s+/g, ' ').slice(0, 1200),
  };
}
"""


def dump_switch(page, tag):
    L(f"\n{'=' * 70}")
    L(f"{tag}")
    L("=" * 70)
    try:
        r = page.evaluate(_DUMP_SWITCH_JS)
    except Exception as e:
        L(f"  执行出错: {e}")
        return None
    if not r.get("found"):
        L("  ⚠ 没找到 #catalog-campaign 里的开关")
        if r.get("boxHtml"):
            L(f"  区块 HTML: {r['boxHtml']}")
        return None
    L(f"  开关标签   : <{r['switchTag']}>")
    L(f"  开关 class : {r['switchClass']!r}")
    L(f"  开关属性   : {r['switchAttrs']}")
    L(f"  父级 class : {r['parentClass']!r}")
    for i, k in enumerate(r["kids"]):
        L(f"  子{i} <{k['tag']}> class={k['cls']!r} attrs={k['attrs']}")
    L(f"  outerHTML  : {r['outerHTML']}")
    return r


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    advertiser_id = sys.argv[1]

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR),
            headless=False,
            locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            ensure_chinese_ui(page, advertiser_id)
            start_new_campaign(page, advertiser_id)
            select_native_growth_objective(page)
            page.wait_for_timeout(2000)

            sw = page.locator(SWITCH_CSS)
            L(f"限定选择器 {SWITCH_CSS!r} 命中 {sw.count()} 个"
              f"（应当只有 1 个；页面级 [role=switch] 有 4 个，其中一个是"
              f"「推广系列已启用」，点了会停用整个推广系列）")

            before = dump_switch(page, "状态 A —— 初始（按你说的，默认是关闭）")
            page.screenshot(path=str(LOGS_DIR / "drama_sw_A.png"))

            sw.first.scroll_into_view_if_needed(timeout=5000)
            sw.first.click(timeout=8000)
            page.wait_for_timeout(2000)
            after = dump_switch(page, "状态 B —— 点击一次之后（应当变成打开）")
            page.screenshot(path=str(LOGS_DIR / "drama_sw_B.png"))

            sw.first.click(timeout=8000)
            page.wait_for_timeout(2000)
            back = dump_switch(page, "状态 C —— 再点一次（应当变回关闭，用于确认差异可复现）")
            page.screenshot(path=str(LOGS_DIR / "drama_sw_C.png"))

            L(f"\n{'=' * 70}\n差异对比 —— 找出「开/关」体现在哪里\n{'=' * 70}")
            if before and after:
                for field in ("switchClass", "parentClass"):
                    a, b = before.get(field), after.get(field)
                    L(f"  {field}: A={a!r}")
                    L(f"  {' ' * len(field)}  B={b!r}   {'← 有变化' if a != b else '（无变化）'}")
                ka = {k: v for k, v in before.get("switchAttrs", {}).items()}
                kb = {k: v for k, v in after.get("switchAttrs", {}).items()}
                diff = {k: (ka.get(k), kb.get(k)) for k in set(ka) | set(kb)
                        if ka.get(k) != kb.get(k)}
                L(f"  开关属性差异: {diff if diff else '无'}")
                for i in range(min(len(before.get('kids', [])), len(after.get('kids', [])))):
                    ca = before['kids'][i]['cls']
                    cb = after['kids'][i]['cls']
                    if ca != cb:
                        L(f"  子{i} class 有变化: {ca!r} -> {cb!r}")
            if before and back:
                same = before.get("switchClass") == back.get("switchClass")
                L(f"  A 与 C 的 switchClass 是否相同: {same}"
                  f"{'  ✓ 说明这个字段确实表示状态' if same else '  ⚠ 不一致，得再找别的字段'}")

        except Exception:
            L("\n出错:")
            L(traceback.format_exc())
            try:
                page.screenshot(path=str(LOGS_DIR / "drama_sw_ERROR.png"))
            except Exception:
                pass
        finally:
            with open(str(LOGS_DIR / "drama_toggle_state.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_toggle_state.txt'}")
            try:
                exit_draft(page)
            except Exception:
                pass
            context.close()


if __name__ == "__main__":
    main()
