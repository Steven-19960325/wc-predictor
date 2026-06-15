#!/usr/bin/env python3
"""
fetch_worldcup.py  v2  ·  2026 World Cup live model updater  (three sources)
---------------------------------------------------------------------------
SOURCE 1  API-Football  (fixtures + standings)  -> Poisson xG model  [每小时]
SOURCE 2  The Odds API  (h2h odds, de-vigged)   -> market probability [每2小时]
SOURCE 3  Qi Men service (mingfa-paipan wrapper)-> 玄学倾向(默认权重0) [每小时]

每个 fixture 输出三套信号 + 真太阳时；融合权重在前端用滑杆调，默认 奇门=0。

预算
  API-Football 免费 100/天：fixtures+standings = 2/时 = 48/天。
  The Odds API 免费 500/月：每2小时1次 = 360/月。脚本用 UTC 小时是否为偶数来闸门。
环境变量
  APISPORTS_KEY  (必填)   API-Football key
  ODDS_KEY       (选填)   The Odds API key；不填则跳过赔率
  QIMEN_URL      (选填)   奇门服务地址，如 http://localhost:8787/paipan；不填则跳过奇门
  WC_FORCE_ODDS=1(选填)   忽略2小时闸门，强制拉赔率（手动测试用）
"""

import os, sys, json, math, unicodedata, datetime
import requests

API_KEY  = os.environ.get("APISPORTS_KEY", "").strip()
ODDS_KEY = os.environ.get("ODDS_KEY", "").strip()
QIMEN_URL= os.environ.get("QIMEN_URL", "").strip()
BASE     = "https://v3.football.api-sports.io"
ODDS_BASE= "https://api.the-odds-api.com/v4"
LEAGUE   = int(os.environ.get("WC_LEAGUE", "1"))
SEASON   = int(os.environ.get("WC_SEASON", "2026"))
OUT      = os.environ.get("WC_OUT", "predictions.json")
HEADERS  = {"x-apisports-key": API_KEY}

BASE_GOALS = 1.35
SHRINK_W   = 3.0
HOSTS      = {"MEX", "USA", "CAN"}

PR = {
 "MEX":1760,"RSA":1660,"KOR":1730,"CZE":1730,"CAN":1740,"BIH":1700,"QAT":1620,"SUI":1780,
 "BRA":2000,"MAR":1860,"HAI":1540,"SCO":1700,"USA":1760,"PAR":1680,"AUS":1700,"TUR":1760,
 "GER":1955,"CUW":1560,"CIV":1720,"ECU":1760,"NED":1965,"JPN":1800,"SWE":1740,"TUN":1660,
 "BEL":1900,"EGY":1720,"IRN":1730,"NZL":1560,"ESP":2090,"CPV":1600,"KSA":1620,"URU":1840,
 "FRA":2075,"SEN":1790,"IRQ":1600,"NOR":1820,"ARG":2080,"ALG":1720,"AUT":1760,"JOR":1600,
 "POR":1985,"COD":1660,"UZB":1620,"COL":1820,"ENG":2010,"CRO":1840,"GHA":1680,"PAN":1640,
}
NAME = {
 "MEX":"墨西哥","RSA":"南非","KOR":"韩国","CZE":"捷克","CAN":"加拿大","BIH":"波黑","QAT":"卡塔尔","SUI":"瑞士",
 "BRA":"巴西","MAR":"摩洛哥","HAI":"海地","SCO":"苏格兰","USA":"美国","PAR":"巴拉圭","AUS":"澳大利亚","TUR":"土耳其",
 "GER":"德国","CUW":"库拉索","CIV":"科特迪瓦","ECU":"厄瓜多尔","NED":"荷兰","JPN":"日本","SWE":"瑞典","TUN":"突尼斯",
 "BEL":"比利时","EGY":"埃及","IRN":"伊朗","NZL":"新西兰","ESP":"西班牙","CPV":"佛得角","KSA":"沙特阿拉伯","URU":"乌拉圭",
 "FRA":"法国","SEN":"塞内加尔","IRQ":"伊拉克","NOR":"挪威","ARG":"阿根廷","ALG":"阿尔及利亚","AUT":"奥地利","JOR":"约旦",
 "POR":"葡萄牙","COD":"刚果(金)","UZB":"乌兹别克斯坦","COL":"哥伦比亚","ENG":"英格兰","CRO":"克罗地亚","GHA":"加纳","PAN":"巴拿马",
}
ALIASES = {
 "mexico":"MEX","southafrica":"RSA","southkorea":"KOR","korearepublic":"KOR","korea":"KOR",
 "czechrepublic":"CZE","czechia":"CZE","canada":"CAN","bosniaandherzegovina":"BIH","bosnia":"BIH",
 "qatar":"QAT","switzerland":"SUI","brazil":"BRA","morocco":"MAR","haiti":"HAI","scotland":"SCO",
 "usa":"USA","unitedstates":"USA","paraguay":"PAR","australia":"AUS","turkey":"TUR","turkiye":"TUR",
 "germany":"GER","curacao":"CUW","ivorycoast":"CIV","cotedivoire":"CIV","ecuador":"ECU",
 "netherlands":"NED","japan":"JPN","sweden":"SWE","tunisia":"TUN","belgium":"BEL","egypt":"EGY",
 "iran":"IRN","iriran":"IRN","newzealand":"NZL","spain":"ESP","capeverde":"CPV","capeverdeislands":"CPV",
 "saudiarabia":"KSA","uruguay":"URU","france":"FRA","senegal":"SEN","iraq":"IRQ","norway":"NOR",
 "argentina":"ARG","algeria":"ALG","austria":"AUT","jordan":"JOR","portugal":"POR",
 "drcongo":"COD","congodr":"COD","democraticrepublicofcongo":"COD","uzbekistan":"UZB","colombia":"COL",
 "england":"ENG","croatia":"CRO","ghana":"GHA","panama":"PAN",
}
# 16 host cities -> (lon east+, lat) for true-solar-time correction
CITY = {
 "atlanta":(-84.39,33.75),"foxborough":(-71.27,42.09),"boston":(-71.06,42.36),
 "arlington":(-97.08,32.73),"dallas":(-96.80,32.78),"houston":(-95.37,29.76),
 "kansascity":(-94.58,39.10),"inglewood":(-118.34,33.96),"losangeles":(-118.24,34.05),
 "miami":(-80.19,25.76),"miamigardens":(-80.24,25.94),"eastrutherford":(-74.07,40.81),
 "newyork":(-74.01,40.71),"newjersey":(-74.07,40.81),"philadelphia":(-75.16,39.95),
 "santaclara":(-121.97,37.40),"sanfrancisco":(-122.42,37.77),"seattle":(-122.33,47.61),
 "mexicocity":(-99.13,19.43),"guadalajara":(-103.35,20.67),"monterrey":(-100.31,25.69),
 "toronto":(-79.38,43.65),"vancouver":(-123.12,49.28),
}
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"

