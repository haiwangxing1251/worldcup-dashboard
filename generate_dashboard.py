"""
2026 世界杯预测 — 自包含仪表盘生成器
======================================

供 GitHub Actions 每小时调用：
  1. 从 openfootball/worldcup.json 获取最新赛程/比分
  2. 更新 ELO 评分（基于真实赛果）
  3. 运行 10,000 次蒙特卡洛模拟
  4. 生成完整手机端适配 HTML → docs/index.html

纯 Python 标准库，零外部依赖。
"""

import json
import os
import sys
import time
from datetime import datetime

# 确保 src/ 在导入路径中
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, "src")
sys.path.insert(0, SRC_DIR)

from worldcup_api import (
    get_all_matches, get_finished_matches, get_match_results_for_elo,
    get_tournament_status, get_today_matches,
)
from simulator import WorldCupSimulator
from report import generate_html_report, save_report, cn

# ============================================================
# 路径配置
# ============================================================
DATA_DIR = os.path.join(BASE_DIR, "data")
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")
ELO_FILE = os.path.join(DATA_DIR, "elo_ratings.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "docs", "index.html")

# 模拟参数
NUM_SIMS = 10_000
SEED = 42

# ============================================================
# ELO 更新
# ============================================================

def update_elo_from_match_results(elo_path: str, results: list) -> dict:
    """
    根据真实赛果更新 ELO 评分。

    K = 30（世界杯权重）
    ELO_new = ELO_old + K × (实际得分 - 预期得分)
    """
    with open(elo_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    teams = data.get("teams", {})
    K = 30

    updated_count = 0
    for match in results:
        a = match.get("team_a", "")
        b = match.get("team_b", "")
        ga = match.get("goals_a", 0)
        gb = match.get("goals_b", 0)

        if a not in teams or b not in teams:
            continue

        elo_a = teams[a]["elo"]
        elo_b = teams[b]["elo"]

        # 预期得分
        expected_a = 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))
        expected_b = 1.0 - expected_a

        # 实际得分
        if ga > gb:
            actual_a, actual_b = 1.0, 0.0
        elif gb > ga:
            actual_a, actual_b = 0.0, 1.0
        else:
            actual_a, actual_b = 0.5, 0.5

        teams[a]["elo"] = round(elo_a + K * (actual_a - expected_a), 2)
        teams[b]["elo"] = round(elo_b + K * (actual_b - expected_b), 2)

        # 标记更新时间
        teams[a]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        teams[b]["last_updated"] = datetime.now().strftime("%Y-%m-%d")

        updated_count += 1

    # 写回文件
    data["teams"] = teams
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    with open(elo_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  ELO 更新: {updated_count} 场比赛（{len(results)} 场赛果）")
    return data


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("🔮 2026 世界杯预测引擎 — 自动仪表盘生成")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ---- 第 1 步：获取实时比赛数据 ----
    print("\n[1/4] 📡 从 openfootball API 获取实时数据...")
    t0 = time.time()

    try:
        tournament = get_tournament_status()
        print(f"  总场次: {tournament['total_matches']}")
        print(f"  已完赛: {tournament['finished_matches']}")
        print(f"  今日:   {tournament['today_matches']}")
    except Exception as e:
        print(f"  ⚠️ API 获取失败: {e}")
        tournament = {"finished_matches": 0, "today_matches": 0, "total_matches": 104}

    # ---- 第 2 步：获取赛果并更新 ELO ----
    print("\n[2/4] 📊 更新 ELO 评分...")

    try:
        results = get_match_results_for_elo()
        print(f"  获取到 {len(results)} 场已完赛比分")
    except Exception as e:
        print(f"  ⚠️ 赛果获取失败: {e}")
        results = []

    if results:
        elo_data = update_elo_from_match_results(ELO_FILE, results)
        num_teams_updated = sum(
            1 for t in elo_data.get("teams", {}).values()
            if t.get("last_updated") == datetime.now().strftime("%Y-%m-%d")
        )
        print(f"  ELO 数据共 {len(elo_data['teams'])} 支球队")
    else:
        num_teams_updated = 0

    # ---- 第 3 步：蒙特卡洛模拟 ----
    print(f"\n[3/4] 🎲 运行 {NUM_SIMS:,} 次蒙特卡洛模拟...")

    sim = WorldCupSimulator(
        GROUPS_FILE, ELO_FILE,
        num_sims=NUM_SIMS, seed=SEED,
        completed_matches=results,
    )
    sim.run(progress_callback=lambda c, t: print(
        f"\r  模拟中... {c}/{t} ({c/t*100:.0f}%)", end="", flush=True
    ))
    print()

    ranked = sim.get_ranked_results()
    difficulties = sim.get_group_difficulty()
    stats = sim.stats

    print(f"  完成! 夺冠热门: {cn(ranked[0]['name'])} ({ranked[0]['champion_pct']:.1f}%)")
    print(f"  生成 {len(ranked)} 支球队排名")

    # ---- 第 4 步：生成 HTML 仪表盘 ----
    print("\n[4/4] 📄 生成 HTML 仪表盘...")

    sync_info = {
        "matches_found": len(results),
        "elo_updated": num_teams_updated,
    }

    html = generate_html_report(
        ranked, difficulties, stats,
        num_sims=NUM_SIMS,
        elo_source_date=datetime.now().strftime("%Y-%m-%d"),
        sync_info=sync_info,
    )

    # 在 HTML 头部插入自动刷新元标签
    refresh_meta = '<meta http-equiv="refresh" content="3600">\n'
    html = html.replace("<head>", "<head>\n" + refresh_meta)

    save_report(html, OUTPUT_FILE)

    elapsed = time.time() - t0
    print(f"\n✅ 全部完成! 耗时 {elapsed:.1f}s")
    print(f"   仪表盘: {OUTPUT_FILE}")
    print(f"   球队数: {len(ranked)}")
    print(f"   赛果:   {len(results)} 场")
    print(f"   ELO:    {num_teams_updated} 队已更新")


if __name__ == "__main__":
    main()
