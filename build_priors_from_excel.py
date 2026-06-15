#!/usr/bin/env python3
"""
build_priors_from_excel.py  ·  从本地 Excel 数据库拟合数据驱动评分 (2006–2026)
------------------------------------------------------------------------------------
读取 Excel 里 2006–2026 的 394 场比赛，用指数时间衰减加权拟合攻防系数。
比直接调 API 快、数据全、还自带赔率历史。

输出 priors.json，供 fetch_worldcup_integrated.py 读取。

环境变量
  WC_EXCEL        本地 Excel 路径，默认 wc_data.xlsx
  WC_SHEET        sheet 名称，默认 "2006-2026"
  WC_HALFLIFE     衰减半衰期(年)，默认 4.0
  WC_OUT_PRIORS   输出 priors.json 路径，默认 priors.json
"""
import os, sys, json, math, unicodedata, datetime
import numpy as np
import pandas as pd

EXCEL = os.environ.get("WC_EXCEL", "wc_data.xlsx")
SHEET = os.environ.get("WC_SHEET", "2006-2026")
HALFLIFE = float(os.environ.get("WC_HALFLIFE", "4.0"))
OUT = os.environ.get("WC_OUT_PRIORS", "priors.json")
NOW_Y = 2026.0

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
# Chinese names -> code (for Excel data)
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
    """Try Chinese name first, then English ALIASES."""
    n_str = str(n).strip() if n else ""
    if n_str in CN_NAMES:
        return CN_NAMES[n_str]
    return ALIASES.get(norm(n_str))

def collect():
    """从 Excel 读取 2006–2026 的 394 场比赛。"""
    try:
        df = pd.read_excel(EXCEL, sheet_name=SHEET, header=2)  # 真实列名在第3行（row index 2）
    except Exception as e:
        sys.exit(f"Failed to read {EXCEL}: {e}")
    except Exception as e:
        sys.exit(f"Failed to read {EXCEL}: {e}")
    
    matches = []
    for _, row in df.iterrows():
        try:
            yr = int(row.get("年份", 0))
            h = code_of(str(row.get("主队", "")))
            a = code_of(str(row.get("客队", "")))
            gh = int(row.get("全主进球数", 0)) if pd.notna(row.get("全主进球数")) else None
            ga = int(row.get("全客进球数", 0)) if pd.notna(row.get("全客进球数")) else None
            if yr and 2006 <= yr <= 2026 and h and a and gh is not None and ga is not None:
                matches.append((yr, h, a, gh, ga))
        except (ValueError, TypeError, AttributeError):
            pass
    
    print(f"[collect] Read {len(matches)} matches from {EXCEL} (sheet '{SHEET}')")
    return matches

def fit(matches):
    """time-decayed weighted Poisson fit."""
    codes = sorted({c for _,h,a,_,_ in matches for c in (h,a)})
    idx = {c:i for i,c in enumerate(codes)}; n = len(codes)
    yr = np.array([m[0] for m in matches], float)
    hi = np.array([idx[m[1]] for m in matches]); ai = np.array([idx[m[2]] for m in matches])
    gh = np.array([m[3] for m in matches], float); ga = np.array([m[4] for m in matches], float)
    w = 0.5**((NOW_Y-yr)/HALFLIFE)                      # time decay
    
    A = np.ones(n); D = np.ones(n); mu = max(0.5, (w*(gh+ga)).sum()/(2*w.sum())); H = 1.10
    for _ in range(200):
        gf_num = np.zeros(n); np.add.at(gf_num, hi, w*gh); np.add.at(gf_num, ai, w*ga)
        gf_den = np.zeros(n)
        np.add.at(gf_den, hi, w*mu*H*D[ai]); np.add.at(gf_den, ai, w*mu*D[hi])
        A = np.where(gf_den>0, gf_num/gf_den, A); A *= n/max(A.sum(), 1e-9)
        
        ga_num = np.zeros(n); np.add.at(ga_num, hi, w*ga); np.add.at(ga_num, ai, w*gh)
        ga_den = np.zeros(n)
        np.add.at(ga_den, hi, w*mu*A[ai]); np.add.at(ga_den, ai, w*mu*H*A[hi])
        D = np.where(ga_den>0, ga_num/ga_den, D); D *= n/max(D.sum(), 1e-9)
        
        base = (w*(H*A[hi]*D[ai] + A[ai]*D[hi])).sum()
        mu = (w*(gh+ga)).sum()/max(base, 1e-9)
        Hnum = (w*gh).sum(); Hden = (w*mu*A[hi]*D[ai]).sum()
        H = max(0.8, min(1.6, Hnum/max(Hden, 1e-9)))
    
    return codes, A, D, mu, H, w, hi, ai, gh, ga

def main():
    matches = collect()
    if not matches:
        sys.exit("No matches extracted.")
    
    codes, A, D, mu, H, w, hi, ai, gh, ga = fit(matches)
    
    # World Cup records per team (un-weighted summary)
    hist = {c: dict(m=0, gf=0, ga=0, w=0, d=0, l=0) for c in codes}
    for yr,h,a,x,y in matches:
        for c,f,ag in ((h,x,y),(a,y,x)):
            r = hist[c]; r["m"]+=1; r["gf"]+=f; r["ga"]+=ag
            r["w"] += f>ag; r["d"] += f==ag; r["l"] += f<ag
    
    rating = A / np.maximum(D, 1e-6)
    lo, hi_only = np.percentile(rating, 5), np.percentile(rating, 95)
    def pr_of(x):
        t = (x - lo) / max(hi_only - lo, 1e-9); t = max(0.0, min(1.0, t))
        return round(1500 + 560*t)
    
    teams = {}
    for i, c in enumerate(codes):
        teams[c] = dict(atk=round(float(A[i]), 3), dff=round(float(D[i]), 3),
                        pr=pr_of(rating[i]), wc=hist[c])
    
    payload = dict(
        built=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        method="time-decayed weighted Poisson (from local Excel 2006-2026)",
        matches=len(matches),
        baselineMu=round(float(mu), 3),
        homeFactor=round(float(H), 3),
        halfLife=HALFLIFE,
        teams=teams
    )
    
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    
    eff = float((w/w.max()).sum())
    print(f"[ok] {OUT}: {len(teams)} teams, {len(matches)} WC matches "
          f"(eff.N≈{eff:.0f} after decay), mu={mu:.2f}, home={H:.2f}")

if __name__ == "__main__":
    main()
