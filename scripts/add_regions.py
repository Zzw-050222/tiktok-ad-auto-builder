import openpyxl

PATH = "REGION.xlsx"

NEW_REGIONS = [
    (2635167, "英国"),
    (2921044, "德国"),
    (3017382, "法国"),
    (3175395, "意大利"),
    (2510769, "西班牙"),
    (2017370, "俄罗斯"),
    (660013, "芬兰"),
    (2661886, "瑞典"),
    (3996063, "墨西哥"),
    (798544, "波兰"),
    (3865483, "阿根廷"),
    (6251999, "加拿大"),
    (357994, "埃及"),
    (2750405, "荷兰"),
    (2077456, "澳大利亚"),
    (3686110, "哥伦比亚"),
    (102358, "沙特阿拉伯"),
    (290557, "阿联酋"),
    (953987, "南非"),
    (2589581, "阿尔及利亚"),
    (2542007, "摩洛哥"),
    (285570, "科威特"),
    (1562822, "越南"),
    (1835841, "韩国"),
    (1668284, "中国台湾地区"),
    (1819730, "中国香港"),
    (1821275, "中国澳门"),
    (1831722, "柬埔寨"),
    (1880251, "新加坡"),
    (1168579, "巴基斯坦"),
    (163843, "叙利亚"),
    (3573345, "百慕大"),
    (3580718, "开曼群岛"),
    (3424932, "圣皮埃尔和密克隆"),
    (3425505, "格陵兰"),
    (3573591, "特立尼达和多巴哥"),
]

wb = openpyxl.load_workbook(PATH)
ws = wb.active

existing_ids = {row[0] for row in ws.iter_rows(min_row=2, values_only=True)}

added = []
skipped = []
for region_id, name in NEW_REGIONS:
    if region_id in existing_ids:
        skipped.append((region_id, name))
        continue
    ws.append([region_id, name])
    added.append((region_id, name))

wb.save(PATH)

print(f"added={len(added)}")
for r in added:
    print(r)
print(f"skipped_already_present={len(skipped)}")
for r in skipped:
    print(r)
