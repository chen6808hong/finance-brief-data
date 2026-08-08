#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财经晨昏简报 - 云端兜底生成脚本 (纯 API，无 AI 依赖)
在 GitHub Actions (境外 ubuntu) 定时运行：
  抓取公开行情 API -> 组装 brief.json -> 由 workflow commit/push 到仓库。
作为兜底：本地 WorkBuddy 自动化(AI 精编) 在线时会覆盖本脚本产出；
本脚本保证即使本地客户端离线，页面也有结构合法、行情真实的最新快照。
"""
import json, urllib.request, urllib.parse, datetime, sys, os

UA = {'User-Agent': 'Mozilla/5.0 (compatible; finance-brief-bot/1.0)'}
TIMEOUT = 12

def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode('utf-8', 'ignore'))

def yf(symbol):
    """Yahoo Finance 实时/收盘报价，返回 (price, pct) 或 (None,None)"""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=1d&range=5d" % urllib.parse.quote(symbol)
    try:
        d = get_json(url)
        m = d['chart']['result'][0]['meta']
        price = m.get('regularMarketPrice')
        prev = m.get('chartPreviousClose') or m.get('previousClose')
        if price is None or not prev:
            return None, None
        return float(price), (float(price) - float(prev)) / float(prev) * 100.0
    except Exception:
        return None, None

def em_quote(secid):
    """东方财富个股/指数报价，secid 形如 1.000001 / 100.HSI"""
    url = "https://push2.eastmoney.com/api/qt/stock/get?secid=%s&fields=f43,f57,f58,f169,f170" % secid
    try:
        d = get_json(url)
        q = d.get('data') or {}
        p, pct = q.get('f43'), q.get('f170')
        if p is None or pct is None:
            return None, None
        return float(p), float(pct)
    except Exception:
        return None, None

def em_boards():
    """申万一级行业涨跌幅排行 [(name, pct), ...]"""
    out = []
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get?fs=m:90+t:1&fields=f12,f14,f3&pn=1&pz=30&po=1"
        d = get_json(url)
        for it in (d.get('data', {}).get('diff') or []):
            try:
                out.append((it.get('f14'), float(it.get('f3') or 0)))
            except Exception:
                pass
    except Exception:
        pass
    return out

def fmt(v, pct):
    if v is None:
        return "—", "—", 0
    d = 1 if pct > 0 else (-1 if pct < 0 else 0)
    c = ("+%.2f%%" % pct) if pct is not None else "—"
    return ("%.2f" % v), c, d

def mk(name, v, pct):
    vv, cc, dd = fmt(v, pct if pct is not None else 0)
    return {"n": name, "v": vv, "c": cc, "d": dd}

# ---------- 抓取 ----------
print("抓取行情中...", flush=True)
# A股宽基
ash = em_quote("1.000001"); asz = em_quote("0.399001"); acy = em_quote("0.399006")
akc = em_quote("1.000688"); ahs = em_quote("1.000300")
agl = em_quote("0.399363"); acp = em_quote("0.980017")
# 港股
hsi = em_quote("100.HSI"); hstech = em_quote("100.HSTECH"); hsiii = em_quote("100.HSIII")
# 美股/全球 (Yahoo)
dji = yf("^DJI"); ixic = yf("^IXIC"); ndx = yf("^NDX"); gsps = yf("^GSPC"); sox = yf("^SOX"); vix = yf("^VIX")
n225 = yf("^N225"); ks11 = yf("^KS11")
# 商品/外汇/利率
gc = yf("GC=F"); cl = yf("CL=F"); bz = yf("BZ=F"); dxy = yf("DX-Y.NYB"); tn_x = yf("^TNX"); fvy = yf("^FVX")

# 申万行业
boards = em_boards()

# ---------- 组装 marketGroups ----------
marketGroups = [
    {"name": "A股", "items": [
        mk("上证指数", ash[0], ash[1]),
        mk("深证成指", asz[0], asz[1]),
        mk("创业板指", acy[0], acy[1]),
        mk("科创50", akc[0], akc[1]),
        mk("国证算力", agl[0], agl[1]),
        mk("国证芯片", acp[0], acp[1]),
        mk("沪深300", ahs[0], ahs[1]),
    ]},
    {"name": "港股", "items": [
        mk("恒生指数", hsi[0], hsi[1]),
        mk("恒生科技", hstech[0], hstech[1]),
        mk("恒生互联网", hsiii[0] if hsiii[0] else hstech[0], hsiii[1] if hsiii[0] else hstech[1]),
    ]},
    {"name": "美股", "items": [
        mk("道琼斯", dji[0], dji[1]),
        mk("纳斯达克", ixic[0], ixic[1]),
        mk("纳指100", ndx[0], ndx[1]),
        mk("标普500", gsps[0], gsps[1]),
        mk("费城半导体", sox[0], sox[1]),
        mk("VIX", vix[0], vix[1]),
    ]},
    {"name": "外汇/利率", "items": [
        mk("5年美债收益率", fvy[0], None if fvy[0] is None else -fvy[1]),
        mk("10年美债收益率", tn_x[0], None if tn_x[0] is None else -tn_x[1]),
        mk("美元指数", dxy[0], dxy[1]),
    ]},
    {"name": "商品", "items": [
        mk("布伦特原油", bz[0], bz[1]),
        mk("现货黄金", gc[0], gc[1]),
    ]},
]

# ---------- sectors ----------
if boards:
    ups = [{"n": n, "v": round(p, 2)} for n, p in boards[:5] if p > 0]
    downs = [{"n": n, "v": round(p, 2)} for n, p in boards[-5:] if p < 0]
    # 兜底补齐
    while len(ups) < 5:
        ups.append({"n": "待更新%d" % (len(ups)+1), "v": 0.0})
    while len(downs) < 5:
        downs.append({"n": "待更新%d" % (len(downs)+1), "v": 0.0})
else:
    ups = [{"n": "煤炭", "v": 0.0}, {"n": "石油石化", "v": 0.0}, {"n": "通信", "v": 0.0}, {"n": "电子", "v": 0.0}, {"n": "建筑", "v": 0.0}]
    downs = [{"n": "传媒", "v": 0.0}, {"n": "汽车", "v": 0.0}, {"n": "电力设备", "v": 0.0}, {"n": "医药", "v": 0.0}, {"n": "计算机", "v": 0.0}]
sectors = {"up": ups[:5], "down": downs[:5]}

# ---------- 资讯 (规则化快照) ----------
def q(d): return d[1] if d and d[0] is not None else None
items = [
    {"id": 1, "imp": 3, "c": "macro", "t": "央行公开市场操作与流动性观察（自动快照）",
     "d": "本条目由云端定时脚本基于公开市场数据生成，详见各交易所与央行公开信息；AI 精编版将覆盖此内容。",
     "g": 0, "lv": "市场级", "s": ["流动性", "宏观"], "src": "公开行情API"},
    {"id": 2, "imp": 2, "c": "cn", "t": "A股主要宽基指数收盘表现（自动快照）",
     "d": "上证指数%s(%s)、深成指%s(%s)、创业板指%s(%s)，数据来自东方财富行情接口。" % (
        fmt(ash[0], ash[1])[0], fmt(ash[0], ash[1])[1],
        fmt(asz[0], asz[1])[0], fmt(asz[0], asz[1])[1],
        fmt(acy[0], acy[1])[0], fmt(acy[0], acy[1])[1]),
     "g": (1 if (q(ash) or 0) > 0 else -1), "lv": "市场级", "s": ["A股", "宽基"], "src": "东方财富"},
    {"id": 3, "imp": 2, "c": "intl", "t": "美股隔夜收盘与全球风险偏好（自动快照）",
     "d": "道指%s(%s)、纳指%s(%s)、纳指100%s(%s)、费城半导体%s(%s)、VIX%s(%s)，数据来自 Yahoo Finance。" % (
        fmt(dji[0], dji[1])[0], fmt(dji[0], dji[1])[1],
        fmt(ixic[0], ixic[1])[0], fmt(ixic[0], ixic[1])[1],
        fmt(ndx[0], ndx[1])[0], fmt(ndx[0], ndx[1])[1],
        fmt(sox[0], sox[1])[0], fmt(sox[0], sox[1])[1],
        fmt(vix[0], vix[1])[0], fmt(vix[0], vix[1])[1]),
     "g": (1 if (q(ixic) or 0) > 0 else -1), "lv": "市场级", "s": ["美股", "全球"], "src": "Yahoo Finance"},
    {"id": 4, "imp": 1, "c": "cn", "t": "港股与南向资金观察（自动快照）",
     "d": "恒生指数%s(%s)、恒生科技%s(%s)，数据来自东方财富行情接口。" % (
        fmt(hsi[0], hsi[1])[0], fmt(hsi[0], hsi[1])[1],
        fmt(hstech[0], hstech[1])[0], fmt(hstech[0], hstech[1])[1]),
     "g": (1 if (q(hsi) or 0) > 0 else -1), "lv": "市场级", "s": ["港股", "南向"], "src": "东方财富"},
    {"id": 5, "imp": 1, "c": "intl", "t": "商品与外汇利率（自动快照）",
     "d": "现货黄金%s(%s)、WTI原油%s(%s)、美元指数%s(%s)、10年美债收益率%s，数据来自 Yahoo Finance。" % (
        fmt(gc[0], gc[1])[0], fmt(gc[0], gc[1])[1],
        fmt(cl[0], cl[1])[0], fmt(cl[0], cl[1])[1],
        fmt(dxy[0], dxy[1])[0], fmt(dxy[0], dxy[1])[1],
        fmt(tn_x[0], tn_x[1])[0]),
     "g": 0, "lv": "市场级", "s": ["商品", "外汇"], "src": "Yahoo Finance"},
    {"id": 6, "imp": 1, "c": "macro", "t": "亚太与全球市场联动（自动快照）",
     "d": "日经225%s(%s)、韩国综指%s(%s)，数据来自 Yahoo Finance。" % (
        fmt(n225[0], n225[1])[0], fmt(n225[0], n225[1])[1],
        fmt(ks11[0], ks11[1])[0], fmt(ks11[0], ks11[1])[1]),
     "g": 0, "lv": "市场级", "s": ["亚太", "全球"], "src": "Yahoo Finance"},
]

focus = [
    {"t": "A股主要宽基收盘表现（自动快照）",
     "d": "上证%s(%s)、深成%s(%s)、创业板%s(%s)，数据来自公开市场接口。" % (
        fmt(ash[0], ash[1])[0], fmt(ash[0], ash[1])[1],
        fmt(asz[0], asz[1])[0], fmt(asz[0], asz[1])[1],
        fmt(acy[0], acy[1])[0], fmt(acy[0], acy[1])[1])},
    {"t": "美股隔夜与全球风险偏好（自动快照）",
     "d": "纳指%s(%s)、费城半导体%s(%s)，数据来自 Yahoo Finance。" % (
        fmt(ixic[0], ixic[1])[0], fmt(ixic[0], ixic[1])[1],
        fmt(sox[0], sox[1])[0], fmt(sox[0], sox[1])[1])},
    {"t": "商品与避险资产（自动快照）",
     "d": "现货黄金%s(%s)、WTI原油%s(%s)。" % (
        fmt(gc[0], gc[1])[0], fmt(gc[0], gc[1])[1],
        fmt(cl[0], cl[1])[0], fmt(cl[0], cl[1])[1])},
]

opps = [
    {"t": "红利与低估值宽基（数据驱动）", "lv": "关注", "lvc": "lv-b",
     "d": "若主要宽基回落，红利与低估值板块具备相对防御属性，关注高股息与权重蓝筹。",
     "tags": ["红利", "低估值"], "risk": "市场风格切换时相对收益不确定，须结合基本面。"},
    {"t": "黄金与避险资产（数据驱动）", "lv": "关注", "lvc": "lv-b",
     "d": "现货黄金%s(%s)，地缘与利率预期支撑贵金属中期趋势。" % (fmt(gc[0], gc[1])[0], fmt(gc[0], gc[1])[1]),
     "tags": ["黄金", "避险"], "risk": "美元与美债收益率反弹将压制金价短线。"},
    {"t": "半导体与算力链（数据驱动）", "lv": "主线", "lvc": "lv-a",
     "d": "费城半导体%s(%s)，全球 AI 算力高景气延续，关注设备与存储链。" % (fmt(sox[0], sox[1])[0], fmt(sox[0], sox[1])[1]),
     "tags": ["半导体", "算力"], "risk": "高位拥挤与海外政策扰动或放大波动。"},
    {"t": "港股科技与互联互通（数据驱动）", "lv": "关注", "lvc": "lv-b",
     "d": "恒生科技%s(%s)，南向资金对港股科技持续增配。" % (fmt(hstech[0], hstech[1])[0], fmt(hstech[0], hstech[1])[1]),
     "tags": ["恒生科技", "南向"], "risk": "指数权重股拖累，需甄别个股质地。"},
]

risks = [
    "本版为云端定时脚本生成的行情快照，非 AI 精编，资讯深度有限，仅供结构化参考。",
    "A股/港股行情接口在境外 CI 偶有延迟或失败，价格以各交易所收盘口径为准。",
    "美股与商品采用 Yahoo Finance 数据，时区与收盘口径可能与境内不一致。",
    "市场波动放大时，高位板块拥挤交易风险集中释放。",
    "海外利率与地缘事件仍可能引发全球资产共振波动。",
    "本简报由公开信息自动汇编，不构成任何投资建议，据此操作风险自担。",
]

# 信息差·认知差：云端快照版仅采集财经类通用型条目（纯 API 无 AI 依赖），共 10 条；
# AI 精编版可覆盖为更有针对性的内容。
insights = [
    {"t": "单月数据容易被放大，趋势信号要看「前两月修正」", "typ": "信息差", "cat": "财经",
     "d": "市场常聚焦当月数值，忽视前两月下修才是拐点信号；下修幅度越大，前期数据被高估的程度越深，资产价格反应往往滞后。", "src": "公开资讯"},
    {"t": "「政策喊话=必然落地」是常见认知差", "typ": "认知差", "cat": "财经",
     "d": "行业自律、倡议书与行政强制存在本质区别，无罚则的承诺执行度常打折扣，盈利修复节奏易被提前定价。", "src": "公开资讯"},
    {"t": "指数急涨叠加新开户激增，常是情绪过热的反向信号", "typ": "信息差", "cat": "财经",
     "d": "散户开户数与成交量同步冲高，往往对应阶段性赚钱效应扩散的尾声，而非趋势起点，需警惕量价背离。", "src": "交易所/券商"},
    {"t": "「整数关口突破=无脑追涨」是典型认知差", "typ": "认知差", "cat": "财经",
     "d": "黄金、股指等突破关键整数位常被解读为趋势确认，但整数位本身无基本面含义；把长期看多逻辑直接等同于当下追涨，易在情绪高点接盘。", "src": "公开资讯"},
    {"t": "收益率曲线倒挂是领先指标，不是即时衰退信号", "typ": "信息差", "cat": "财经",
     "d": "长短端利差倒挂常被视为衰退前兆，但它领先经济实际走弱往往有数月时滞；把倒挂当天当作衰退已发生，会误判政策与资产节奏。", "src": "公开资讯"},
    {"t": "本币中间价微调常被误读为贬值意图", "typ": "认知差", "cat": "财经",
     "d": "中间价小幅调贬在美元走弱背景下，常是央行收窄逆周期因子、让汇率更市场化的体现，而非主动引导贬值；需结合离岸价与供求判断。", "src": "外汇交易中心"},
    {"t": "ETF净申购潮常是「下跌中越跌越买」的结果，而非看涨先行信号", "typ": "信息差", "cat": "财经",
     "d": "机构与长期资金多在回调中分批申购，净流入更多是对已发生波动的结果映射；单周申购数据噪声大，不宜简单当作方向领先信号。", "src": "交易所/基金业协会"},
    {"t": "「北向/外资单日净买入」不等于聪明钱看多", "typ": "认知差", "cat": "财经",
     "d": "单日净买卖含被动调仓、对冲与套利，噪声很大；判断真实流向应看数周维度的连续净买入与持仓结构。", "src": "港交所/公开数据"},
    {"t": "分红除权日股价「下跌」是账面价值重排，并非真实亏损", "typ": "信息差", "cat": "财经",
     "d": "除权除息日股价按分红额机械下移，实为权益内部转移；追逐填权者常忽略税收与除权后实际回报。", "src": "公开资讯"},
    {"t": "低市盈率(PE)不等于便宜，盈利周期位置更关键", "typ": "认知差", "cat": "财经",
     "d": "周期股在盈利高点PE最低（看似便宜实则贵），低谷PE最高（看似贵实则便宜）；估值须结合盈利周期与自由现金流。", "src": "公开资讯"},
]

now = datetime.datetime.now()
weekday_cn = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"][now.weekday()]
brief = {
    "date": now.strftime("%Y-%m-%d"),
    "updated": now.strftime("%Y-%m-%d %H:%M") + "(云端快照)",
    "weekday": weekday_cn,
    "marketGroups": marketGroups,
    "sectors": sectors,
    "focus": focus,
    "items": items,
    "opps": opps,
    "risks": risks,
    "insights": insights,
    "sources": "数据源：东方财富行情接口、Yahoo Finance；本版为云端定时脚本自动生成的行情快照，AI 精编版将覆盖此内容。",
}

# ---------- 兜底防覆盖：若本地 AI 精编版当天已更新，则不覆盖 ----------
TODAY = brief["date"]
try:
    with open("brief.json", "r", encoding="utf-8") as _f:
        _existing = json.load(_f)
    _ex_date = _existing.get("date")
    _ex_upd = _existing.get("updated", "")
    if _ex_date == TODAY and ("云端快照" not in _ex_upd):
        print("检测到本地 AI 精编版(%s)当天已更新，云端兜底跳过覆盖。" % _ex_upd, flush=True)
        sys.exit(0)
except Exception:
    pass  # 文件不存在或解析失败则正常生成

with open("brief.json", "w", encoding="utf-8") as f:
    json.dump(brief, f, ensure_ascii=False, indent=2)
print("已生成 brief.json(云端快照)，date=%s items=%d sectors=%d/%d" % (
    brief["date"], len(items), len(sectors["up"]), len(sectors["down"])), flush=True)
