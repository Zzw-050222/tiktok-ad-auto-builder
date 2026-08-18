"""探商品库下拉里那一项到底该点哪个元素。

背景：换了广告主之后，程序能找到框、能展开下拉、能按文字认出商品库，
但点下去不生效（占位文字「请选择商品库」仍在）。说明 _option_row_of 的启发式
（往上找 宽>200 高30~140 的祖先）在这个账号的下拉上抓错了层。

前两版定位都是猜的，都错了：
  ① text=/ID[:：]\\s*\\d{10,}/ —— 照旧账号写死，新账号的商品库不显示 ID
  ② role="option" —— 这个下拉不用标准 option 角色
所以这次不猜，把商品库名字那段文字的【整条祖先链】连同属性和尺寸打出来，
再逐层试点，看哪一层点下去占位文字会消失。

用法：
    venv/bin/python3 -m src.drama.dev_probe_catalog_option <广告主ID>
"""

import sys
import traceback

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.pages.adgroup_page import CATALOG_PLACEHOLDER, _first_visible
from src.drama.pages.campaign_page import enable_catalog_campaign, ensure_chinese_ui
from src.pages.adgroup_page import wait_adgroup_page_ready
from src.pages.campaign_page import (
    continue_step,
    fill_campaign_details,
    select_native_growth_objective,
    start_new_campaign,
)
from src.pages.common import click_to_open, exit_draft, wait_until

REPORT = []


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


# 把一个元素的整条祖先链连同属性、尺寸、能否点击打出来
_CHAIN_JS = """
el => {
  const out = [];
  let n = el;
  for (let k = 0; k < 9 && n; k++) {
    const r = n.getBoundingClientRect();
    const attrs = {};
    for (const a of n.attributes || []) {
      if (/testid|role|class|aria|id|tabindex/i.test(a.name)) {
        attrs[a.name] = (a.value || '').slice(0, 70);
      }
    }
    const st = getComputedStyle(n);
    out.push({
      depth: k,
      tag: n.tagName.toLowerCase(),
      attrs: attrs,
      x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height),
      pointerEvents: st.pointerEvents,
      cursor: st.cursor,
      // 这一层里有没有勾选控件（有的话多半要点它）
      hasBox: !!n.querySelector('input[type=checkbox], input[type=radio], [role=checkbox], [role=radio]'),
    });
    n = n.parentElement;
  }
  return out;
}
"""


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    adv = sys.argv[1]

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR),
            headless=False, locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            L(f"广告主: {adv}")
            ensure_chinese_ui(page, adv)
            start_new_campaign(page, adv)
            select_native_growth_objective(page)
            enable_catalog_campaign(page)
            fill_campaign_details(page, f"PROBE-catalog-{adv[-4:]}", 20)
            continue_step(page)
            wait_adgroup_page_ready(page)
            page.wait_for_timeout(2000)
            L("已到广告组页")

            trigger = wait_until(
                page,
                lambda: _first_visible(page.get_by_text(CATALOG_PLACEHOLDER, exact=True)),
                timeout_seconds=60,
            )
            if not trigger:
                L("✗ 没看到「请选择商品库」占位文字")
                return
            trigger.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(500)

            # 锚定【占位文字本身】往上 dump——上一版探针锚错了元素（拿页头的
            # 广告主账号名当商品库），教训是：锚点必须是这一步真正相关的那段文字。
            L(f"\n{'=' * 72}\n占位文字「{CATALOG_PLACEHOLDER}」的祖先链\n{'=' * 72}")
            for node in trigger.evaluate(_CHAIN_JS):
                a = " ".join(f"{k}={v!r}" for k, v in node["attrs"].items())
                L(f"  祖先{node['depth']}: <{node['tag']}> ({node['x']},{node['y']}) "
                  f"{node['w']}x{node['h']} pe={node['pointerEvents']} "
                  f"cursor={node['cursor']}")
                if a:
                    L(f"           {a}")

            # 这个选择器是不是禁用状态
            state = trigger.evaluate("""el => {
              let n = el;
              for (let k = 0; k < 8 && n; k++) {
                const cls = (n.className && n.className.toString) ? n.className.toString() : '';
                if (/select|input/i.test(cls) || n.getAttribute('data-testid')) {
                  return {
                    tag: n.tagName.toLowerCase(),
                    cls: cls.slice(0, 90),
                    testid: n.getAttribute('data-testid'),
                    ariaDisabled: n.getAttribute('aria-disabled'),
                    disabled: n.hasAttribute('disabled'),
                    hasDisabledClass: /disabled|is-disabled/i.test(cls),
                    pe: getComputedStyle(n).pointerEvents,
                    opacity: getComputedStyle(n).opacity,
                  };
                }
                n = n.parentElement;
              }
              return null;
            }""")
            L(f"\n选择器控件状态: {state}")

            # 用真实鼠标点它的中心（而不是 Playwright 的元素点击），看会不会展开
            before = set(page.evaluate("""() => {
              const out = [];
              for (const el of document.querySelectorAll('*')) {
                const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
                  .map(n => n.textContent.trim()).join('').trim();
                if (!own || own.length > 100) continue;
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) out.push(own);
              }
              return out;
            }"""))
            box = trigger.bounding_box()
            L(f"\n占位文字的盒子: {box}")
            if box:
                page.mouse.click(box["x"] + box["width"] / 2,
                                 box["y"] + box["height"] / 2)
                page.wait_for_timeout(3000)
                after = page.evaluate("""() => {
                  const out = [];
                  for (const el of document.querySelectorAll('*')) {
                    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
                      .map(n => n.textContent.trim()).join('').trim();
                    if (!own || own.length > 100) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) out.push(own);
                  }
                  return out;
                }""")
                newly = [x for x in after if x not in before]
                L(f"真实鼠标点中心后，新出现的文字: {newly[:20] or '（空——还是没展开）'}")
                page.screenshot(path=str(LOGS_DIR / "drama_catalog_open.png"))

        except Exception:
            L("\n出错:")
            L(traceback.format_exc())
            try:
                page.screenshot(path=str(LOGS_DIR / "drama_catalog_ERROR.png"))
            except Exception:
                pass
        finally:
            with open(str(LOGS_DIR / "drama_catalog_probe.txt"), "w",
                      encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_catalog_probe.txt'}")
            try:
                exit_draft(page)
            except Exception:
                pass
            context.close()


if __name__ == "__main__":
    main()
