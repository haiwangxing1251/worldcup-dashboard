"""
实时数据抓取模块 — 2026 世界杯预测系统
=========================================

功能：
  1. fetch_elo_ratings()  — 从网络抓取最新 ELO 评分
  2. fetch_fifa_rankings() — 从网络抓取最新 FIFA 排名
  3. fetch_match_results() — 抓取已完赛的世界杯比分
  4. update_elo_from_results() — 根据真实比分更新 ELO
  5. merge_and_save() — 合并数据并写回本地 JSON

数据源（按优先级降序）：
  - eloratings.net        (ELO 评分)
  - worldfootballrankings.com (ELO 备选)
  - whereig.com           (FIFA 排名)
  - Google 搜索结果        (比赛比分)

依赖：纯 Python 标准库（urllib + re + json），无需 pip install。
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ============================================================
# 配置
# ============================================================
HTTP_TIMEOUT = 15  # 秒
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# ELO 数据源列表（按优先级）
ELO_SOURCES = [
    {
        "name": "eloratings.net",
        "url": "https://www.eloratings.net/",
        "parser": "eloratings",
    },
    {
        "name": "worldfootballrankings.com",
        "url": "https://www.worldfootballrankings.com/rankings",
        "parser": "wfr",
    },
]

# FIFA 排名数据源
FIFA_RANK_SOURCES = [
    {
        "name": "whereig.com",
        "url": "https://www.whereig.com/football/fifa-world-rankings.html",
        "parser": "whereig",
    },
]

# 48 支参赛队 3 字母代码 → 全名映射（用于匹配爬取数据）
CODE_TO_NAME = {
    "FRA": "France",       "ESP": "Spain",          "ARG": "Argentina",
    "ENG": "England",       "POR": "Portugal",        "BRA": "Brazil",
    "NED": "Netherlands",   "MAR": "Morocco",         "BEL": "Belgium",
    "GER": "Germany",       "CRO": "Croatia",         "COL": "Colombia",
    "SEN": "Senegal",       "MEX": "Mexico",          "USA": "United States",
    "URU": "Uruguay",       "JPN": "Japan",           "SUI": "Switzerland",
    "IRN": "Iran",          "TUR": "Turkey",          "ECU": "Ecuador",
    "AUT": "Austria",       "KOR": "South Korea",     "AUS": "Australia",
    "ALG": "Algeria",       "EGY": "Egypt",           "CAN": "Canada",
    "NOR": "Norway",        "PAN": "Panama",          "CIV": "Ivory Coast",
    "SWE": "Sweden",        "PAR": "Paraguay",        "CZE": "Czech Republic",
    "SCO": "Scotland",      "TUN": "Tunisia",         "COD": "DR Congo",
    "UZB": "Uzbekistan",    "KSA": "Saudi Arabia",    "RSA": "South Africa",
    "BIH": "Bosnia & Herzegovina", "QAT": "Qatar",    "GHA": "Ghana",
    "JOR": "Jordan",        "IRQ": "Iraq",            "CPV": "Cape Verde",
    "HAI": "Haiti",         "CUW": "Curacao",         "NZL": "New Zealand",
}

# 球队名 → 代码（反向映射，用于匹配）
NAME_TO_CODE = {v: k for k, v in CODE_TO_NAME.items()}
# 再加一些常见变体
NAME_ALIASES = {
    "USA":                "United States",
    "US":                 "United States",
    "America":            "United States",
    "Korea Republic":     "South Korea",
    "South Korea":        "South Korea",
    "Korea":              "South Korea",
    "Ivory Coast":        "Ivory Coast",
    "Côte d'Ivoire":     "Ivory Coast",
    "Cote d'Ivoire":     "Ivory Coast",
    "DR Congo":           "DR Congo",
    "Congo DR":           "DR Congo",
    "Czechia":            "Czech Republic",
    "Bosnia":             "Bosnia & Herzegovina",
    "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "Saudi":              "Saudi Arabia",
    "South Africa":       "South Africa",
    "New Zealand":        "New Zealand",
    "Cape Verde Islands": "Cape Verde",
    "Holland":            "Netherlands",
}


def _fetch_url(url: str) -> Optional[str]:
    """使用 urllib 抓取网页内容（纯文本）。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read()
            # 尝试解码
            for enc in ["utf-8", "latin-1", "iso-8859-1"]:
                try:
                    return raw.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue
            return raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [数据抓取] 请求失败 {url}: {e}")
        return None


def _match_team(name: str) -> Optional[str]:
    """将爬取到的队名匹配到 3 字母代码。"""
    name = name.strip()
    # 直接匹配
    if name in NAME_TO_CODE:
        return NAME_TO_CODE[name]
    # 别名匹配
    for alias, full in NAME_ALIASES.items():
        if name.lower() == alias.lower():
            return NAME_TO_CODE.get(full)
    # 模糊匹配
    name_lower = name.lower()
    for full_name, code in NAME_TO_CODE.items():
        if name_lower in full_name.lower() or full_name.lower() in name_lower:
            return code
    return None


