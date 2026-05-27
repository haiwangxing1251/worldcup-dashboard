"""
世界杯实时数据 API 模块 — 2026 世界杯预测系统
===============================================

数据源：openfootball/worldcup.json（GitHub Raw JSON，CC0 公共领域）
  - 赛前：提供完整赛程（104场，含日期/时间/球队/小组/场馆）
  - 赛中：同一 JSON 更新比分（score.ft/ht/et）、进球者、比赛状态
  - 赛后：包含全部完赛结果

特点：
  - 无需 API Key，完全免费
  - GitHub 全球 CDN，国内可访问
  - JSON 格式，解析简单
  - 本地缓存 + TTL，避免频繁请求
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# ============================================================
# 配置
# ============================================================
# 数据源 URL
DATA_URL = (
    "https://raw.githubusercontent.com/openfootball/worldcup.json/"
    "master/2026/worldcup.json"
)

# 本地缓存路径
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CACHE_FILE = os.path.join(CACHE_DIR, "worldcup_live.json")

# 缓存有效期（秒）
CACHE_TTL_PRE = 86400     # 赛前：24小时
CACHE_TTL_DURING = 600    # 赛中：10分钟
CACHE_TTL_POST = 86400    # 赛后：24小时

HTTP_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# 48 队英文名 → 3字母代码映射
TEAM_NAME_TO_CODE = {
    "Mexico":                   "MEX",
    "South Africa":            "RSA",
    "South Korea":             "KOR",
    "Czech Republic":          "CZE",
    "Canada":                  "CAN",
    "Bosnia & Herzegovina":    "BIH",
    "Qatar":                   "QAT",
    "Switzerland":             "SUI",
    "Brazil":                  "BRA",
    "Morocco":                 "MAR",
    "Haiti":                   "HAI",
    "Scotland":                "SCO",
    "USA":                     "USA",
    "Paraguay":                "PAR",
    "Australia":               "AUS",
    "Turkey":                  "TUR",
    "Germany":                 "GER",
    "Curaçao":                 "CUW",
    "Ivory Coast":             "CIV",
    "Ecuador":                 "ECU",
    "Netherlands":             "NED",
    "Japan":                   "JPN",
    "Sweden":                  "SWE",
    "Tunisia":                 "TUN",
    "Belgium":                 "BEL",
    "Egypt":                   "EGY",
    "Iran":                    "IRN",
    "New Zealand":             "NZL",
    "Spain":                   "ESP",
    "Cape Verde":              "CPV",
    "Saudi Arabia":            "KSA",
    "Uruguay":                 "URU",
    "France":                  "FRA",
    "Senegal":                 "SEN",
    "Iraq":                    "IRQ",
    "Norway":                  "NOR",
    "Argentina":               "ARG",
    "Algeria":                 "ALG",
    "Austria":                 "AUT",
    "Jordan":                  "JOR",
    "Portugal":                "POR",
    "DR Congo":                "COD",
    "Uzbekistan":              "UZB",
    "Colombia":                "COL",
    "England":                 "ENG",
    "Croatia":                 "CRO",
    "Ghana":                   "GHA",
    "Panama":                  "PAN",
}

# 反向：代码 → 英文名
CODE_TO_NAME = {v: k for k, v in TEAM_NAME_TO_CODE.items()}

# 中文名映射
TEAM_NAMES_CN = {
    "MEX": "墨西哥",   "RSA": "南非",       "KOR": "韩国",
    "CZE": "捷克",     "CAN": "加拿大",     "BIH": "波黑",
    "QAT": "卡塔尔",   "SUI": "瑞士",       "BRA": "巴西",
    "MAR": "摩洛哥",   "HAI": "海地",       "SCO": "苏格兰",
    "USA": "美国",     "PAR": "巴拉圭",     "AUS": "澳大利亚",
    "TUR": "土耳其",   "GER": "德国",       "CUW": "库拉索",
    "CIV": "科特迪瓦", "ECU": "厄瓜多尔",   "NED": "荷兰",
    "JPN": "日本",     "SWE": "瑞典",       "TUN": "突尼斯",
    "BEL": "比利时",   "EGY": "埃及",       "IRN": "伊朗",
    "NZL": "新西兰",   "ESP": "西班牙",     "CPV": "佛得角",
    "KSA": "沙特",     "URU": "乌拉圭",     "FRA": "法国",
    "SEN": "塞内加尔", "IRQ": "伊拉克",     "NOR": "挪威",
    "ARG": "阿根廷",   "ALG": "阿尔及利亚", "AUT": "奥地利",
    "JOR": "约旦",     "POR": "葡萄牙",     "COD": "刚果(金)",
    "UZB": "乌兹别克斯坦", "COL": "哥伦比亚", "ENG": "英格兰",
    "CRO": "克罗地亚", "GHA": "加纳",       "PAN": "巴拿马",
}

# 轮次中文标签
ROUND_LABELS = {
    "Matchday 1":  "小组赛第1轮",
    "Matchday 2":  "小组赛第1轮",
    "Matchday 3":  "小组赛第1轮",
    "Matchday 4":  "小组赛第1轮",
    "Matchday 5":  "小组赛第1轮",
    "Matchday 6":  "小组赛第1轮",
    "Matchday 7":  "小组赛第1轮",
    "Matchday 8":  "小组赛第2轮",
    "Matchday 9":  "小组赛第2轮",
    "Matchday 10": "小组赛第2轮",
    "Matchday 11": "小组赛第2轮",
    "Matchday 12": "小组赛第2轮",
    "Matchday 13": "小组赛第2轮",
    "Matchday 14": "小组赛第3轮",
    "Matchday 15": "小组赛第3轮",
    "Matchday 16": "小组赛第3轮",
    "Matchday 17": "小组赛第3轮",
    "Round of 32":         "三十二强",
    "Round of 16":         "十六强",
    "Quarter-final":       "四分之一决赛",
    "Semi-final":          "半决赛",
    "Match for third place": "三四名决赛",
    "Final":               "决赛",
}

# 淘汰赛顺序
KNOCKOUT_ORDER = [
    "Round of 32", "Round of 16", "Quarter-final",
    "Semi-final", "Match for third place", "Final",
]


def _tz_to_beijing(date_str: str, time_str: str) -> str:
    """将 UTC 时区时间转换为北京时间字符串 'HH:MM'。
    
    输入如 date_str="2026-06-11", time_str="13:00 UTC-6"
    """
    import re
    m = re.match(r'(\d{1,2}):(\d{2})\s+UTC([+-]\d+)', time_str)
    if not m:
        return time_str.split()[0]  # 无法解析，返回原始时间
    
    hour, minute = int(m.group(1)), int(m.group(2))
    utc_offset = int(m.group(3))
    
    # 先转 UTC
    utc_hour = hour - utc_offset
    # 再转北京时间 (UTC+8)
    bj_hour = (utc_hour + 8) % 24
    
    return f"{bj_hour:02d}:{minute:02d}"


def _extract_group(grp_str: str) -> str:
    """从 'Group A' 提取 'A'。"""
    if grp_str and grp_str.startswith("Group "):
        return grp_str[6:]
    return grp_str


def _safe_int(val, default=0):
    """安全整数转换。"""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# ============================================================
# 数据抓取
# ============================================================

def fetch_raw_data(force: bool = False) -> Optional[Dict]:
    """从 GitHub 抓取原始 JSON 数据，支持本地缓存。
    
    Args:
        force: 强制刷新，忽略缓存
        
    Returns:
        原始 JSON 数据字典，失败返回 None
    """
    # 检查缓存
    if not force and os.path.exists(CACHE_FILE):
        try:
            cache_mtime = os.path.getmtime(CACHE_FILE)
            now = time.time()
            
            # 判断缓存 TTL
            today = datetime.now()
            tournament_start = datetime(2026, 6, 11)
            tournament_end = datetime(2026, 7, 20)
            
            if today < tournament_start:
                ttl = CACHE_TTL_PRE
            elif today > tournament_end:
                ttl = CACHE_TTL_POST
            else:
                ttl = CACHE_TTL_DURING
            
            if now - cache_mtime < ttl:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data and "matches" in data:
                    return data
        except (json.JSONDecodeError, OSError):
            pass  # 缓存损坏，重新抓取
    
    # 网络抓取
    req = urllib.request.Request(DATA_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            
            # 写入缓存
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return data
    except Exception as e:
        # 网络失败，尝试用缓存
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        
        print(f"  [API] 数据抓取失败: {e}")
        return None


# ============================================================
# 数据解析
# ============================================================

def parse_matches(raw_data: Dict) -> List[Dict]:
    """将原始 JSON 的比赛数据解析为统一内部格式。
    
    内部格式：
    {
        "match_id": "1",            # 比赛编号（按JSON顺序）
        "date": "2026-06-11",       # 日期
        "time_bj": "03:00",         # 北京时间
        "round": "Matchday 1",      # 原始轮次名
        "stage": "小组赛第1轮",     # 中文阶段
        "stage_code": "group",      # group|r32|r16|qf|sf|third|final
        "group": "A",               # 小组（淘汰赛为 None）
        "home": "Mexico",           # 主队英文名
        "away": "South Africa",     # 客队英文名
        "home_code": "MEX",         # 主队代码
        "away_code": "RSA",         # 客队代码
        "home_cn": "墨西哥",        # 主队中文名
        "away_cn": "南非",          # 客队中文名
        "venue": "Mexico City",     # 场馆
        "score_ft": [0, 0],         # 全场比分（null = 未开赛）
        "score_ht": [0, 0],         # 半场比分
        "finished": False,          # 是否已完赛
        "started": False,           # 是否已开赛
        "knockout_num": None,       # 淘汰赛比赛编号
    }
    """
    matches = []
    raw_matches = raw_data.get("matches", [])
    
    for idx, m in enumerate(raw_matches):
        round_name = m.get("round", "")
        grp = _extract_group(m.get("group", ""))
        date_str = m.get("date", "")
        time_raw = m.get("time", "")
        time_bj = _tz_to_beijing(date_str, time_raw) if time_raw else ""
        
        home_name = m.get("team1", "")
        away_name = m.get("team2", "")
        home_code = TEAM_NAME_TO_CODE.get(home_name, home_name)
        away_code = TEAM_NAME_TO_CODE.get(away_name, away_name)
        
        # 判断阶段
        if round_name.startswith("Matchday"):
            stage_code = "group"
            stage_label = ROUND_LABELS.get(round_name, "小组赛")
        elif round_name == "Round of 32":
            stage_code = "r32"
            stage_label = ROUND_LABELS.get(round_name, "三十二强")
        elif round_name == "Round of 16":
            stage_code = "r16"
            stage_label = ROUND_LABELS.get(round_name, "十六强")
        elif round_name == "Quarter-final":
            stage_code = "qf"
            stage_label = ROUND_LABELS.get(round_name, "四分之一决赛")
        elif round_name == "Semi-final":
            stage_code = "sf"
            stage_label = ROUND_LABELS.get(round_name, "半决赛")
        elif round_name == "Match for third place":
            stage_code = "third"
            stage_label = ROUND_LABELS.get(round_name, "三四名决赛")
        elif round_name == "Final":
            stage_code = "final"
            stage_label = ROUND_LABELS.get(round_name, "决赛")
        else:
            stage_code = "unknown"
            stage_label = round_name
        
        # 解析比分
        score = m.get("score")
        finished = False
        score_ft = None
        score_ht = None
        
        if score:
            ft = score.get("ft")
            ht = score.get("ht")
            if ft and len(ft) == 2:
                score_ft = ft
                finished = True
            if ht and len(ht) == 2:
                score_ht = ht
        
        # 解析进球
        goals_home = m.get("goals1", [])
        goals_away = m.get("goals2", [])
        
        # 淘汰赛编号
        knockout_num = m.get("num")
        
        match_data = {
            "match_id": str(idx + 1),
            "date": date_str,
            "time_bj": time_bj,
            "time_raw": time_raw,
            "round": round_name,
            "stage": stage_label,
            "stage_code": stage_code,
            "group": grp if grp else None,
            "home": home_name,
            "away": away_name,
            "home_code": home_code,
            "away_code": away_code,
            "home_cn": TEAM_NAMES_CN.get(home_code, home_name),
            "away_cn": TEAM_NAMES_CN.get(away_code, away_name),
            "venue": m.get("ground", ""),
            "score_ft": score_ft,
            "score_ht": score_ht,
            "finished": finished,
            "started": score_ft is not None or finished,
            "knockout_num": knockout_num,
            "goals_home": goals_home,
            "goals_away": goals_away,
        }
        matches.append(match_data)
    
    return matches


def get_all_matches(force: bool = False) -> List[Dict]:
    """获取全部 104 场比赛数据。
    
    Args:
        force: 强制刷新缓存
        
    Returns:
        比赛列表（内部格式）
    """
    raw = fetch_raw_data(force=force)
    if not raw:
        return []
    return parse_matches(raw)


def get_today_matches(force: bool = False) -> List[Dict]:
    """获取今天的比赛。"""
    today = datetime.now().strftime("%Y-%m-%d")
    matches = get_all_matches(force=force)
    return [m for m in matches if m["date"] == today]


def get_matches_by_date(date_str: str, force: bool = False) -> List[Dict]:
    """获取指定日期的比赛。"""
    matches = get_all_matches(force=force)
    return [m for m in matches if m["date"] == date_str]


def get_finished_matches(force: bool = False) -> List[Dict]:
    """获取所有已完赛的比赛。"""
    matches = get_all_matches(force=force)
    return [m for m in matches if m.get("finished")]


def get_group_matches(group_name: str, force: bool = False) -> List[Dict]:
    """获取指定小组的所有比赛。"""
    matches = get_all_matches(force=force)
    return [m for m in matches if m.get("group") == group_name]


def get_group_standings(force: bool = False) -> Dict[str, List[Dict]]:
    """计算小组积分榜。
    
    返回：{ "A": [{"team": "MEX", "pts": 3, "gf": 2, "ga": 0, ...}, ...], ... }
    """
    matches = get_all_matches(force=force)
    
    # 初始化
    groups = {}
    for grp in [chr(ord('A') + i) for i in range(12)]:
        groups[grp] = {}
    
    # 遍历每场小组赛
    for m in matches:
        if m["stage_code"] != "group":
            continue
        grp = m.get("group")
        if not grp:
            continue
        if not m.get("finished"):
            continue
        
        home_code = m["home_code"]
        away_code = m["away_code"]
        ft = m.get("score_ft")
        if not ft:
            continue
        
        hg, ag = ft[0], ft[1]
        
        # 确保两支队伍都在积分榜中
        for code in [home_code, away_code]:
            if code not in groups[grp]:
                groups[grp][code] = {
                    "team": code,
                    "team_cn": TEAM_NAMES_CN.get(code, code),
                    "played": 0, "wins": 0, "draws": 0, "losses": 0,
                    "gf": 0, "ga": 0, "gd": 0, "pts": 0,
                }
        
        # 更新主队
        groups[grp][home_code]["played"] += 1
        groups[grp][home_code]["gf"] += hg
        groups[grp][home_code]["ga"] += ag
        
        # 更新客队
        groups[grp][away_code]["played"] += 1
        groups[grp][away_code]["gf"] += ag
        groups[grp][away_code]["ga"] += hg
        
        if hg > ag:
            groups[grp][home_code]["wins"] += 1
            groups[grp][home_code]["pts"] += 3
            groups[grp][away_code]["losses"] += 1
        elif ag > hg:
            groups[grp][away_code]["wins"] += 1
            groups[grp][away_code]["pts"] += 3
            groups[grp][home_code]["losses"] += 1
        else:
            groups[grp][home_code]["draws"] += 1
            groups[grp][home_code]["pts"] += 1
            groups[grp][away_code]["draws"] += 1
            groups[grp][away_code]["pts"] += 1
    
    # 计算净胜球 + 排序
    result = {}
    for grp, teams in groups.items():
        for code in teams:
            teams[code]["gd"] = teams[code]["gf"] - teams[code]["ga"]
        
        sorted_teams = sorted(
            teams.values(),
            key=lambda t: (-t["pts"], -t["gd"], -t["gf"], t["team"])
        )
        result[grp] = sorted_teams
    
    return result


def get_match_results_for_elo() -> List[Dict]:
    """获取用于 ELO 更新的比赛结果。
    
    返回格式（与 data_fetcher.py 兼容）：
    [
      {
        "team_a": "FRA", "team_b": "SEN",
        "goals_a": 2, "goals_b": 1,
        "stage": "group",
        "group": "I",
        "date": "2026-06-12"
      },
      ...
    ]
    """
    matches = get_all_matches()
    results = []
    
    for m in matches:
        if not m.get("finished"):
            continue
        ft = m.get("score_ft")
        if not ft:
            continue
        
        # 只对真实球队的结果有效（排除淘汰赛 TBD 占位符）
        if m["home_code"] not in TEAM_NAMES_CN or m["away_code"] not in TEAM_NAMES_CN:
            continue
        
        results.append({
            "team_a": m["home_code"],
            "team_b": m["away_code"],
            "goals_a": ft[0],
            "goals_b": ft[1],
            "stage": m["stage_code"],
            "group": m.get("group"),
            "date": m["date"],
        })
    
    return results


def get_tournament_status() -> Dict:
    """获取赛事整体状态。"""
    matches = get_all_matches()
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    
    total = len(matches)
    finished = sum(1 for m in matches if m.get("finished"))
    today_matches = [m for m in matches if m["date"] == today_str]
    today_finished = sum(1 for m in today_matches if m.get("finished"))
    
    # 所有比赛日期
    all_dates = sorted(set(m["date"] for m in matches))
    completed_dates = sum(1 for d in all_dates if d < today_str)
    
    return {
        "total_matches": total,
        "finished_matches": finished,
        "remaining_matches": total - finished,
        "today_matches": len(today_matches),
        "today_finished": today_finished,
        "today": today_str,
        "tournament_start": "2026-06-11",
        "tournament_end": "2026-07-19",
        "total_matchdays": len(all_dates),
        "completed_matchdays": completed_dates,
        "is_live": today_str >= "2026-06-11" and today_str <= "2026-07-19",
        "data_source": "openfootball/worldcup.json (GitHub)",
        "last_updated": datetime.now().isoformat(),
    }


def get_live_match_details(force: bool = False) -> List[Dict]:
    """获取正在进行的比赛详情（用于实时更新）。
    
    返回包含比分、进球者等详细信息的列表。
    """
    matches = get_all_matches(force=force)
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    
    live = []
    for m in matches:
        if m["date"] == today_str and m.get("started"):
            live.append(m)
    
    return live


# ============================================================
# 快速诊断
# ============================================================

def diagnose() -> str:
    """运行诊断，返回可读的状态报告。"""
    lines = []
    lines.append("=" * 50)
    lines.append("  世界杯数据 API 诊断报告")
    lines.append(f"  时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 50)
    
    # 测试网络连接
    lines.append("\n📡 网络连接测试：")
    try:
        req = urllib.request.Request(DATA_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            lines.append(f"  ✅ GitHub Raw 可访问（状态码 {resp.status}）")
    except Exception as e:
        lines.append(f"  ❌ 无法访问数据源：{e}")
    
    # 检查缓存
    if os.path.exists(CACHE_FILE):
        mtime = datetime.fromtimestamp(os.path.getmtime(CACHE_FILE))
        age = (datetime.now() - mtime).total_seconds()
        lines.append(f"\n📦 本地缓存：{CACHE_FILE}")
        lines.append(f"  更新时间：{mtime.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  缓存年龄：{age:.0f} 秒")
    
    # 加载数据
    matches = get_all_matches(force=True)
    if not matches:
        lines.append("\n❌ 无法加载比赛数据")
        return "\n".join(lines)
    
    lines.append(f"\n⚽ 比赛数据：")
    lines.append(f"  总场次：{len(matches)}")
    
    # 按阶段统计
    stages = {}
    for m in matches:
        sc = m["stage_code"]
        stages[sc] = stages.get(sc, 0) + 1
    for sc, cnt in sorted(stages.items()):
        lines.append(f"  {sc}: {cnt} 场")
    
    # 已完赛
    finished = [m for m in matches if m.get("finished")]
    lines.append(f"\n✅ 已完赛：{len(finished)} 场")
    if finished:
        for m in finished[:5]:
            ft = m.get("score_ft", [0, 0])
            lines.append(
                f"  {m['date']} {m['home_cn']} {ft[0]}-{ft[1]} {m['away_cn']}"
                f" ({m['stage']})"
            )
        if len(finished) > 5:
            lines.append(f"  ... 及其他 {len(finished) - 5} 场")
    
    # 今天比赛
    today = datetime.now().strftime("%Y-%m-%d")
    today_m = [m for m in matches if m["date"] == today]
    lines.append(f"\n📅 今日比赛（{today}）：{len(today_m)} 场")
    for m in today_m:
        status = "🟢 进行中" if m.get("started") else "⏳ 未开始"
        if m.get("finished"):
            ft = m.get("score_ft", [0, 0])
            status = f"✅ {ft[0]}-{ft[1]}"
        lines.append(f"  {m['time_bj']} {m['home_cn']} vs {m['away_cn']} — {status}")
    
    # 积分榜（如果有完赛）
    if finished:
        standings = get_group_standings()
        lines.append(f"\n📊 小组积分榜（已完赛小组）：")
        for grp in sorted(standings.keys()):
            if standings[grp]:
                lines.append(f"\n  {grp}组：")
                for t in standings[grp]:
                    if t["played"] > 0:
                        lines.append(
                            f"    {t['team_cn']} {t['played']}场 "
                            f"{t['wins']}胜{t['draws']}平{t['losses']}负 "
                            f"进{t['gf']}失{t['ga']} 净{t['gd']} {t['pts']}分"
                        )
    
    return "\n".join(lines)


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="世界杯实时数据 API")
    parser.add_argument("--diagnose", "-d", action="store_true", help="运行诊断")
    parser.add_argument("--today", "-t", action="store_true", help="显示今日比赛")
    parser.add_argument("--results", "-r", action="store_true", help="显示完赛结果")
    parser.add_argument("--force", "-f", action="store_true", help="强制刷新")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    
    args = parser.parse_args()
    
    if args.diagnose:
        print(diagnose())
    elif args.today:
        matches = get_today_matches(force=args.force)
        if args.json:
            print(json.dumps(matches, ensure_ascii=False, indent=2))
        else:
            print(f"\n📅 今日比赛（{datetime.now().strftime('%Y-%m-%d')}）：")
            if not matches:
                print("  (无比赛)")
            for m in matches:
                status = "未开始"
                if m.get("finished"):
                    ft = m.get("score_ft", [0, 0])
                    status = f"{ft[0]}-{ft[1]}（已完赛）"
                print(f"  {m['time_bj']} {m['home_cn']} vs {m['away_cn']} — {status}")
    elif args.results:
        results = get_match_results_for_elo()
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"\n✅ 已完赛结果（{len(results)} 场）：")
            for r in results:
                print(f"  {r['date']} {r['team_a']} {r['goals_a']}-{r['goals_b']} {r['team_b']}")
    else:
        status = get_tournament_status()
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            print(f"\n🏆 2026 世界杯赛事状态：")
            print(f"  日期：{status['today']}")
            print(f"  赛程：{status['total_matches']} 场比赛")
            print(f"  完赛：{status['finished_matches']} 场")
            print(f"  剩余：{status['remaining_matches']} 场")
            print(f"  数据源：{status['data_source']}")
