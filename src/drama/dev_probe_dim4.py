"""点开搜索维度下拉，看展开后的选项到底长什么样、在哪里。

已确认：下拉是 div.vi-select[0]，其 input.vi-input__inner 的 value='短剧名称'、
readonly。定位没问题，问题在点开之后找不到「短剧ID」选项。
"""
import sys, traceback
from playwright.sync_api import sync_playwright
from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.dev_probe_episode_select import open_dialog

OUT = []
def L(s=""):
    OUT.append(s); print(s, flush=True)

DUMP = """
() => {
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const own = Array.from(el.childNodes).filter(n=>n.nodeType===3)
      .map(n=>n.textContent.trim()).join('').trim();
    if (!own || own.length > 20) continue;
    out.push({t: own, x: Math.round(r.x), y: Math.round(r.y),
              tag: el.tagName.toLowerCase(),
              cls: (el.className && el.className.toString ? el.className.toString():'').slice(0,44)});
  }
  return out;
}
"""

def main():
    adv = sys.argv[1]
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR), headless=False,
            locale=LOCALE, extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            L(f"打开弹层: {open_dialog(page, adv)}")
            page.wait_for_timeout(2500)

            sel = page.locator("div.vi-select").first
            inp = sel.locator("input.vi-input__inner").first
            L(f"点击前 value = {inp.input_value()!r}")

            before = {(o['t'], o['x'], o['y']) for o in page.evaluate(DUMP)}
            inp.click(timeout=8000)
            page.wait_for_timeout(2500)
            page.screenshot(path=str(LOGS_DIR/"drama_dim4_opened.png"))

            after = page.evaluate(DUMP)
            new = [o for o in after if (o['t'], o['x'], o['y']) not in before]
            L(f"\n=== 点开后【新出现】的元素 {len(new)} 个 ===")
            for o in new[:40]:
                L(f"  ({o['x']:>4},{o['y']:>4}) <{o['tag']}> {o['t']!r} cls={o['cls']!r}")

            L(f"\n=== 页面上含「短剧」或「ID」的文字 ===")
            for o in after:
                if "短剧" in o['t'] or o['t'].upper().endswith("ID"):
                    L(f"  ({o['x']:>4},{o['y']:>4}) <{o['tag']}> {o['t']!r} cls={o['cls']!r}")

            L(f"\n点击后 value = {inp.input_value()!r}")
        except Exception:
            L(traceback.format_exc())
        finally:
            with open(str(LOGS_DIR/"drama_dim4.txt"),"w",encoding="utf-8") as f:
                f.write("\n".join(OUT))
            ctx.close()

main()
