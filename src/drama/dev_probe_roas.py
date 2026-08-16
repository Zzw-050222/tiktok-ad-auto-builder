"""挖短剧广告组页「优化和出价」区块的真实结构。

小游戏那套 set_target_roas 在这里失败：点开竞价策略后找不到「目标 ROAS」。
短剧页面多了「优化目标」「选择价值类型」等字段，结构可能不同。
这次的 JS 递归 shadow DOM（今天已经三次栽在这上面）。
"""
import traceback
from playwright.sync_api import sync_playwright
from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.pages.adgroup_page import (add_specific_episode, fill_ad_group_name,
                                          select_product_catalog, select_tiktok_mini)
from src.drama.pages.campaign_page import enable_catalog_campaign, ensure_chinese_ui
from src.pages.campaign_page import (continue_step, fill_campaign_details,
                                     select_native_growth_objective, start_new_campaign)
from src.pages.common import exit_draft, wait_until

OUT = []
def L(s=""):
    OUT.append(s); print(s, flush=True)

# 递归穿透 shadow DOM，列出「优化和出价」往下所有可见元素
JS = """
([anchor, below]) => {
  const all = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walk(el.shadowRoot);
      all.push(el);
    }
  };
  walk(document);

  let ay = null;
  for (const el of all) {
    const t = Array.from(el.childNodes).filter(n=>n.nodeType===3)
      .map(n=>n.textContent.trim()).join('').trim();
    if (t !== anchor) continue;
    const r = el.getBoundingClientRect();
    if (r.width>0 && r.height>0 && (ay===null || r.y<ay)) ay = r.y;
  }
  if (ay === null) return {ay: null, items: []};

  const items = [];
  for (const el of all) {
    const r = el.getBoundingClientRect();
    if (r.width<=0 || r.height<=0) continue;
    if (r.y < ay-30 || r.y > ay+below) continue;
    const t = Array.from(el.childNodes).filter(n=>n.nodeType===3)
      .map(n=>n.textContent.trim()).join(' ').trim();
    const a = {};
    for (const at of ['placeholder','role','data-testid','type','aria-checked']) {
      const v = el.getAttribute && el.getAttribute(at);
      if (v !== null && v !== undefined) a[at] = String(v).slice(0,44);
    }
    if (el.tagName === 'INPUT') a['.value'] = el.value;
    if (!t && !Object.keys(a).length) continue;
    items.push({tag: el.tagName.toLowerCase(), x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height), t: t.slice(0,40), a,
                cls: (el.className && el.className.toString ? el.className.toString():'').slice(0,44)});
  }
  items.sort((p,q)=>p.y-q.y);
  return {ay: Math.round(ay), items: items.slice(0, 55)};
}
"""

def dump(page, anchor, tag, below=420):
    L(f"\n{'='*72}\n{tag}  （锚点 {anchor!r}）\n{'='*72}")
    try:
        r = page.evaluate(JS, [anchor, below])
    except Exception as e:
        L(f"  出错 {e}"); return
    if r["ay"] is None:
        L(f"  ⚠ 找不到 {anchor!r}"); return
    L(f"  锚点 y={r['ay']}")
    for it in r["items"]:
        a = " ".join(f"{k}={v!r}" for k,v in it["a"].items())
        L(f"  ({it['x']:>4},{it['y']:>4}) {it['w']:>4}x{it['h']:<4} <{it['tag']}> "
          f"{it['t']!r}" + (f"  {a}" if a else "") + (f"  cls={it['cls']!r}" if it['cls'] else ""))

def main():
    adv = "7654526429006315541"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR), headless=False,
            locale=LOCALE, extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            ensure_chinese_ui(page, adv); start_new_campaign(page, adv)
            select_native_growth_objective(page); enable_catalog_campaign(page)
            fill_campaign_details(page, "DRAMAPROBE-勿用", "500"); continue_step(page)
            wait_until(page, lambda: page.get_by_text("广告组名称", exact=True).count()>0,
                       timeout_seconds=90)
            page.wait_for_timeout(1500)
            fill_ad_group_name(page, "DRAMAPROBE-ag")
            select_product_catalog(page, catalog_id=None)
            add_specific_episode(page, series_id="TIKTOKSERIES002",
                                 series_name="The Tyrant of Silvermoon")
            select_tiktok_mini(page, tt_mini_id="mnk980l0ef79v57q")
            L("前 10 步完成\n")
            page.wait_for_timeout(2500)
            page.screenshot(path=str(LOGS_DIR/"drama_roas_00.png"))

            dump(page, "优化和出价", "① 优化和出价整块", below=520)
            for a in ("竞价策略", "优化目标", "选择价值类型"):
                dump(page, a, f"② {a}", below=220)
        except Exception:
            L(traceback.format_exc())
            try: page.screenshot(path=str(LOGS_DIR/"drama_roas_ERR.png"))
            except Exception: pass
        finally:
            with open(str(LOGS_DIR/"drama_roas.txt"),"w",encoding="utf-8") as f:
                f.write("\n".join(OUT))
            try: exit_draft(page)
            except Exception: pass
            ctx.close()

main()