def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())
def code_of(api_name): return ALIASES.get(norm(api_name))
def city_of(name):
    n = norm(name)
    if n in CITY: return CITY[n]
    for k,v in CITY.items():
        if k in n or n in k: return v
    return None

def strength(pr): return max(0.0, min(1.0, (pr - 1490) / 620.0))
def atk_prior(pr): return 0.60 + 1.00 * strength(pr)
def def_prior(pr): return 1.40 - 0.80 * strength(pr)
def pois(k, lam): return math.exp(-lam) * lam**k / math.factorial(k)

# data-driven priors from build_priors.py (1930-2026, time-decayed). Optional.
PRIORS = {}
try:
    with open(os.environ.get("WC_PRIORS","priors.json"), encoding="utf-8") as _f:
        _p = json.load(_f); PRIORS = _p.get("teams", {})
        print(f"[priors] loaded {len(PRIORS)} data-driven team priors "
              f"(HL={_p.get('halfLife')}y, {_p.get('matches')} WC matches)")
except FileNotFoundError:
    print("[priors] priors.json not found -> using hand-set ratings")
except Exception as _e:
    print(f"[priors] load failed ({_e}) -> using hand-set ratings", file=sys.stderr)

def prior_mults(code):
    """(atk, dff, pr) prior for a team: data-driven if available, else hand-set."""
    p = PRIORS.get(code)
    if p and "atk" in p and "dff" in p:
        return p["atk"], p["dff"], p.get("pr", PR.get(code, 1700))
    pr = PR.get(code, 1700)
    return atk_prior(pr), def_prior(pr), pr

def predict(lamH, lamA):
    pH=pD=pA=0.0; grid={}
    for i in range(9):
        for j in range(9):
            p=pois(i,lamH)*pois(j,lamA); grid[(i,j)]=p
            if i>j:pH+=p
            elif i==j:pD+=p
            else:pA+=p
    top=sorted(grid.items(),key=lambda kv:kv[1],reverse=True)[:3]
    over25=sum(p for (i,j),p in grid.items() if i+j>=3)
    return pH,pD,pA,[(f"{i}-{j}",round(p,4)) for (i,j),p in top],over25

def confidence(gap, top_outcome):
    score=max(0.0,min(100.0,abs(gap)/3.2+(top_outcome-0.34)*135))
    tier=("极高" if score>=78 else "高" if score>=58 else "中" if score>=38 else "较低" if score>=20 else "低")
    return round(score),tier

