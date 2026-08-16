"""挖「短剧名称 ∨」这个搜索维度下拉的真实结构。

已经失败过两种写法，都是点那段文字：
  ① 取「第一个可见的『短剧名称』」-> 点到了表格列头，没反应
  ② 把所有可见的『短剧名称』都试一遍 -> 仍然展不开
说明【点文字本身展不开这个下拉】，要点的是它的容器或那个箭头。所以这次不猜，
用 elementFromPoint 取那个位置上真正的元素，再把整条祖先链的属性打出来。

用法：
    venv/bin/python3 -m src.drama.dev_probe_dim_dropdown <广告主ID>
"""

import sys
import traceback

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.dev_probe_episode_select import open_dialog

REPORT = []


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


# 先找到弹层里那个写着「短剧名称」的筛选下拉（不是表格列头），
# 再把它自己和整条祖先链的标签/属性打出来。
_DUMP_JS = """
() => {
  // 收集所有文字恰好是「短剧名称」的可见元素，带位置
  const hits = [];
  for (const el of document.querySelectorAll('*')) {
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
      .map(n => n.textContent.trim()).join('').trim();
    if (own !== '短剧名称') continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    hits.push({el, x: Math.round(r.x), y: Math.round(r.y),
               w: Math.round(r.width), h: Math.round(r.height)});
  }

  const describe = (el) => {
    const attrs = {};
    for (const a of el.attributes || []) attrs[a.name] = (a.value || '').slice(0, 60);
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      cls: (el.className && el.className.toString ? el.className.toString() : '').slice(0, 70),
      attrs,
      x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height),
    };
  };

  const out = [];
  for (const h of hits) {
    const chain = [];
    let n = h.el;
    for (let k = 0; k < 6 && n; k++) {
      chain.push(describe(n));
      n = n.parentElement;
    }
    // 这一支里有没有 chevron / 箭头图标
    let arrow = null;
    let p = h.el.parentElement;
    for (let k = 0; k < 4 && p; k++) {
      const a = p.querySelector('[class*="arrow"], [class*="chevron"], svg, ks-icon-chevron-down');
      if (a) { arrow = describe(a); break; }
      p = p.parentElement;
    }
    out.push({pos: `(${h.x},${h.y}) ${h.w}x${h.h}`, chain, arrow});
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
            L(f"打开弹层: {open_dialog(page, adv)}")
            page.wait_for_timeout(2000)

            L(f"\n{'=' * 72}\n所有可见的「短剧名称」及其祖先链\n{'=' * 72}")
            res = page.evaluate(_DUMP_JS)
            for i, item in enumerate(res):
                L(f"\n--- 第 {i} 个  位置 {item['pos']} ---")
                for d, node in enumerate(item["chain"]):
                    a = " ".join(f"{k}={v!r}" for k, v in node["attrs"].items()
                                 if k in ("role", "data-testid", "aria-expanded",
                                          "id", "tabindex", "aria-haspopup"))
                    L(f"  祖先{d}: <{node['tag']}> ({node['x']},{node['y']}) "
                      f"{node['w']}x{node['h']} cls={node['cls']!r}" + (f"  {a}" if a else ""))
                if item["arrow"]:
                    ar = item["arrow"]
                    L(f"  箭头图标: <{ar['tag']}> ({ar['x']},{ar['y']}) "
                      f"{ar['w']}x{ar['h']} cls={ar['cls']!r}")
                else:
                    L("  箭头图标: 无 —— 这一个多半是表格列头，不是下拉")

            # 对每个候选，试着点它的各级祖先，看哪一层能展开出「短剧ID」
            L(f"\n{'=' * 72}\n逐层点击测试：哪一层能展开出「短剧ID」\n{'=' * 72}")
            for i, item in enumerate(res):
                if not item["arrow"]:
                    L(f"  第 {i} 个（无箭头，跳过）")
                    continue
                for depth in range(4):
                    try:
                        page.evaluate(
                            """([idx, d]) => {
                              const hits = [];
                              for (const el of document.querySelectorAll('*')) {
                                const own = Array.from(el.childNodes).filter(n=>n.nodeType===3)
                                  .map(n=>n.textContent.trim()).join('').trim();
                                if (own !== '短剧名称') continue;
                                const r = el.getBoundingClientRect();
                                if (r.width <= 0 || r.height <= 0) continue;
                                hits.push(el);
                              }
                              let n = hits[idx];
                              for (let k = 0; k < d && n; k++) n = n.parentElement;
                              if (n) n.click();
                            }""", [i, depth])
                        page.wait_for_timeout(1500)
                        opened = page.get_by_text("短剧ID", exact=True)
                        vis = any(opened.nth(j).is_visible()
                                  for j in range(min(opened.count(), 5)))
                        L(f"  第 {i} 个 · 祖先{depth} 点击后「短剧ID」可见 = {vis}"
                          + ("   ★ 就是这一层" if vis else ""))
                        if vis:
                            page.screenshot(path=str(LOGS_DIR / "drama_dim_opened.png"))
                            raise SystemExit(0)
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(600)
                    except SystemExit:
                        raise
                    except Exception as e:
                        L(f"  第 {i} 个 · 祖先{depth} 点击出错: {str(e)[:60]}")

        except SystemExit:
            L("\n找到可展开的那一层，见上面标 ★ 的行")
        except Exception:
            L("\n出错:")
            L(traceback.format_exc())
            try:
                page.screenshot(path=str(LOGS_DIR / "drama_dim_ERROR.png"))
            except Exception:
                pass
        finally:
            with open(str(LOGS_DIR / "drama_dim_dropdown.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_dim_dropdown.txt'}")
            context.close()


if __name__ == "__main__":
    main()