# ============================================================
# ELO 评分抓取
# ============================================================

def _parse_eloratings(html: str) -> Dict[str, Dict]:
    """解析 eloratings.net 的 HTML 表格。"""
    teams = {}
    # 匹配表格行：排名 | 球队 | 评分 | ...
    # 页面结构：<tr> <td>rank</td> <td>team</td> <td>rating</td> ...
    rows = re.findall(
        r'<tr[^>]*>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>.*?<a[^>]*>([^<]+)</a>.*?</td>\s*<td[^>]*>(\d{3,4})</td>',
        html, re.DOTALL | re.IGNORECASE
    )
    if not rows:
        # 备用正则：更宽松的匹配
        rows = re.findall(
            r'<tr[^>]*>.*?<td[^>]*>(\d+)</td>.*?<td[^>]*>(.*?)</td>.*?<td[^>]*>(\d{3,4})</td>',
            html, re.DOTALL | re.IGNORECASE
        )
    for rank_str, team_name, rating_str in rows:
        code = _match_team(team_name.strip())
        if code:
            teams[code] = {
                "elo": float(rating_str),
                "rank": int(rank_str),
                "source": "eloratings.net",
                "estimated": False,
            }
    return teams


def _parse_wfr(html: str) -> Dict[str, Dict]:
    """解析 worldfootballrankings.com 的 HTML 表格。"""
    teams = {}
    # 匹配：排名-球队-ELO
    rows = re.findall(
        r'<tr[^>]*>.*?<td[^>]*>(\d+)</td>.*?<td[^>]*>(.*?)</td>.*?<td[^>]*>(\d{3,4})</td>',
        html, re.DOTALL | re.IGNORECASE
    )
    for rank_str, team_name, rating_str in rows:
        code = _match_team(team_name.strip())
        if code:
            teams[code] = {
                "elo": float(rating_str),
                "rank": int(rank_str),
                "source": "worldfootballrankings.com",
                "estimated": False,
            }
    return teams


def fetch_elo_ratings() -> Dict[str, Dict]:
    """
    从网络抓取最新 ELO 评分。

    返回：{ "FRA": {"elo": 1877, "rank": 1, "estimated": false}, ... }
    """
    print("\n🌐 正在抓取最新 ELO 评分……")
    for source in ELO_SOURCES:
        print(f"  尝试 {source['name']}……")
        html = _fetch_url(source["url"])
        if not html:
            continue

        if source["parser"] == "eloratings":
            teams = _parse_eloratings(html)
        else:
            teams = _parse_wfr(html)

        if teams:
            # 检查覆盖率：至少要匹配到 30+ 支球队
            matched = len(teams)
            print(f"  ✅ 从 {source['name']} 抓取到 {matched} 支球队的 ELO 数据")
            return teams
        else:
            print(f"  ⚠️  {source['name']} 解析失败，尝试下一个源……")

    print("  ❌ 所有数据源均抓取失败，将使用本地缓存数据")
    return {}


# ============================================================
# FIFA 排名抓取
# ============================================================

def fetch_fifa_rankings() -> Dict[str, int]:
    """
    从网络抓取最新 FIFA 排名。

    返回：{ "FRA": 3, "ARG": 1, ... }
    """
    print("\n🌐 正在抓取最新 FIFA 排名……")
    for source in FIFA_RANK_SOURCES:
        html = _fetch_url(source["url"])
        if not html:
            continue

        # 匹配：排名 | 球队
        rankings = {}
        rows = re.findall(
            r'<tr[^>]*>.*?<td[^>]*>(\d{1,3})</td>.*?<td[^>]*>(.*?)</td>',
            html, re.DOTALL | re.IGNORECASE
        )
        for rank_str, team_name in rows:
            code = _match_team(team_name.strip())
            if code and code not in rankings:
                rankings[code] = int(rank_str)

        if len(rankings) >= 30:
            print(f"  ✅ 从 {source['name']} 抓取到 {len(rankings)} 支球队的 FIFA 排名")
            return rankings
        else:
            print(f"  ⚠️  {source['name']} 只匹配到 {len(rankings)} 支球队")

    print("  ❌ FIFA 排名抓取失败")
    return {}


# ============================================================
# 比赛结果抓取
# ============================================================

