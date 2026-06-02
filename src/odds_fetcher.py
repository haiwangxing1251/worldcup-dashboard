"""
odds_fetcher.py — 抓取 wc-2026.com 的2026世界杯赔率数据

使用标准库（urllib + re），无需额外依赖。
数据源：wc-2026.com/world-cup-odds/ （冠军赔率、小组出线赔率、最佳射手赔率）

输出：data/odds.json
融合：把赔率隐含概率融合到 ELO 评分中，提升预测准确度
"""

import json
import os
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import re

CST = timezone(timedelta(hours=8))

# 中文队名 → 3字母 FIFA 代码
TEAM_NAME_MAP = {
    "西班牙": "ESP", "法国": "FRA", "英格兰": "ENG",
    "巴西": "BRA", "阿根廷": "ARG", "葡萄牙": "POR",
    "德国": "GER", "荷兰": "NED", "挪威": "NOR",
    "比利时": "BEL", "哥伦比亚": "COL", "摩洛哥": "MAR",
    "日本": "JPN", "美国": "USA", "瑞士": "SUI",
    "墨西哥": "MEX", "乌拉圭": "URU", "土耳其": "TUR",
    "厄瓜多尔": "ECU", "克罗地亚": "CRO", "塞内加尔": "SEN",
    "瑞典": "SWE", "奥地利": "AUT", "加拿大": "CAN",
    "苏格兰": "SCO", "科特迪瓦": "CIV", "巴拉圭": "PAR",
    "捷克": "CZE", "埃及": "EGY", "韩国": "KOR",
    "阿尔及利亚": "ALG", "波黑": "BIH", "加纳": "GHA",
    "澳大利亚": "AUS", "突尼斯": "TUN", "伊朗": "IRN",
    "刚果民主共和国": "COD", "南非": "RSA", "沙特阿拉伯": "KSA",
    "巴拿马": "PAN", "卡塔尔": "QAT", "佛得角": "CPV",
    "新西兰": "NZL", "伊拉克": "IRQ", "乌兹别克斯坦": "UZB",
    "库拉索": "CUW", "约旦": "JOR", "海地": "HAI",
}

