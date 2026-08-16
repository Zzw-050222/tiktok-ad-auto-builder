"""把弹层里每个 div.vi-select 的 input 的 value / placeholder / outerHTML 打出来。
不再猜「短剧名称」是 value 还是 placeholder 还是别的什么。"""
import sys, traceback
from playwright.sync_api import sync_playwright
from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.dev_probe_episode_select import open_dialog

OUT = []
def L(s=""):
    OUT.append(s); print(s, flush=True)

JS = """
() => {
  const out = [];
  for (const sel of document.querySelectorAll('div.vi-select')) {
    const r = sel.getBoundingClientRect();
    const inp = sel.querySelector('input');
    out.push({
      pos: `(${Math.round(r.x)},${Math.round(r.y)}) ${Math.round(r.w||r.width)}x${Math.round(r.height)}`,
      visible: r.width > 0 && r.height > 0,
      selCls: (sel.className||'').toString().slice(0,60),
      inputTag: inp ? inp.tagName.toLowerCase() : null,
      inputCls: inp ? (inp.className||'').toString().slice(0,50) : null,
      value: inp ? inp.value : null,
      placeholder: inp ? inp.getAttribute('placeholder') : null,
      readonly: inp ? inp.hasAttribute('readonly') : null,
      selText: (sel.innerText||'').trim().slice(0,40),
      html: sel.outerHTML.replace(/\\s+/g,' ').slice(0, 320),
    });
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
            for i, s in enumerate(page.evaluate(JS)):
                L(f"\n--- vi-select[{i}] {s['pos']} 可见={s['visible']} ---")
                L(f"  容器 cls : {s['selCls']!r}")
                L(f"  innerText: {s['selText']!r}")
                L(f"  input    : <{s['inputTag']}> cls={s['inputCls']!r} readonly={s['readonly']}")
                L(f"  value    : {s['value']!r}")
                L(f"  placeholder: {s['placeholder']!r}")
                L(f"  html     : {s['html']}")
        except Exception:
            L(traceback.format_exc())
        finally:
            with open(str(LOGS_DIR/"drama_dim3.txt"),"w",encoding="utf-8") as f:
                f.write("\n".join(OUT))
            ctx.close()

main()