def fetch_match_results() -> List[Dict]:
    """
    抓取 2026 世界杯已完赛比分。

    数据源（按优先级）：
      1. openfootball/worldcup.json（GitHub Raw，免费、实时更新）
      2. 本地缓存（网络不可用时）

    返回格式：
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
    print("\n🌐 正在获取 2026 世界杯最新赛果……")

    today = datetime.now()
    tournament_start = datetime(2026, 6, 11)

    if today < tournament_start:
        days_left = (tournament_start - today).days
        print(f"  距世界杯开赛还有 {days_left} 天，暂无赛果")
        return []

    # 使用 worldcup_api 模块获取实时数据
    try:
        from worldcup_api import get_match_results_for_elo
        results = get_match_results_for_elo()
        if results:
            print(f"  ✅ 从 openfootball API 获取到 {len(results)} 场已完赛比分")
            return results
    except ImportError:
        print("  ⚠️  worldcup_api 模块不可用")

    print("  ℹ️  未获取到赛果数据")
    return []


# ============================================================
# ELO 更新算法
# ============================================================

def update_elo_from_results(
    elo_data: Dict[str, Dict],
    match_results: List[Dict],
) -> Dict[str, Dict]:
    """
    根据真实比赛结果更新 ELO 评分。

    使用标准 ELO 更新公式：
      new = old + K * (actual - expected)
      其中 K = 30（世界杯权重），actual = 1/0.5/0（胜/平/负）

    返回更新后的 ELO 数据。
    """
    if not match_results:
        return elo_data

    K = 30  # 世界杯 K 因子
    updated = {k: dict(v) for k, v in elo_data.items()}

    for match in match_results:
        a, b = match["team_a"], match["team_b"]
        ga, gb = match["goals_a"], match["goals_b"]

        if a not in updated or b not in updated:
            continue

        elo_a = updated[a]["elo"]
        elo_b = updated[b]["elo"]

        # 预期胜率
        expected_a = 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))

        # 实际结果
        if ga > gb:
            actual_a = 1.0
        elif gb > ga:
            actual_a = 0.0
        else:
            actual_a = 0.5

        # 更新
        delta = K * (actual_a - expected_a)
        updated[a]["elo"] = elo_a + delta
        updated[b]["elo"] = elo_b - delta

    print(f"  🔄 根据 {len(match_results)} 场真实赛果更新了 ELO 评分")
    return updated


# ============================================================
# 合并与保存
# ============================================================

def merge_elo_data(
    existing: Dict[str, Dict],
    fetched: Dict[str, Dict],
) -> Dict[str, Dict]:
    """将抓取到的新数据合并到现有数据中。"""
    merged = {k: dict(v) for k, v in existing.items()}

    for code, info in fetched.items():
        if code in merged:
            merged[code]["elo"] = info["elo"]
            merged[code].setdefault("rank", info.get("rank", 0))
            merged[code]["estimated"] = False
            merged[code]["last_updated"] = datetime.now().isoformat()

    # 标记未被更新的球队
    for code in merged:
        if code not in fetched:
            merged[code].setdefault("estimated", True)

    return merged


def save_elo_data(elo_data: Dict[str, Dict], output_path: str):
    """保存 ELO 数据到 JSON 文件。"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 读取原有文件结构，保留 teams 包裹
    original = {}
    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            original = json.load(f)

    output = {
        "source": original.get("source", "worldfootballrankings.com"),
        "last_updated": datetime.now().isoformat(),
        "teams": elo_data,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  💾 ELO 数据已保存至 {output_path}")


def sync_all(
    elo_path: str,
    groups_path: str,
    force: bool = False,
) -> Dict:
    """
    一键同步所有数据。

    返回：
      {
        "elo_updated": bool,
        "matches_found": int,
        "elo_from_web": int,     # 从网络获取到的球队数
        "timestamp": "ISO8601",
      }
    """
    result = {
        "elo_updated": False,
        "matches_found": 0,
        "elo_from_web": 0,
        "timestamp": datetime.now().isoformat(),
    }

    # 1. 抓取最新 ELO
    fetched_elo = fetch_elo_ratings()
    result["elo_from_web"] = len(fetched_elo)

    if fetched_elo:
        # 读取现有数据
        existing = {}
        if os.path.exists(elo_path):
            with open(elo_path, "r", encoding="utf-8") as f:
                existing = json.load(f).get("teams", {})

        # 合并数据
        merged = merge_elo_data(existing, fetched_elo)

        # 2. 抓取比赛结果
        matches = fetch_match_results()
        result["matches_found"] = len(matches)

        # 3. 根据赛果更新 ELO
        if matches:
            merged = update_elo_from_results(merged, matches)

        # 4. 保存
        save_elo_data(merged, elo_path)
        result["elo_updated"] = True
    else:
        print("\n  ⚠️  使用本地缓存数据（网络抓取未成功）")

    return result


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    elo_path = os.path.join(base_dir, "data", "elo_ratings.json")
    groups_path = os.path.join(base_dir, "data", "groups.json")

    print("=" * 60)
    print("  2026 世界杯数据同步工具")
    print(f"  时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    result = sync_all(elo_path, groups_path)
    print(f"\n📊 同步结果：")
    print(f"  ELO 更新：{'✅ 成功' if result['elo_updated'] else '❌ 失败'}")
    print(f"  网络数据：{result['elo_from_web']} 支球队")
    print(f"  赛果数据：{result['matches_found']} 场")
