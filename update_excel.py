#!/usr/bin/env python3
"""
update_excel.py  ·  实时更新 Excel 数据库
--------------------------------------------
每次运行时，从 API-Football 拉取本届（2026）所有已完成的比赛，
检查哪些是 Excel 里没有的（通过编号去重），自动追加到 Excel。

用法：
  fetch_worldcup.py 每小时跑一次 -> 生成 predictions.json
  update_excel.py   在 fetch 之后手动或定时运行 -> 自动追加新比赛到 Excel
"""
import os, sys, json, unicodedata, datetime
import pandas as pd
import requests

API_KEY = os.environ.get("APISPORTS_KEY", "").strip()
EXCEL = os.environ.get("WC_EXCEL", "wc_data.xlsx")
SHEET = os.environ.get("WC_SHEET", "2006-2026")
BASE = "https://v3.football.api-sports.io"
LEAGUE = 1
SEASON = 2026
HEADERS = {"x-apisports-key": API_KEY}

ALIASES = {
 "mexico":"MEX","southafrica":"RSA","southkorea":"KOR","korearepublic":"KOR","korea":"KOR",
 "czechrepublic":"CZE","czechia":"CZE","czechoslovakia":"CZE","canada":"CAN",
 "bosniaandherzegovina":"BIH","bosnia":"BIH","qatar":"QAT","switzerland":"SUI",
 "brazil":"BRA","morocco":"MAR","haiti":"HAI","scotland":"SCO","usa":"USA","unitedstates":"USA",
 "paraguay":"PAR","australia":"AUS","turkey":"TUR","turkiye":"TUR","germany":"GER","westgermany":"GER",
 "curacao":"CUW","ivorycoast":"CIV","cotedivoire":"CIV","ecuador":"ECU","netherlands":"NED",
 "japan":"JPN","sweden":"SWE","tunisia":"TUN","belgium":"BEL","egypt":"EGY","iran":"IRN","iriran":"IRN",
 "newzealand":"NZL","spain":"ESP","capeverde":"CPV","capeverdeislands":"CPV","saudiarabia":"KSA",
 "uruguay":"URU","france":"FRA","senegal":"SEN","iraq":"IRQ","norway":"NOR","argentina":"ARG",
 "algeria":"ALG","austria":"AUT","jordan":"JOR","portugal":"POR","drcongo":"COD","congodr":"COD",
 "zaire":"COD","uzbekistan":"UZB","colombia":"COL","england":"ENG","croatia":"CRO","ghana":"GHA","panama":"PAN",
}
CN_NAMES = {
 "德国":"GER","英格兰":"ENG","法国":"FRA","西班牙":"ESP","葡萄牙":"POR",
 "荷兰":"NED","比利时":"BEL","瑞士":"SUI","奥地利":"AUT","波黑":"BIH",
 "瑞典":"SWE","克罗地亚":"CRO","挪威":"NOR","苏格兰":"SCO","捷克":"CZE",
 "巴西":"BRA","阿根廷":"ARG","乌拉圭":"URU","哥伦比亚":"COL","巴拉圭":"PAR",
 "墨西哥":"MEX","美国":"USA","加拿大":"CAN","巴拿马":"PAN",
 "日本":"JPN","韩国":"KOR","澳大利亚":"AUS","伊朗":"IRN",
 "沙特阿拉伯":"KSA","伊拉克":"IRQ","约旦":"JOR","乌兹别克斯坦":"UZB",
 "摩洛哥":"MAR","突尼斯":"TUN","埃及":"EGY","塞内加尔":"SEN","南非":"RSA","科特迪瓦":"CIV","加纳":"GHA",
 "厄瓜多尔":"ECU","海地":"HAI","新西兰":"NZL",
 "卡塔尔":"QAT","库拉索":"CUW","佛得角":"CPV","刚果民主共和国":"COD","阿尔及利亚":"ALG",
}
def norm(s):
    s=unicodedata.normalize("NFKD",s or ""); s="".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())
def code_of(n):
    n_str = str(n).strip() if n else ""
    if n_str in CN_NAMES:
        return CN_NAMES[n_str]
    return ALIASES.get(norm(n_str))

def api_get(path, params):
    r = requests.get(f"{BASE}/{path}", headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("errors"):
        print(f"[warn] /{path}: {d['errors']}", file=sys.stderr)
    return d.get("response", [])

def load_excel():
    """Load existing Excel, return fixture IDs and DataFrame."""
    try:
        df = pd.read_excel(EXCEL, sheet_name=SHEET, header=2)
        existing_ids = set(df["编号"].dropna().astype(int).tolist()) if "编号" in df.columns else set()
        return df, existing_ids
    except FileNotFoundError:
        print(f"[warn] {EXCEL} not found, will create new", file=sys.stderr)
        return None, set()

def fetch_completed():
    """Fetch all FT/AET/PEN matches from API-Football (2026 season)."""
    fixtures = api_get("fixtures", {"league": LEAGUE, "season": SEASON})
    out = []
    for f in fixtures:
        if f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
            continue
        try:
            fid = f["fixture"]["id"]
            yr = 2026
            rnd = f["fixture"]["round"] or "小组赛"
            date = f["fixture"]["date"]
            h = code_of(f["teams"]["home"]["name"]); a = code_of(f["teams"]["away"]["name"])
            gh = f["goals"]["home"]; ga = f["goals"]["away"]
            if h and a and gh is not None and ga is not None:
                out.append({
                    "API_ID": fid, "年份": yr, "轮次": rnd, "时间": date,
                    "主队": h, "客队": a, "全主进球数": gh, "全客进球数": ga
                })
        except (KeyError, TypeError):
            pass
    return out

def append_new(df, existing_ids, new_matches):
    """Append new matches to Excel (avoid duplicates by API_ID)."""
    if df is None:
        # Create header row if no existing Excel
        header_row = {
            "编号": "", "年份": "", "轮次": "", "时间": "",
            "主队": "", "客队": "", "半主进球数": "", "半客进球数": "", "半场比分": "",
            "全主进球数": "", "全客进球数": "", "全场比分": ""
        }
        df = pd.DataFrame([header_row])
    
    added = 0
    for m in new_matches:
        api_id = m["API_ID"]
        # Simple dedup: check if this API_ID is already in the Excel (add a helper column)
        if "API_ID" not in df.columns:
            df["API_ID"] = None
        existing_api = set(df["API_ID"].dropna().tolist())
        if api_id not in existing_api:
            # Assign next编号
            try:
                max_id = df["编号"].dropna().astype(int).max()
                next_id = int(max_id) + 1 if pd.notna(max_id) else 1
            except (ValueError, TypeError):
                next_id = len(df)
            
            m["编号"] = next_id
            df = pd.concat([df, pd.DataFrame([m])], ignore_index=True)
            added += 1
    
    return df, added

def main():
    if not API_KEY:
        sys.exit("APISPORTS_KEY not set.")
    
    df, existing = load_excel()
    new = fetch_completed()
    print(f"[fetch] Found {len(new)} finished matches in API (2026)")
    
    # Filter to only truly new ones
    new_ids = {m["API_ID"] for m in new}
    truly_new = [m for m in new if m["API_ID"] not in existing]
    print(f"[filter] {len(truly_new)} are new (not in existing {len(existing)})")
    
    if truly_new:
        df, added = append_new(df, existing, truly_new)
        df.to_excel(EXCEL, sheet_name=SHEET, index=False)
        print(f"[saved] Appended {added} rows to {EXCEL}")
    else:
        print("[no-op] No new matches to append")

if __name__ == "__main__":
    main()
