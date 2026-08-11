import openpyxl

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Sheet1"

headers = [
    "Campaign Name",
    "Budget",
    "Advertiser ID",
    "Ad Group Name",
    "TT Mini ID",
    "roas_bid",
    "TT Mini URL",
    "Region",
    "Mini Game Name",
    "ads_text",
    "Identity_ID",
    "Business Center Account ID",
    "optimization_event",
    "Ad Group Name Number",
]
ws.append(headers)

ws.append(
    [
        "Demo-Puzzle Game-0101-1",
        50,
        "1234567890123456789",
        "Demo-Puzzle Game-0101-1-1",
        "mgabc123demo0001",
        1,
        "https://www.tiktok.com/minis/demoAbc123",
        "6252001,1861060",
        "Demo Puzzle Game",
        "play now",
        "00000000-0000-0000-0000-000000000001",
        "",
        "",
        0,
    ]
)
ws.append(
    [
        "Demo-Puzzle Game-0101-1",
        50,
        "1234567890123456789",
        "Demo-Puzzle Game-0101-2",
        "mgabc123demo0002",
        1.2,
        "https://www.tiktok.com/minis/demoXyz789",
        "6252001,1861060,1605651,1733045,298795,3469034,1694008,1643084",
        "Demo Match-3 Game",
        "download now",
        "00000000-0000-0000-0000-000000000001",
        "",
        "",
        2,
    ]
)

wb.save("examples/sample_campaign_template.xlsx")

wb2 = openpyxl.Workbook()
ws2 = wb2.active
ws2.title = "Sheet1"
ws2.append(["TIKTOK-NAME", "Identity_ID"])
ws2.append(["@demo_creator_01", "00000000-0000-0000-0000-000000000001"])
ws2.append(["Demo Business Account", "00000000-0000-0000-0000-000000000002"])
wb2.save("examples/sample_identity_id.xlsx")

print("done")