# ---------- true solar time ----------
def equation_of_time_minutes(dt_utc):
    N = dt_utc.timetuple().tm_yday
    B = 2*math.pi*(N-81)/364.0
    return 9.87*math.sin(2*B) - 7.53*math.cos(B) - 1.5*math.sin(B)
def true_solar_time(dt_utc, lon):
    eot = equation_of_time_minutes(dt_utc)
    offset = datetime.timedelta(hours=lon/15.0, minutes=eot)
    tst = dt_utc + offset
    return tst, eot
def shichen(tst):
    idx = int(((tst.hour + 1) % 24)//2)
    return BRANCHES[idx] + "时"

def api_get(path, params):
    r=requests.get(f"{BASE}/{path}",headers=HEADERS,params=params,timeout=30)
    r.raise_for_status(); d=r.json()
    if d.get("errors"): print(f"[warn] /{path}: {d['errors']}",file=sys.stderr)
    return d.get("response",[])

# ---------- The Odds API ----------
def fetch_odds():
    """Return {(homeCode,awayCode): {pH,pD,pA,books}} de-vigged & averaged. 1 credit."""
    out={}
    try:
        r=requests.get(f"{ODDS_BASE}/sports/soccer_fifa_world_cup/odds",
                       params={"apiKey":ODDS_KEY,"regions":"eu","markets":"h2h","oddsFormat":"decimal"},
                       timeout=30)
        r.raise_for_status()
        remain=r.headers.get("x-requests-remaining")
        print(f"[odds] remaining this month: {remain}")
        for ev in r.json():
            hc=code_of(ev.get("home_team","")); ac=code_of(ev.get("away_team",""))
            if not hc or not ac: continue
            ph=[];pd=[];pa=[];books=0
            for bk in ev.get("bookmakers",[]):
                for mk in bk.get("markets",[]):
                    if mk.get("key")!="h2h": continue
                    o={}
                    for oc in mk.get("outcomes",[]):
                        nm=oc["name"]; o[("D" if nm=="Draw" else code_of(nm))]=oc["price"]
                    if "D" in o and hc in o and ac in o and all(o[k]>1 for k in (hc,ac,"D")):
                        inv=[1/o[hc],1/o["D"],1/o[ac]]; s=sum(inv)
                        ph.append(inv[0]/s); pd.append(inv[1]/s); pa.append(inv[2]/s); books+=1
            if books:
                out[(hc,ac)]=dict(pH=round(sum(ph)/books,3),pD=round(sum(pd)/books,3),
                                  pA=round(sum(pa)/books,3),books=books)
    except Exception as e:
        print(f"[odds] skipped: {e}",file=sys.stderr)
    return out

# ---------- Qi Men service ----------
def call_qimen(tst, lon, lat):
    """POST corrected true-solar-time + location to the mingfa-paipan wrapper.
       Expects JSON: {favor:'home'|'away'|'draw', strength:0..1, summary:str, chart?:..}"""
    if not QIMEN_URL: return None
    try:
        r=requests.post(QIMEN_URL,json={"datetime":tst.isoformat(),"lon":lon,"lat":lat},timeout=25)
        r.raise_for_status(); d=r.json()
        fav=d.get("favor","draw"); st=float(d.get("strength",0))
        return dict(favor=fav,strength=max(0.0,min(1.0,st)),summary=d.get("summary",""))
    except Exception as e:
        print(f"[qimen] skipped: {e}",file=sys.stderr)
        return None

def main():
    if not API_KEY: sys.exit("APISPORTS_KEY not set.")
    now=datetime.datetime.now(datetime.timezone.utc)

    fixtures  = api_get("fixtures",  {"league":LEAGUE,"season":SEASON})
    standings = api_get("standings", {"league":LEAGUE,"season":SEASON})

    # odds gate: every 2 hours (even UTC hour) to stay under 500/month
    odds_map={}
    if ODDS_KEY and (os.environ.get("WC_FORCE_ODDS")=="1" or now.hour%2==0):
        odds_map=fetch_odds()

    # records from standings (fallback: finished fixtures)
    rec={}
    try: groups=standings[0]["league"]["standings"] if standings else []
    except (IndexError,KeyError): groups=[]
    for grp in groups:
        for row in grp:
            c=code_of(row["team"]["name"])
            if not c: continue
            a=row.get("all",{}); g=a.get("goals",{})
            rec[c]=dict(played=a.get("played",0),w=a.get("win",0),d=a.get("draw",0),
                        l=a.get("lose",0),gf=g.get("for",0),ga=g.get("against",0))
    if not rec:
        for fx in fixtures:
            if fx["fixture"]["status"]["short"] not in ("FT","AET","PEN"): continue
            for s,o in (("home","away"),("away","home")):
                c=code_of(fx["teams"][s]["name"])
                if not c: continue
                gf=fx["goals"][s] or 0; ga=fx["goals"][o] or 0
                r=rec.setdefault(c,dict(played=0,w=0,d=0,l=0,gf=0,ga=0))
                r["played"]+=1; r["gf"]+=gf; r["ga"]+=ga
                r["w"]+=gf>ga; r["d"]+=gf==ga; r["l"]+=gf<ga

    tot_g=sum(r["gf"] for r in rec.values()); tot_m=sum(r["played"] for r in rec.values())
    avg=(tot_g/tot_m) if tot_m else BASE_GOALS

    teams=[]; mult={}
    for code,pr in PR.items():
        ap,dp=atk_prior(pr),def_prior(pr); r=rec.get(code,dict(played=0,w=0,d=0,l=0,gf=0,ga=0)); n=r["played"]
        if n>0 and avg>0:
            a=(SHRINK_W*ap+n*((r["gf"]/n)/avg))/(SHRINK_W+n)
            d=(SHRINK_W*dp+n*((r["ga"]/n)/avg))/(SHRINK_W+n)
        else: a,d=ap,dp
        mult[code]=(a,d)
        teams.append(dict(code=code,name=NAME[code],pr=pr,atk=round(a,3),dff=round(d,3),
                          atkPrior=round(ap,3),dffPrior=round(dp,3),rec=r))

    LIVE={"1H","HT","2H","ET","BT","P","LIVE"}; PEND={"NS","TBD","PST"}
    out_fx=[]
    for fx in fixtures:
        st=fx["fixture"]["status"]["short"]
        if st not in LIVE and st not in PEND: continue
        hc=code_of(fx["teams"]["home"]["name"]); ac=code_of(fx["teams"]["away"]["name"])
        if not hc or not ac: continue
        (ah,dh),(aa,da)=mult[hc],mult[ac]
        vH=1.12 if hc in HOSTS else 1.0; vA=0.93 if hc in HOSTS else 1.0
        lamH=BASE_GOALS*ah*da*vH; lamA=BASE_GOALS*aa*dh*vA
        pH,pD,pA,top,over25=predict(lamH,lamA); tot=pH+pD+pA
        score,tier=confidence(PR[hc]-PR[ac],max(pH,pD,pA)/tot)

        # true solar time + qimen (only for not-yet-finished, charted at kickoff)
        qimen=None; tstinfo=None
        loc=city_of((fx["fixture"].get("venue") or {}).get("city") or
                    (fx["fixture"].get("venue") or {}).get("name") or "")
        try: dt_utc=datetime.datetime.fromisoformat(fx["fixture"]["date"].replace("Z","+00:00"))
        except Exception: dt_utc=None
        if loc and dt_utc:
            lon,lat=loc; tst,eot=true_solar_time(dt_utc.astimezone(datetime.timezone.utc),lon)
            tstinfo=dict(tst=tst.strftime("%Y-%m-%d %H:%M"),shichen=shichen(tst),eot=round(eot,1),lon=lon)
            if st in PEND:
                qimen=call_qimen(tst,lon,lat)

        out_fx.append(dict(
            id=fx["fixture"]["id"],date=fx["fixture"]["date"],status=st,home=hc,away=ac,
            liveScore=[fx["goals"]["home"],fx["goals"]["away"]] if st in LIVE else None,
            lamH=round(lamH,2),lamA=round(lamA,2),
            model=dict(pH=round(pH/tot,3),pD=round(pD/tot,3),pA=round(pA/tot,3)),
            market=odds_map.get((hc,ac)),
            qimen=qimen, tst=tstinfo,
            topScores=top,over25=round(over25,3),conf=score,confTier=tier))

    out_fx.sort(key=lambda f:f["date"])
    payload=dict(updated=now.isoformat(),league=LEAGUE,season=SEASON,avgGoals=round(avg,3),
                 matchesPlayed=tot_m,shrinkWeight=SHRINK_W,
                 sources=dict(model=True,market=bool(odds_map),qimen=bool(QIMEN_URL)),
                 teams=teams,fixtures=out_fx)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(payload,f,ensure_ascii=False,indent=1)
    print(f"[ok] {OUT}: {len(teams)} teams, {len(out_fx)} fixtures, odds={len(odds_map)}, "
          f"qimen={'on' if QIMEN_URL else 'off'}, {tot_m} played, avg {avg:.2f}")

if __name__=="__main__": main()