def _fetch_html(url: str, timeout: int = 15) -> str | None:
    """用 urllib 抓取页面 HTML，返回字符串或 None。"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=timeout) as resp:
            charset = "utf-8"
            ct = resp.headers.get("Content-Type", "")
            m = re.search(r"charset=([^\s;]+)", ct)
            if m:
                charset = m.group(1)
            return resp.read().decode(charset, errors="replace")
    except (URLError, HTTPError, TimeoutError) as e:
        print(f"[odds] 抓取失败 {url!r}: {e}")
        return None


def fetch_outright_odds() -> list[dict] | None:
    """
    抓取冠军（夺冠）赔率。
    返回 [{"rank":1, "team":"ESP", "team_cn":"西班牙", "odd":5.75}, ...]
    """
    url = "https://wc-2026.com/world-cup-odds/"
    html = _fetch_html(url)
    if not html:
        return None

    # 用正则直接提取表格行中的数据
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    results = []
    for row_html in rows:
        # 提取行内所有纯文本（去掉 HTML 标签）
        texts = [t.strip() for t in re.sub(r"<[^>]+>", "\n", row_html).split("\n") if t.strip()]
        # 找排名（行首数字）
        if not texts or not re.match(r"^\d+$", texts[0]):
            continue
        rank = int(texts[0])
        if rank > 48:
            continue
        # 找赔率数字（1.01 ~ 9999）
        odds = [float(x) for x in texts if re.match(r"^\d+\.\d+$", x) and 1.0 < float(x) < 10000]
        # 球队中文名：第一个非数字、非赔率的文本
        team_cn = None
        for t in texts[1:]:
            if not re.match(r"^\d+(\.\d+)?$", t):
                team_cn = t
                break
        if not team_cn or not odds:
            continue
        team_code = TEAM_NAME_MAP.get(team_cn)
        if not team_code:
            print(f"[odds] 未知球队名: {team_cn}")
            continue
        results.append({
            "rank": rank,
            "team": team_code,
            "team_cn": team_cn,
            "odd": odds[0],
        })
    if results:
        # 只保留前 48 条（冠军赔率），去掉后面的小组出线赔率
        # 冠军赔率 rank 是 1~48 连续唯一；小组赛 rank 会重复 1~4
        seen_ranks = set()
        unique = []
        for r in results:
            rk = r["rank"]
            if rk in seen_ranks:
                break   # 遇到重复 rank，说明已经进入小组赛表格
            seen_ranks.add(rk)
            unique.append(r)
        print(f"[odds] 冠军赔率 {len(unique)} 条，跳过 {len(results)-len(unique)} 条小组赛赔率")
        return unique[:48]

    # 备选方案：用 HTMLParser 解析（上面的正则失败时）
    print("[odds] 正则解析失败，尝试 HTMLParser...")
    return None


def fetch_odds(use_cache: bool = True, cache_minutes: int = 60) -> dict:
    """
    统一抓取入口，带本地缓存。
    返回 { "outright": [...], "updated_at": "...", "source": "..." }
    """
    os.makedirs("data", exist_ok=True)
    cache_path = "data/odds.json"
    now = datetime.now(CST)

    # 读取缓存
    if use_cache and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)
            updated_at = datetime.fromisoformat(cached["updated_at"])
            if (now - updated_at).total_seconds() < cache_minutes * 60:
                print(f"[odds] 使用缓存（{updated_at.strftime('%H:%M')} CST）")
                return cached
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    print("[odds] 正在抓取赔率数据...")
    outright = fetch_outright_odds()

    result = {
        "outright": outright or [],
        "updated_at": now.isoformat(),
        "source": "wc-2026.com",
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[odds] 已保存 {len(result['outright'])} 条冠军赔率 → {cache_path}")

    # 同时抓取小组出线赔率（下一版实现）
    # TODO: fetch_group_odds()
    return result


def odds_to_prob(odd: float) -> float:
    """将赔率转换为隐含概率（未归一化）。"""
    if odd <= 1.0:
        return 0.0
    return 1.0 / odd


def merge_odds_to_elo(odds_data: dict, elo_data: dict, alpha: float = 0.6) -> dict:
    """
    将赔率隐含概率融合到 ELO 数据中，生成综合实力评分。
    alpha: ELO 权重（0~1），默认 0.6

    elo_data:  {"ESP": 2100, "FRA": 2080, ...}
    odds_data: {"outright": [{"team":"ESP", "odd":5.75}, ...]}
    返回新的评分字典，值域与 ELO 相近。
    """
    if not odds_data.get("outright"):
        print("[odds] 无赔率数据，使用纯 ELO 评分")
        return elo_data

    # 构建 球队代码 → 赔率隐含概率
    odds_probs = {}
    for entry in odds_data["outright"]:
        team = entry.get("team", "")
        odd = entry.get("odd", 0)
        if team and odd > 1.0:
            odds_probs[team] = odds_to_prob(odd)

    if not odds_probs:
        return elo_data

    # 归一化（赔率隐含概率之和 > 1，需要缩放）
    total_prob = sum(odds_probs.values())
    if total_prob > 0:
        odds_probs = {k: v / total_prob for k, v in odds_probs.items()}

    # 融合：综合评分 = alpha * ELO评分 + (1-alpha) * 赔率评分
    # 将赔率概率映射到一个类 ELO 的数值（约 800~2000）
    merged = {}
    for team, elo in elo_data.items():
        prob = odds_probs.get(team, 0)
        if prob > 0:
            # 将概率映射到 ELO 量级
            odds_score = 800 + 1200 * (prob ** 0.33)
            merged[team] = alpha * elo + (1 - alpha) * odds_score
        else:
            merged[team] = elo
    return merged


if __name__ == "__main__":
    data = fetch_odds(use_cache=False)
    print(json.dumps(data, ensure_ascii=False, indent=2))
