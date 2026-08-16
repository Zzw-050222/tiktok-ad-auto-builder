"""用坐标直接取筛选下拉那个位置上的元素，看它到底是什么。"""
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
  const res = {selects: [], atPoints: []};
  // ① 所有 <select> 及其选项
  for (const s of document.querySelectorAll('select')) {
    const r = s.getBoundingClientRect();
    res.selects.push({
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      cls: (s.className||'').toString().slice(0,50),
      options: Array.from(s.options).map(o => `${o.value}=${o.text}`).slice(0, 10),
    });
  }
  // ② 弹层筛选行那一带，逐点取元素
  const describe = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const attrs = {};
    for (const a of el.attributes || []) attrs[a.name] = (a.value||'').slice(0,50);
    return {tag: el.tagName.toLowerCase(),
            cls: (el.className && el.className.toString ? el.className.toString() : '').slice(0,60),
            text: (el.innerText||'').trim().slice(0,30),
            attrs, x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height)};
  };
  for (const y of [185, 190, 195]) {
    for (const x of [860, 880, 900, 940, 955]) {
      const el = document.elementFromPoint(x, y);
      if (!el) continue;
      const chain = [];
      let n = el;
      for (let k = 0; k < 4 && n; k++) { chain.push(describe(n)); n = n.parentElement; }
      res.atPoints.push({at: `(${x},${y})`, chain});
    }
  }
  return res;
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
            page.wait_for_timeout(2000)
            r = page.evaluate(JS)
            L(f"\n=== <select> 元素 {len(r['selects'])} 个 ===")
            for s in r["selects"]:
                L(f"  ({s['x']},{s['y']}) {s['w']}x{s['h']} cls={s['cls']!r}")
                L(f"     选项: {s['options']}")
            L(f"\n=== 筛选行坐标处的元素 ===")
            seen = set()
            for ap in r["atPoints"]:
                top = ap["chain"][0]
                key = (top["tag"], top["cls"], top["x"], top["y"])
                if key in seen: continue
                seen.add(key)
                L(f"\n  {ap['at']}:")
                for d, n in enumerate(ap["chain"]):
                    a = " ".join(f"{k}={v!r}" for k,v in n["attrs"].items()
                                 if k in ("role","data-testid","aria-expanded","aria-haspopup","id"))
                    L(f"    祖先{d} <{n['tag']}> ({n['x']},{n['y']}) {n['w']}x{n['h']} "
                      f"text={n['text']!r} cls={n['cls']!r}" + (f" {a}" if a else ""))
            page.screenshot(path=str(LOGS_DIR/"drama_dim2.png"))
        except Exception:
            L(traceback.format_exc())
        finally:
            with open(str(LOGS_DIR/"drama_dim2.txt"),"w",encoding="utf-8") as f:
                f.write("\n".join(OUT))
            ctx.close()

main()
