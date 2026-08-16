"""一次挖完剩下三步的结构：选择 TikTok Mini、目标 ROAS、地域。

已知这个广告组页上【两套组件库并存】：
  * ks-*  用在主表单（商品库下拉、TikTok Mini 都是这套）
  * vi-*  用在弹层内（搜索维度、可用性筛选、分页）
所以不能把一套的规律套到另一套上。这次把三处的真实结构一次性 dump 出来。
"""
import sys, traceback
from playwright.sync_api import sync_playwright
from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.pages.adgroup_page import (add_specific_episode, fill_ad_group_name,
                                          select_product_catalog)
from src.drama.pages.campaign_page import enable_catalog_campaign, ensure_chinese_ui
from src.pages.campaign_page import (continue_step, fill_campaign_details,
                                     select_native_growth_objective, start_new_campaign)
from src.pages.common import exit_draft, wait_until

OUT = []
def L(s=""):
    OUT.append(s); print(s, flush=True)

# 以一段文字为锚，dump 附近所有渲染出来的元素（含 placeholder / value / 全部属性）
JS = """
([anchor, below, above]) => {
  let ay = null;
  for (const el of document.querySelectorAll('*')) {
    const own = Array.from(el.childNodes).filter(n=>n.nodeType===3)
      .map(n=>n.textContent.trim()).join('').trim();
    const ph = el.getAttribute ? (el.getAttribute('placeholder')||'') : '';
    if (own === anchor || ph === anchor) {
      const r = el.getBoundingClientRect();
      if (r.width>0 && r.height>0 && (ay===null || r.y<ay)) ay = r.y;
    }
  }
  if (ay === null) return {ay: null, items: []};
  const items = [];
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width<=0 || r.height<=0) continue;
    if (r.y < ay-above || r.y > ay+below) continue;
    const own = Array.from(el.childNodes).filter(n=>n.nodeType===3)
      .map(n=>n.textContent.trim()).join(' ').trim();
    const a = {};
    for (const at of ['placeholder','value','role','data-testid','type','readonly','id']) {
      const v = el.getAttribute && el.getAttribute(at);
      if (v !== null && v !== undefined) a[at] = String(v).slice(0,50);
    }
    if (el.tagName === 'INPUT') a['.value'] = el.value;
    if (!own && !Object.keys(a).length) continue;
    items.push({tag: el.tagName.toLowerCase(), x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height), text: own.slice(0,44),
                a, cls: (el.className && el.className.toString ? el.className.toString():'').slice(0,50)});
  }
  items.sort((p,q)=>p.y-q.y);
  return {ay: Math.round(ay), items: items.slice(0, 40)};
}
"""

def dump(page, anchor, tag, below=260, above=40):
    L(f"\n{'='*72}\n{tag}  （锚点 {anchor!r}）\n{'='*72}")
    try:
        r = page.evaluate(JS, [anchor, below, above])
    except Exception as e:
        L(f"  出错 {e}"); return
    if r["ay"] is None:
        L(f"  ⚠ 找不到 {anchor!r}"); return
    L(f"  锚点 y={r['ay']}")
    for it in r["items"]:
        a = " ".join(f"{k}={v!r}" for k,v in it["a"].items())
        L(f"  ({it['x']:>4},{it['y']:>4}) {it['w']:>4}x{it['h']:<4} <{it['tag']}> "
          f"{it['text']!r}" + (f"  {a}" if a else "") + (f"  cls={it['cls']!r}" if it['cls'] else ""))

def main():
    adv = "7654526429006315541"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR), headless=False,
            locale=LOCALE, extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            ensure_chinese_ui(page, adv)
            start_new_campaign(page, adv)
            select_native_growth_objective(page)
            enable_catalog_campaign(page)
            fill_campaign_details(page, "DRAMAPROBE-勿用", "500")
            continue_step(page)
            wait_until(page, lambda: page.get_by_text("广告组名称", exact=True).count()>0,
                       timeout_seconds=90)
            page.wait_for_timeout(1500)
            fill_ad_group_name(page, "DRAMAPROBE-ag")
            select_product_catalog(page, catalog_id=None)
            add_specific_episode(page, series_id="TIKTOKSERIES002",
                                 series_name="The Tyrant of Silvermoon")
            L("前 9 步完成，开始 dump 剩下三处\n")
            page.wait_for_timeout(2000)
            page.screenshot(path=str(LOGS_DIR/"drama_rest_00.png"))

            dump(page, "选择 TikTok Mini", "① 选择 TikTok Mini 控件")
            dump(page, "短剧", "②「短剧」区块", below=200)
            dump(page, "优化和出价", "③ 优化和出价 / ROAS", below=360)
            dump(page, "地域", "④ 地域", below=260)
        except Exception:
            L(traceback.format_exc())
            try: page.screenshot(path=str(LOGS_DIR/"drama_rest_ERROR.png"))
            except Exception: pass
        finally:
            with open(str(LOGS_DIR/"drama_rest.txt"),"w",encoding="utf-8") as f:
                f.write("\n".join(OUT))
            try: exit_draft(page)
            except Exception: pass
            ctx.close()

main()
