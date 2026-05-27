"""
2026 世界杯实时仪表盘服务器
==============================
零依赖（纯标准库 http.server），启动后浏览器访问：
  http://localhost:8888

API 端点：
  GET  /                  — 实时仪表盘 HTML
  GET  /api/predictions   — JSON：当前预测数据
  POST /api/sync          — 触发数据同步 + 重新模拟
  GET  /api/status        — JSON：服务状态
  GET  /api/matches       — JSON：已完赛真实比分

用法：
  python live_server.py [--port 8888] [--sims 10000] [--seed 42]
"""

import json
import os
import sys
import time
import socket
import threading
import urllib.parse
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# 添加 src 到搜索路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from simulator import WorldCupSimulator
from data_fetcher import sync_all
from report import generate_html_report, cn, gcn, TEAM_NAMES_CN, GROUP_NAMES_CN
from schedule import build_full_schedule, get_upcoming_summary, get_tournament_progress, get_match_predictions

# 世界杯实时数据 API（openfootball/worldcup.json）
try:
    from worldcup_api import (
        get_all_matches, get_today_matches, get_finished_matches,
        get_match_results_for_elo, get_tournament_status,
    )
    HAS_WORLDCUP_API = True
except ImportError:
    HAS_WORLDCUP_API = False
    print("  ⚠️  worldcup_api 模块不可用，将使用本地数据")

# ============================================================
# 全局状态（线程安全）
# ============================================================
STATE_LOCK = threading.Lock()

class ServerState:
    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.groups_file = os.path.join(self.base_dir, "data", "groups.json")
        self.elo_file = os.path.join(self.base_dir, "data", "elo_ratings.json")
        self.num_sims = 10000
        self.seed = 42
        self.simulator = None
        self.results = []
        self.difficulties = []
        self.last_sim_time = None
        self.last_sync_time = None
        self.sync_status = "空闲"
        self.matches_found = 0
        self.elo_from_web = 0
        # 从本地缓存文件统计 ELO 球队数
        self.elo_from_local = self._count_local_elo()
        self._initialized = False
        # 赛程数据（懒加载）
        self._schedule_data = None
        self._schedule_progress = None
        # 今日比赛预测
        self.current_match_date = None  # None = 自动取第一个比赛日
        self._teams_lookup = {}  # English name -> code
        self._build_teams_lookup()
        # 全自动同步
        self.auto_sync_interval = 7200  # 默认 2 小时
        self.auto_sync_enabled = True
        self.next_auto_sync_time = None
        self._auto_sync_stop = threading.Event()

    def _count_local_elo(self):
        """统计本地缓存 ELO 文件中的球队数量。"""
        try:
            if os.path.exists(self.elo_file):
                with open(self.elo_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return len(data.get("teams", {}))
        except Exception:
            pass
        return 0

    def _build_teams_lookup(self):
        """Build English team name -> code mapping from groups and ELO data."""
        try:
            if os.path.exists(self.groups_file):
                with open(self.groups_file, "r", encoding="utf-8") as f:
                    groups = json.load(f).get("groups", {})
                for grp_name, teams in groups.items():
                    for t in teams:
                        self._teams_lookup[t["name"]] = t["code"]
        except Exception:
            pass
        # Supplement from ELO file
        try:
            if os.path.exists(self.elo_file):
                with open(self.elo_file, "r", encoding="utf-8") as f:
                    elo = json.load(f).get("teams", {})
                for code, info in elo.items():
                    name = info.get("name", "")
                    if name and name not in self._teams_lookup:
                        self._teams_lookup[name] = code
        except Exception:
            pass

    def get_today_predictions(self) -> dict:
        """Get today's match predictions with win/draw/loss probabilities and expected goals."""
        self._load_schedule()

        # Determine effective date (default to first match day)
        if self.current_match_date is None:
            all_dates = sorted(set(m["date"] for m in self._schedule_data))
            self.current_match_date = all_dates[0] if all_dates else datetime.now().strftime("%Y-%m-%d")

        # Load ELO data fresh each time (so sync updates take effect)
        try:
            with open(self.elo_file, "r", encoding="utf-8") as f:
                elo_data = json.load(f).get("teams", {})
        except Exception:
            elo_data = {}

        result = get_match_predictions(
            self._schedule_data,
            self.current_match_date,
            elo_data,
            self._teams_lookup,
        )

        if result is None:
            return {"status": "no_data", "message": "无比赛数据"}
        result["status"] = "ok"
        return result

    def advance_match_day(self) -> dict:
        """Advance to the next match day and return predictions for that day."""
        self._load_schedule()
        all_dates = sorted(set(m["date"] for m in self._schedule_data))

        if self.current_match_date is None:
            self.current_match_date = all_dates[0] if all_dates else datetime.now().strftime("%Y-%m-%d")
        else:
            try:
                idx = all_dates.index(self.current_match_date)
                if idx < len(all_dates) - 1:
                    self.current_match_date = all_dates[idx + 1]
            except ValueError:
                self.current_match_date = all_dates[0]

        return self.get_today_predictions()

    def _load_schedule(self):
        """懒加载赛程数据。"""
        if self._schedule_data is None:
            self._schedule_data = build_full_schedule(self.groups_file)
            self._schedule_progress = get_tournament_progress(self._schedule_data)

    def get_schedule_json(self, upcoming_days: int = 30) -> dict:
        """获取赛程摘要 JSON。"""
        self._load_schedule()
        upcoming = get_upcoming_summary(self._schedule_data, days=upcoming_days)
        return {
            "status": "ok",
            "progress": self._schedule_progress,
            "upcoming": upcoming,
        }

    def init_simulator(self):
        """初始化模拟器并运行首次模拟。"""
        if not self._initialized:
            self.simulator = WorldCupSimulator(
                self.groups_file, self.elo_file,
                num_sims=self.num_sims, seed=self.seed
            )
            self._initialized = True

    def run_simulation(self):
        """运行模拟并更新缓存结果。"""
        with STATE_LOCK:
            self.init_simulator()
            self.sync_status = "模拟中……"
        try:
            stats = self.simulator.run()
            results = self.simulator.get_ranked_results()
            difficulties = self.simulator.get_group_difficulty()
            with STATE_LOCK:
                self.results = results
                self.difficulties = difficulties
                self.last_sim_time = datetime.now().isoformat()
                self.sync_status = "空闲"
        except Exception as e:
            with STATE_LOCK:
                self.sync_status = f"模拟失败: {e}"

    def sync_data(self):
        """同步最新数据并重新模拟。"""
        with STATE_LOCK:
            self.sync_status = "同步数据中……"
        try:
            # 1. 从 worldcup_api 获取实时赛果并融入 ELO
            if HAS_WORLDCUP_API:
                try:
                    api_results = get_match_results_for_elo()
                    if api_results:
                        # 读取当前 ELO
                        with open(self.elo_file, "r", encoding="utf-8") as f:
                            elo_data = json.load(f).get("teams", {})
                        # 根据赛果更新 ELO
                        from data_fetcher import update_elo_from_results
                        updated = update_elo_from_results(elo_data, api_results)
                        # 写回文件
                        from data_fetcher import save_elo_data
                        save_elo_data(updated, self.elo_file)
                        with STATE_LOCK:
                            self.matches_found = len(api_results)
                            self.elo_from_web = len(updated)
                        print(f"  [API] 从 openfootball 获取到 {len(api_results)} 场赛果，已更新 ELO")
                except Exception as e:
                    print(f"  [API] 赛果获取失败: {e}")
            
            # 2. 从网络抓取最新 ELO 评分
            result = sync_all(self.elo_file, self.groups_file)
            with STATE_LOCK:
                if not self.matches_found:
                    self.matches_found = result["matches_found"]
                self.elo_from_web = result["elo_from_web"]
                self.last_sync_time = datetime.now().isoformat()
                self.sync_status = "重新模拟中……"
            # 重建模拟器以加载新数据
            with STATE_LOCK:
                self.simulator = WorldCupSimulator(
                    self.groups_file, self.elo_file,
                    num_sims=self.num_sims, seed=self.seed
                )
            self.run_simulation()
        except Exception as e:
            with STATE_LOCK:
                self.sync_status = f"同步失败: {e}"

    def get_predictions_json(self) -> dict:
        """获取当前预测的 JSON 表示。"""
        with STATE_LOCK:
            if not self.results:
                return {"status": "no_data", "message": "模拟尚未完成"}
            top20 = []
            for i, r in enumerate(self.results[:20]):
                top20.append({
                    "rank": i + 1,
                    "name": TEAM_NAMES_CN.get(r["name"], r["name"]),
                    "name_en": r["name"],
                    "code": r["code"],
                    "group": GROUP_NAMES_CN.get(r["group"], r["group"]),
                    "elo": round(r["elo"]),
                    "elo_estimated": r["elo_estimated"],
                    "champion_pct": round(r["champion_pct"], 1),
                    "final_pct": round(r["final_pct"], 1),
                    "sf_pct": round(r["sf_pct"], 1),
                    "qf_pct": round(r["qf_pct"], 1),
                    "r16_pct": round(r["r16_pct"], 1),
                    "r32_pct": round(r["r32_pct"], 1),
                })
            return {
                "status": "ok",
                "num_sims": self.num_sims,
                "total_teams": len(self.results),
                "last_sim_time": self.last_sim_time,
                "last_sync_time": self.last_sync_time,
                "sync_status": self.sync_status,
                "matches_found": self.matches_found,
                "elo_from_web": self.elo_from_web,
                "predictions": top20,
                "all_predictions": [
                    {
                        "rank": i + 1,
                        "name": TEAM_NAMES_CN.get(r["name"], r["name"]),
                        "group": GROUP_NAMES_CN.get(r["group"], r["group"]),
                        "elo": round(r["elo"]),
                        "elo_estimated": r["elo_estimated"],
                        "champion_pct": round(r["champion_pct"], 1),
                        "final_pct": round(r["final_pct"], 1),
                        "sf_pct": round(r["sf_pct"], 1),
                        "qf_pct": round(r["qf_pct"], 1),
                        "r16_pct": round(r["r16_pct"], 1),
                        "r32_pct": round(r["r32_pct"], 1),
                        "group_exit_pct": round(r["group_exit_pct"], 1),
                    }
                    for i, r in enumerate(self.results)
                ],
            }


    def start_auto_sync(self):
        """启动后台自动同步线程。"""
        # 立即设定首次同步时间，避免前端显示空值
        with STATE_LOCK:
            self.next_auto_sync_time = datetime.now().timestamp() + self.auto_sync_interval

        def _auto_sync_loop():
            while not self._auto_sync_stop.is_set():
                # 计算下一次同步时间
                with STATE_LOCK:
                    if self.auto_sync_enabled:
                        self.next_auto_sync_time = (
                            datetime.now().timestamp() + self.auto_sync_interval
                        )
                # 等待间隔时间，每秒检查停止信号和间隔变更
                elapsed = 0
                while elapsed < self.auto_sync_interval:
                    if self._auto_sync_stop.is_set():
                        return
                    time.sleep(1)
                    elapsed += 1
                    # 如果间隔被缩短到小于已等待时间，立即触发
                    if elapsed >= self.auto_sync_interval:
                        break
                if self._auto_sync_stop.is_set():
                    return
                # 执行同步
                with STATE_LOCK:
                    enabled = self.auto_sync_enabled
                if enabled:
                    print(f"\n⏰ 定时自动同步触发 [{datetime.now().strftime('%H:%M:%S')}]")
                    self.sync_data()

        t = threading.Thread(target=_auto_sync_loop, daemon=True)
        t.start()

    def toggle_auto_sync(self) -> dict:
        """切换自动同步开关。"""
        with STATE_LOCK:
            self.auto_sync_enabled = not self.auto_sync_enabled
            if self.auto_sync_enabled:
                self.next_auto_sync_time = (
                    datetime.now().timestamp() + self.auto_sync_interval
                )
            else:
                self.next_auto_sync_time = None
            return {
                "auto_sync_enabled": self.auto_sync_enabled,
                "auto_sync_interval_min": round(self.auto_sync_interval / 60),
                "next_auto_sync_time": (
                    datetime.fromtimestamp(self.next_auto_sync_time).isoformat()
                    if self.next_auto_sync_time else None
                ),
            }

    def set_sync_interval(self, minutes: int) -> dict:
        """设置自动同步间隔（分钟）。"""
        minutes = max(1, min(1440, minutes))  # 限制 1 分钟 ~ 24 小时
        with STATE_LOCK:
            self.auto_sync_interval = minutes * 60
            if self.auto_sync_enabled:
                self.next_auto_sync_time = (
                    datetime.now().timestamp() + self.auto_sync_interval
                )
            return {
                "auto_sync_enabled": self.auto_sync_enabled,
                "auto_sync_interval_min": round(self.auto_sync_interval / 60),
                "next_auto_sync_time": (
                    datetime.fromtimestamp(self.next_auto_sync_time).isoformat()
                    if self.next_auto_sync_time else None
                ),
            }


# ============================================================
# 全局状态实例
# ============================================================
state = ServerState()


# ============================================================
# 仪表盘 HTML（内嵌）
# ============================================================

def get_dashboard_html() -> str:
    """生成实时仪表盘 HTML 页面。"""
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>2026 世界杯实时预测仪表盘</title>
<style>
:root {
  --bg: #0a0e27; --card: #111640; --text: #e8e8ec;
  --text2: #8890b5; --accent: #4fc3f7; --gold: #FFD700;
  --silver: #C0C0C0; --bronze: #CD7F32; --green: #66bb6a;
  --red: #ef5350; --orange: #ff7043;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6;
  min-height: 100vh;
}
.container { max-width: 1300px; margin: 0 auto; padding: 16px; }

/* Header */
.header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 20px; background: var(--card);
  border-radius: 12px; margin-bottom: 16px;
  border: 1px solid rgba(255,255,255,0.06);
  flex-wrap: wrap; gap: 12px;
}
.header h1 {
  font-size: 1.3em;
  background: linear-gradient(90deg, #FFD700, #FFA726, #FFD700);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.header-right {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.status-dot {
  width: 8px; height: 8px; border-radius: 50%; display: inline-block;
}
.status-dot.green { background: var(--green); animation: pulse 2s infinite; }
.status-dot.yellow { background: #FFA726; animation: pulse 1s infinite; }
.status-dot.red { background: var(--red); }
@keyframes pulse {
  0%, 100% { opacity: 1; } 50% { opacity: 0.4; }
}

/* Buttons */
.btn {
  padding: 8px 18px; border: none; border-radius: 8px;
  cursor: pointer; font-size: 0.85em; font-weight: 600;
  transition: all 0.2s;
}
.btn-sync {
  background: linear-gradient(135deg, #1a237e, #0d47a1);
  color: white; border: 1px solid rgba(79,195,247,0.3);
}
.btn-sync:hover { background: linear-gradient(135deg, #283593, #1565c0); }
.btn-sync:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-auto {
  background: var(--card); color: var(--text2);
  border: 1px solid rgba(255,255,255,0.1);
}
.btn-auto.active {
  background: rgba(102,187,106,0.15); color: var(--green);
  border-color: rgba(102,187,106,0.3);
}

/* Sync interval selector */
.sync-interval-select {
  padding: 7px 10px; border-radius: 8px;
  background: var(--card); color: var(--text);
  border: 1px solid rgba(255,255,255,0.1);
  font-size: 0.82em; font-weight: 600; cursor: pointer;
  font-family: inherit;
  transition: all 0.2s;
}
.sync-interval-select:hover { border-color: rgba(79,195,247,0.3); }
.sync-interval-select:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(79,195,247,0.15);
}
.sync-interval-select option {
  background: var(--card); color: var(--text);
  padding: 8px;
}

/* Status bar */
.status-bar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px; margin-bottom: 16px;
}
.status-card {
  background: var(--card); border-radius: 10px;
  padding: 14px; border: 1px solid rgba(255,255,255,0.06);
  display: flex; align-items: center; gap: 10px;
}
.status-card .icon { font-size: 1.5em; }
.status-card .value { font-size: 1.15em; font-weight: 700; }
.status-card .label { font-size: 0.72em; color: var(--text2); }

/* Main content grid */
.main-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
/* ============================================================
   Mobile Responsive Styles (width <= 768px)
   ============================================================ */
@media (max-width: 768px) {
  .container { padding: 8px; }
  .header {
    flex-direction: column; align-items: flex-start; padding: 12px 14px;
    border-radius: 10px; margin-bottom: 10px;
  }
  .header h1 { font-size: 1.05em; }
  .header-right { width: 100%; justify-content: space-between; gap: 6px; }
  .header-right .btn, .header-right select { font-size: 0.75em; padding: 6px 10px; }

  /* Status bar: 2 columns on mobile */
  .status-bar { grid-template-columns: 1fr 1fr; gap: 6px; }
  .status-card { padding: 10px; border-radius: 8px; }
  .status-card .icon { font-size: 1.2em; }
  .status-card .value { font-size: 0.95em; }
  .status-card .label { font-size: 0.65em; }

  /* Main grid: single column */
  .main-grid { grid-template-columns: 1fr; gap: 10px; }
  .card { padding: 14px; border-radius: 10px; }
  .card h2 { font-size: 1em; margin-bottom: 10px; }

  /* Champion chart: compact */
  .champion-name { width: 70px; font-size: 0.72em; }
  .champion-rank { width: 22px; height: 22px; font-size: 0.7em; }
  .champion-bar-bg { height: 14px; }
  .champion-pct { width: 42px; font-size: 0.72em; }
  .champion-row { gap: 4px; padding: 2px 0; }

  /* Table: horizontal scroll */
  .tbl-wrap { max-height: 50vh; }
  .tbl { font-size: 0.7em; }
  .tbl th, .tbl td { padding: 5px 6px; }

  /* Group difficulty: single column */
  .group-grid { grid-template-columns: 1fr; gap: 5px; }
  .group-item { padding: 8px 12px; }

  /* Schedule: single column, full width */
  .schedule-summary { gap: 8px; }
  .schedule-summary .sstat { min-width: 70px; padding: 8px 10px; }
  .schedule-summary .sstat .val { font-size: 1.1em; }
  .schedule-list { flex-direction: column; gap: 5px; }
  .schedule-day { max-width: 100%; min-width: 0; flex: none; }

  /* Today's matches: compact */
  .match-item { padding: 10px 12px; margin-bottom: 8px; }
  .match-teams-row { gap: 10px; }
  .team-block { min-width: 70px; }
  .team-block .tname { font-size: 0.85em; }
  .team-block .telo { font-size: 0.62em; }
  .prob-row { gap: 4px; }
  .prob-col .plabel { font-size: 0.65em; }
  .goals-row { font-size: 0.72em; }

  /* Today actions */
  .today-actions { flex-direction: column; gap: 8px; }
  .btn-next-day { width: 100%; padding: 10px; font-size: 0.9em; }
  .today-date-header { font-size: 0.85em; display: block; margin-left: 0; }

  /* Footer */
  .footer { padding: 12px; font-size: 0.65em; }
}
/* =========== Mobile Responsive End =========== */

.card {
  background: var(--card); border-radius: 12px;
  padding: 20px; border: 1px solid rgba(255,255,255,0.06);
}
.card h2 { font-size: 1.1em; color: var(--accent); margin-bottom: 14px; }

/* Champion chart */
.champion-row {
  display: flex; align-items: center; gap: 8px; padding: 3px 0;
}
.champion-rank {
  width: 26px; height: 26px; display: flex;
  align-items: center; justify-content: center;
  border-radius: 50%; font-weight: 700; font-size: 0.78em;
  flex-shrink: 0;
}
.champion-rank.g1 { background: var(--gold); color: #1a1a2e; }
.champion-rank.g2 { background: var(--silver); color: #1a1a2e; }
.champion-rank.g3 { background: var(--bronze); color: #1a1a2e; }
.champion-name {
  width: 100px; font-weight: 600; font-size: 0.82em;
  flex-shrink: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.champion-bar-bg {
  flex: 1; height: 18px; background: rgba(255,255,255,0.05);
  border-radius: 9px; overflow: hidden;
}
.champion-bar-fill { height: 100%; border-radius: 9px; transition: width 0.5s ease; }
.champion-pct { width: 50px; text-align: right; font-weight: 700; font-size: 0.82em; flex-shrink: 0; }

/* Table */
.tbl-wrap { max-height: 60vh; overflow-y: auto; border-radius: 8px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 0.78em; }
.tbl th {
  text-align: left; padding: 8px 10px;
  background: rgba(79,195,247,0.08); color: var(--accent);
  font-weight: 600; position: sticky; top: 0; z-index: 2;
}
.tbl td { padding: 6px 10px; border-bottom: 1px solid rgba(255,255,255,0.04); }
.tbl tr:hover { background: rgba(255,255,255,0.02); }
.tbl .r { text-align: right; }
.tbl .highlight { background: rgba(255,215,0,0.04); }

/* Group difficulty */
.group-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 8px; }
.group-item {
  padding: 10px 14px; border-radius: 8px;
  background: rgba(255,255,255,0.03); border-left: 3px solid #555;
}
.group-item.death { border-left-color: var(--red); }
.group-item .gname { font-weight: 700; font-size: 0.9em; }
.group-item .gteams { color: var(--text2); font-size: 0.78em; margin-top: 2px; }

/* Log */
#log { margin-top: 16px; color: var(--text2); font-size: 0.72em; line-height: 1.8; }

/* Loading spinner */
.spin {
  display: inline-block; width: 14px; height: 14px;
  border: 2px solid rgba(255,255,255,0.2);
  border-top-color: var(--accent); border-radius: 50%;
  animation: spin 0.8s linear infinite;
  vertical-align: middle; margin-right: 4px;
}
@keyframes spin { to { transform: rotate(360deg); } }

.footer {
  text-align: center; padding: 20px; color: var(--text2);
  font-size: 0.72em; margin-top: 16px;
}

/* Diff highlight */
.val-up { color: var(--green); }
.val-down { color: var(--red); }

/* Schedule module */
.schedule-summary {
  display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap;
}
.schedule-summary .sstat {
  background: rgba(79,195,247,0.06); border-radius: 8px;
  padding: 12px 16px; min-width: 100px; text-align: center;
}
.schedule-summary .sstat .val { font-size: 1.3em; font-weight: 700; color: var(--accent); }
.schedule-summary .sstat .lbl { font-size: 0.72em; color: var(--text2); margin-top: 2px; }
.schedule-list { display: flex; flex-wrap: wrap; gap: 6px; }
.schedule-day {
  background: rgba(255,255,255,0.03); border-radius: 8px;
  padding: 10px 14px; min-width: 160px; flex: 1 1 180px;
  border-left: 3px solid #444; max-width: 220px;
}
.schedule-day.today {
  border-left-color: var(--accent);
  background: rgba(79,195,247,0.08);
}
.schedule-day .dhead {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 6px;
}
.schedule-day .ddate { font-weight: 700; font-size: 0.82em; }
.schedule-day .dweek { font-size: 0.7em; color: var(--text2); }
.schedule-day .dinfo {
  font-size: 0.78em; color: var(--text2); line-height: 1.6;
}
.schedule-day .dinfo .teams-count {
  font-weight: 700; color: #FFD700;
}
.schedule-day .dinfo .matches-count {
  color: var(--accent);
}
.schedule-day .dstage {
  font-size: 0.68em; color: var(--text2); margin-top: 4px;
  padding-top: 4px; border-top: 1px solid rgba(255,255,255,0.06);
}
.schedule-day .dcountdown {
  font-size: 0.75em; color: var(--accent); margin-top: 4px;
  font-weight: 600;
}

/* Today's Matches Prediction */
.match-item {
  background: rgba(255,255,255,0.03);
  border-radius: 10px; padding: 14px 16px;
  margin-bottom: 10px;
  border: 1px solid rgba(255,255,255,0.05);
  transition: border-color 0.2s;
}
.match-item:hover { border-color: rgba(79,195,247,0.2); }
.match-item.tbd {
  opacity: 0.5; border-style: dashed;
}
.match-header-row {
  display: flex; justify-content: space-between;
  margin-bottom: 10px; font-size: 0.72em; color: var(--text2);
}
.match-group-tag {
  background: rgba(79,195,247,0.12); color: var(--accent);
  padding: 2px 8px; border-radius: 4px; font-weight: 600;
}
.match-teams-row {
  display: flex; align-items: center; justify-content: center;
  gap: 16px; margin-bottom: 12px;
}
.team-block {
  text-align: center; min-width: 100px;
}
.team-block .tname {
  font-weight: 700; font-size: 1em;
}
.team-block .telo {
  font-size: 0.7em; color: var(--text2);
}
.team-vs {
  font-size: 1.1em; font-weight: 900;
  color: rgba(255,255,255,0.15);
}
.prob-row {
  display: flex; gap: 8px; margin-bottom: 8px;
}
.prob-col {
  flex: 1; text-align: center;
}
.prob-col .plabel {
  font-size: 0.72em; margin-bottom: 3px; font-weight: 600;
}
.prob-col.home .plabel { color: #42a5f5; }
.prob-col.draw .plabel { color: #9e9e9e; }
.prob-col.away .plabel { color: #ef5350; }
.prob-bar-wrap {
  height: 8px; background: rgba(255,255,255,0.06);
  border-radius: 4px; overflow: hidden;
}
.prob-bar {
  height: 100%; border-radius: 4px; transition: width 0.5s ease;
}
.prob-bar.home { background: linear-gradient(90deg, #1565c0, #42a5f5); }
.prob-bar.draw { background: linear-gradient(90deg, #616161, #9e9e9e); }
.prob-bar.away { background: linear-gradient(90deg, #c62828, #ef5350); }
.goals-row {
  text-align: center; font-size: 0.78em; color: var(--text2);
  padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.04);
}
.goals-row .gval { font-weight: 700; }
.goals-row .ghome { color: #42a5f5; }
.goals-row .gaway { color: #ef5350; }
.today-empty {
  text-align: center; padding: 30px; color: var(--text2);
  font-size: 0.9em;
}
.today-actions {
  display: flex; align-items: center; justify-content: center;
  gap: 16px; padding-top: 14px; margin-top: 10px;
  border-top: 1px solid rgba(255,255,255,0.06);
}
.btn-next-day {
  padding: 8px 20px; border: none; border-radius: 8px;
  cursor: pointer; font-size: 0.85em; font-weight: 600;
  background: linear-gradient(135deg, #1b5e20, #2e7d32);
  color: white; border: 1px solid rgba(102,187,106,0.3);
  transition: all 0.2s;
}
.btn-next-day:hover {
  background: linear-gradient(135deg, #2e7d32, #388e3c);
}
.btn-next-day:disabled { opacity: 0.4; cursor: not-allowed; }
.today-progress-text {
  font-size: 0.78em; color: var(--text2);
}
.today-progress-text span { color: var(--accent); font-weight: 700; }
.today-date-header {
  display: inline-block; font-weight: 600; color: #FFD700;
  font-size: 1em; margin-left: 8px;
}
.tournament-timeline {
  display: flex; align-items: center; gap: 4px;
  font-size: 0.72em; color: var(--text2); margin-bottom: 4px;
}
.tournament-timeline .dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: rgba(255,255,255,0.15);
}
.tournament-timeline .dot.active { background: var(--accent); }
.tournament-timeline .dot.done { background: var(--green); }
</style>
</head>
<body>

<div class="container">

<!-- Header -->
<div class="header">
  <h1>&#x26BD; 2026 世界杯实时预测</h1>
  <div class="header-right">
    <span id="conn-status">
      <span class="status-dot green"></span> 已连接
    </span>
    <button class="btn btn-auto active" id="btn-auto-sync" onclick="toggleAutoSync()">
      &#x1F504; 自动同步: 开
    </button>
    <select class="sync-interval-select" id="sync-interval" onchange="setSyncInterval()">
      <option value="1">每 1 分钟</option>
      <option value="5">每 5 分钟</option>
      <option value="10">每 10 分钟</option>
      <option value="30">每 30 分钟</option>
      <option value="60">每 60 分钟</option>
      <option value="120" selected>每 2 小时</option>
    </select>
    <button class="btn btn-auto" id="btn-auto" onclick="toggleAuto()">
      &#x1F4CA; 自动刷新: 开
    </button>
    <button class="btn btn-sync" id="btn-sync" onclick="syncData()">
      &#x1F4E1; 同步最新数据
    </button>
  </div>
</div>

<!-- Status Cards -->
<div class="status-bar">
  <div class="status-card">
    <div class="icon">&#x1F3C6;</div>
    <div>
      <div class="value" id="st-champion">--</div>
      <div class="label">最大热门</div>
    </div>
  </div>
  <div class="status-card">
    <div class="icon">&#x1F4CA;</div>
    <div>
      <div class="value" id="st-sims">--</div>
      <div class="label">模拟次数</div>
    </div>
  </div>
  <div class="status-card">
    <div class="icon">&#x1F310;</div>
    <div>
      <div class="value" id="st-elo-web">--</div>
      <div class="label">网络 ELO</div>
    </div>
  </div>
  <div class="status-card">
    <div class="icon">&#x26BD;</div>
    <div>
      <div class="value" id="st-matches">--</div>
      <div class="label">已完赛比分</div>
    </div>
  </div>
  <div class="status-card">
    <div class="icon">&#x1F552;</div>
    <div>
      <div class="value" id="st-updated">--</div>
      <div class="label">最后更新</div>
    </div>
  </div>
  <div class="status-card">
    <div class="icon">&#x23F0;</div>
    <div>
      <div class="value" id="st-next-sync">--</div>
      <div class="label">下次自动同步</div>
    </div>
  </div>
</div>

<!-- Main Grid -->
<div class="main-grid">

<!-- Champion Probability -->
<div class="card" id="champion-card">
  <h2>&#x1F3C6; 夺冠概率 Top 20</h2>
  <div id="champion-list">加载中……</div>
</div>

<!-- Group Difficulty -->
<div class="card">
  <h2>&#x1F4A5; 小组难度实时排名</h2>
  <div class="group-grid" id="group-list">加载中……</div>
</div>

</div>

<!-- Match Schedule -->
<div class="card" style="margin-top:16px;">
  <h2>&#x1F4C5; 比赛日程</h2>
  <div class="schedule-summary" id="schedule-summary"></div>
  <div id="schedule-list">加载中……</div>
</div>

<!-- Today's Match Predictions -->
<div class="card" style="margin-top:16px;" id="today-card">
  <h2>
    &#x1F4CA; 今日比赛预测
    <span class="today-date-header" id="today-date-header"></span>
  </h2>
  <div class="tournament-timeline" id="today-timeline"></div>
  <div id="today-matches">加载中……</div>
  <div class="today-actions" id="today-actions" style="display:none;">
    <button class="btn-next-day" id="btn-next-day" onclick="advanceMatchDay()">
      &#x25B6; 下一比赛日
    </button>
    <span class="today-progress-text" id="today-progress-text"></span>
  </div>
</div>

<!-- Full Probability Table -->
<div class="card" style="margin-top:16px;">
  <h2>&#x1F4CA; 全部 48 队晋级概率矩阵</h2>
  <div class="tbl-wrap">
    <table class="tbl">
      <thead>
        <tr>
          <th>#</th><th>球队</th><th>小组</th><th>ELO</th>
          <th class="r">夺冠</th><th class="r">决赛</th><th class="r">四强</th>
          <th class="r">八强</th><th class="r">十六强</th>
          <th class="r">三十二强</th><th class="r">小组出局</th>
        </tr>
      </thead>
      <tbody id="full-table">加载中……</tbody>
    </table>
  </div>
</div>

<!-- Log -->
<div id="log"></div>

<div class="footer">
  2026 世界杯预测引擎 &middot; ELO + 泊松分布 + 蒙特卡洛 &middot;
  数据源：FIFA / eloratings.net / worldfootballrankings.com
</div>

</div>

<script>
// ============================================================
// Dashboard JS: auto-refresh polling + sync
// ============================================================

const API_BASE = '';
const REFRESH_INTERVAL = 30000;  // 30 秒自动刷新
const SIM_PROGRESS_INTERVAL = 2000;  // 模拟中轮询间隔

let autoRefresh = true;
let autoSync = true;
let refreshTimer = null;
let prevData = null;
let logLines = [];

function log(msg) {
  const now = new Date().toLocaleTimeString('zh-CN');
  logLines.push(`[${now}] ${msg}`);
  if (logLines.length > 20) logLines.shift();
  document.getElementById('log').innerHTML = logLines.join('<br>');
}

function toggleAuto() {
  autoRefresh = !autoRefresh;
  const btn = document.getElementById('btn-auto');
  if (autoRefresh) {
    btn.classList.add('active');
    btn.innerHTML = '&#x1F4CA; 自动刷新: 开';
    startAutoRefresh();
    log('自动刷新已开启（每 30 秒）');
  } else {
    btn.classList.remove('active');
    btn.innerHTML = '&#x1F4CA; 自动刷新: 关';
    stopAutoRefresh();
    log('自动刷新已关闭');
  }
}

async function toggleAutoSync() {
  try {
    const resp = await fetch(API_BASE + '/api/auto-sync/toggle', { method: 'POST' });
    const result = await resp.json();
    autoSync = result.auto_sync_enabled;
    const btn = document.getElementById('btn-auto-sync');
    if (autoSync) {
      btn.classList.add('active');
      btn.innerHTML = '&#x1F504; 自动同步: 开';
      log('自动同步已开启');
    } else {
      btn.classList.remove('active');
      btn.innerHTML = '&#x1F504; 自动同步: 关';
      log('自动同步已关闭');
    }
    updateNextSyncTime(result.next_auto_sync_time);
    // 同步下拉框
    if (result.auto_sync_interval_min) {
      document.getElementById('sync-interval').value = String(result.auto_sync_interval_min);
    }
  } catch (e) {
    log('切换自动同步失败: ' + e.message);
  }
}

async function setSyncInterval() {
  const select = document.getElementById('sync-interval');
  const minutes = parseInt(select.value);
  try {
    const resp = await fetch(API_BASE + '/api/auto-sync/interval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ minutes: minutes })
    });
    const result = await resp.json();
    updateNextSyncTime(result.next_auto_sync_time);
    log('同步间隔已改为每 ' + minutes + ' 分钟');
  } catch (e) {
    log('设置间隔失败: ' + e.message);
  }
}

function updateNextSyncTime(isoTime) {
  const el = document.getElementById('st-next-sync');
  if (!isoTime) {
    el.textContent = '已关闭';
    el.style.color = '#ef5350';
    return;
  }
  const target = new Date(isoTime);
  const now = new Date();
  const diffSec = Math.max(0, Math.floor((target - now) / 1000));
  const h = Math.floor(diffSec / 3600);
  const m = Math.floor((diffSec % 3600) / 60);
  const s = diffSec % 60;
  if (diffSec <= 0) {
    el.textContent = '即将同步...';
    el.style.color = '#FFA726';
  } else {
    el.textContent = `${h}时${m}分${s}秒`;
    el.style.color = '';
  }
  // 每秒更新倒计时
  setTimeout(() => updateNextSyncTime(isoTime), 1000);
}

function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    fetchPredictions();
    fetchTodayMatches();
  }, REFRESH_INTERVAL);
}

function stopAutoRefresh() {
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
}

function fmtTime(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function pctColor(pct) {
  if (pct >= 15) return '#FFD700';
  if (pct >= 8) return '#FFA726';
  if (pct >= 3) return '#ef5350';
  if (pct >= 1) return '#ab47bc';
  return '#78909c';
}

function barColor(i) {
  const colors = ['#FFD700','#FFA726','#ef5350','#ab47bc','#42a5f5',
                  '#26c6da','#9ccc65','#ff7043','#78909c','#8d6e63',
                  '#FFD700','#FFA726','#ef5350','#ab47bc','#42a5f5',
                  '#26c6da','#9ccc65','#ff7043','#78909c','#8d6e63'];
  return colors[i] || '#78909c';
}

// ============================================================
// Fetch & Render
// ============================================================
async function fetchPredictions() {
  try {
    const resp = await fetch(API_BASE + '/api/predictions');
    const data = await resp.json();

    if (data.status !== 'ok') {
      log('等待模拟完成……');
      return;
    }

    prevData = data;
    renderAll(data);
    updateStatus(data);

    document.getElementById('conn-status').innerHTML =
      '<span class="status-dot green"></span> 已连接';
    log('数据已刷新');
  } catch (e) {
    document.getElementById('conn-status').innerHTML =
      '<span class="status-dot red"></span> 连接失败';
    log('连接失败: ' + e.message);
  }
}

function updateStatus(data) {
  document.getElementById('st-sims').textContent = (data.num_sims || 0).toLocaleString();
  document.getElementById('st-elo-web').textContent = (data.elo_from_web || 0) + ' 队';
  document.getElementById('st-matches').textContent = (data.matches_found || 0) + ' 场';
  document.getElementById('st-updated').textContent = fmtTime(data.last_sim_time);

  if (data.predictions && data.predictions.length > 0) {
    document.getElementById('st-champion').textContent = data.predictions[0].name;
  }

  // 更新自动同步状态
  if (data.auto_sync_enabled !== undefined) {
    autoSync = data.auto_sync_enabled;
    const btn = document.getElementById('btn-auto-sync');
    if (autoSync) {
      btn.classList.add('active');
      btn.innerHTML = '&#x1F504; 自动同步: 开';
    } else {
      btn.classList.remove('active');
      btn.innerHTML = '&#x1F504; 自动同步: 关';
    }
    updateNextSyncTime(data.next_auto_sync_time);
    // 同步下拉框
    if (data.auto_sync_interval_min) {
      document.getElementById('sync-interval').value = String(data.auto_sync_interval_min);
    }
  }
}

function renderAll(data) {
  renderChampionChart(data.predictions);
  renderGroupDifficulty(data);
  renderFullTable(data.all_predictions);
  // Schedule renders independently via its own fetch
}

function renderChampionChart(predictions) {
  if (!predictions || predictions.length === 0) return;
  let html = '<div class="champion-list">';
  const maxPct = predictions[0].champion_pct;

  predictions.forEach((p, i) => {
    let rc = '';
    if (i === 0) rc = 'g1';
    else if (i === 1) rc = 'g2';
    else if (i === 2) rc = 'g3';
    const barW = (p.champion_pct / Math.max(maxPct, 1)) * 100;
    const color = barColor(i);
    const estTag = p.elo_estimated ? ' <span style="color:#ff9800;font-size:0.7em;">估算</span>' : '';
    html += `<div class="champion-row">
      <div class="champion-rank ${rc}">${i+1}</div>
      <div class="champion-name" title="${p.name_en||''}">${p.name}${estTag}</div>
      <div class="champion-bar-bg">
        <div class="champion-bar-fill" style="width:${barW}%; background:${color};"></div>
      </div>
      <div class="champion-pct" style="color:${color}">${p.champion_pct}%</div>
    </div>`;
  });
  html += '</div>';
  document.getElementById('champion-list').innerHTML = html;
}

function renderGroupDifficulty(data) {
  let allTeams = [];
  if (data.all_predictions) {
    // Build group data from all_predictions
    const groupMap = {};
    data.all_predictions.forEach(t => {
      if (!groupMap[t.group]) groupMap[t.group] = [];
      groupMap[t.group].push(t);
    });
    allTeams = Object.entries(groupMap).map(([g, teams]) => {
      const avgElo = teams.reduce((s, t) => s + t.elo, 0) / teams.length;
      const maxElo = Math.max(...teams.map(t => t.elo));
      const minElo = Math.min(...teams.map(t => t.elo));
      return {
        group: g,
        avg_elo: avgElo,
        max_elo: maxElo,
        min_elo: minElo,
        spread: maxElo - minElo,
        teams: teams.map(t => t.name)
      };
    });
    allTeams.sort((a, b) => b.avg_elo - a.avg_elo);
  } else {
    allTeams = data.group_difficulties || [];
  }

  let html = '';
  allTeams.forEach(d => {
    const deathClass = d.avg_elo > 1650 ? 'death' : '';
    const teamsStr = d.teams.join(' · ');
    html += `<div class="group-item ${deathClass}">
      <div class="gname">${d.group} <span style="font-size:0.75em;opacity:0.6">均ELO ${d.avg_elo.toFixed(0)}</span></div>
      <div class="gteams">${teamsStr}</div>
    </div>`;
  });
  document.getElementById('group-list').innerHTML = html;
}

function renderFullTable(predictions) {
  if (!predictions || predictions.length === 0) return;
  let html = '';
  predictions.forEach((p, i) => {
    const hc = i < 3 ? 'highlight' : '';
    const estMark = p.elo_estimated ? ' &#x26A0;' : '';
    html += `<tr class="${hc}">
      <td>${i+1}</td>
      <td><strong>${p.name}</strong>${estMark}</td>
      <td>${p.group}</td>
      <td class="r">${p.elo}</td>
      <td class="r" style="color:${pctColor(p.champion_pct)}">${p.champion_pct}%</td>
      <td class="r" style="color:${pctColor(p.final_pct)}">${p.final_pct}%</td>
      <td class="r">${p.sf_pct}%</td>
      <td class="r">${p.qf_pct}%</td>
      <td class="r">${p.r16_pct}%</td>
      <td class="r">${p.r32_pct}%</td>
      <td class="r" style="color:#78909c">${p.group_exit_pct}%</td>
    </tr>`;
  });
  document.getElementById('full-table').innerHTML = html;
}

// ============================================================
// Sync
// ============================================================
async function syncData() {
  const btn = document.getElementById('btn-sync');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> 同步中...';

  log('开始同步最新数据……');

  try {
    const resp = await fetch(API_BASE + '/api/sync', { method: 'POST' });
    const result = await resp.json();

    if (result.status === 'started') {
      // Poll until done
      log('数据同步已触发，等待模拟完成……');
      await pollSyncProgress();
    } else if (result.status === 'ok') {
      await fetchPredictions();
      log('同步完成！');
    } else {
      log('同步失败: ' + (result.message || '未知错误'));
    }
  } catch (e) {
    log('同步请求失败: ' + e.message);
  }

  btn.disabled = false;
  btn.innerHTML = '&#x1F4E1; 同步最新数据';
}

async function pollSyncProgress() {
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, SIM_PROGRESS_INTERVAL));
    try {
      const resp = await fetch(API_BASE + '/api/status');
      const status = await resp.json();
      if (status.sync_status === '空闲' || status.sync_status.includes('失败')) {
        if (status.last_sim_time) {
          await fetchPredictions();
          log('同步完成！');
        } else if (status.sync_status.includes('失败')) {
          log('同步失败: ' + status.sync_status);
        }
        return;
      }
    } catch (e) {
      // retry
    }
  }
  log('同步超时（2 分钟）');
}

// ============================================================
// Schedule rendering
// ============================================================
const WEEKDAYS_CN = {
  'Monday': '周一', 'Tuesday': '周二', 'Wednesday': '周三',
  'Thursday': '周四', 'Friday': '周五', 'Saturday': '周六', 'Sunday': '周日'
};

async function fetchSchedule() {
  try {
    const resp = await fetch(API_BASE + '/api/schedule?days=28');
    const data = await resp.json();
    if (data.status === 'ok') {
      renderSchedule(data);
    }
  } catch (e) {
    log('赛程加载失败: ' + e.message);
  }
}

function renderSchedule(data) {
  const progress = data.progress;
  const upcoming = data.upcoming;

  // Summary bar
  const todayMatches = upcoming.length > 0 ? upcoming[0].match_count : 0;
  const todayTeams = upcoming.length > 0 ? upcoming[0].team_count : 0;
  const isToday = upcoming.length > 0 && upcoming[0].date === progress.today;

  document.getElementById('schedule-summary').innerHTML =
    '<div class="sstat">' +
      '<div class="val">' + progress.total_teams + '</div>' +
      '<div class="lbl">参赛球队</div>' +
    '</div>' +
    '<div class="sstat">' +
      '<div class="val">' + progress.total_matchdays + '</div>' +
      '<div class="lbl">比赛日</div>' +
    '</div>' +
    '<div class="sstat">' +
      '<div class="val">' + progress.total_matches + '</div>' +
      '<div class="lbl">总场次</div>' +
    '</div>' +
    '<div class="sstat">' +
      '<div class="val">' + progress.remaining_matches + '</div>' +
      '<div class="lbl">剩余场次</div>' +
    '</div>' +
    '<div class="sstat">' +
      '<div class="val">' +
        (isToday ? '<span style="color:#4caf50">' + todayTeams + '队/' + todayMatches + '场</span>' : '--') +
      '</div>' +
      '<div class="lbl">今日比赛</div>' +
    '</div>';

  // Day-by-day list (show first 14 days)
  const showDays = upcoming.slice(0, 14);
  let html = '<div class="schedule-list">';
  showDays.forEach((d, idx) => {
    const isFirstDay = idx === 0;
    const todayClass = isFirstDay && isToday ? ' today' : '';
    const weekdayCN = WEEKDAYS_CN[d.day_of_week] || d.day_of_week;
    const dateShort = d.date.slice(5); // MM-DD

    // Countdown
    let countdownHtml = '';
    if (isFirstDay) {
      const matchDate = new Date(d.date + 'T00:00:00');
      const now = new Date();
      const diffDays = Math.ceil((matchDate - now) / (1000 * 60 * 60 * 24));
      if (diffDays > 0) {
        countdownHtml = '<div class="dcountdown">⏳ 距开赛 ' + diffDays + ' 天</div>';
      } else if (diffDays === 0) {
        countdownHtml = '<div class="dcountdown">🔥 今天开赛!</div>';
      }
    }

    const stageStr = d.stages.join(' · ');

    html += '<div class="schedule-day' + todayClass + '">' +
      '<div class="dhead">' +
        '<span class="ddate">' + dateShort + '</span>' +
        '<span class="dweek">' + weekdayCN + '</span>' +
      '</div>' +
      '<div class="dinfo">' +
        '<span class="teams-count">' + d.team_count + ' 支球队</span> · ' +
        '<span class="matches-count">' + d.match_count + ' 场</span>' +
        (d.team_count > 0 && d.teams.length <= 6
          ? '<br><span style="font-size:0.69em;color:var(--text2)">' + d.teams.join(', ') + '</span>'
          : '') +
      '</div>' +
      '<div class="dstage">' + stageStr + '</div>' +
      countdownHtml +
    '</div>';
  });
  html += '</div>';
  document.getElementById('schedule-list').innerHTML = html;
}

// ============================================================
// Today's Match Predictions
// ============================================================
const TEAM_NAMES_CN_JS = {
  'France':'法国','Spain':'西班牙','Brazil':'巴西','Argentina':'阿根廷',
  'England':'英格兰','Portugal':'葡萄牙','Netherlands':'荷兰','Germany':'德国',
  'Italy':'意大利','Belgium':'比利时','Uruguay':'乌拉圭','Colombia':'哥伦比亚',
  'Croatia':'克罗地亚','Morocco':'摩洛哥','Denmark':'丹麦','Senegal':'塞内加尔',
  'USA':'美国','Mexico':'墨西哥','South Korea':'韩国','Japan':'日本',
  'Iran':'伊朗','Australia':'澳大利亚','Egypt':'埃及','Algeria':'阿尔及利亚',
  'Tunisia':'突尼斯','Saudi Arabia':'沙特阿拉伯','Ecuador':'厄瓜多尔',
  'Paraguay':'巴拉圭','Canada':'加拿大','Costa Rica':'哥斯达黎加',
  'Ivory Coast':'科特迪瓦','Cote d\'Ivoire':'科特迪瓦','Ghana':'加纳',
  'South Africa':'南非','Cameroon':'喀麦隆','Nigeria':'尼日利亚',
  'DR Congo':'刚果(金)','Cape Verde':'佛得角','Serbia':'塞尔维亚',
  'Switzerland':'瑞士','Poland':'波兰','Ukraine':'乌克兰','Austria':'奥地利',
  'Czech Republic':'捷克','Turkey':'土耳其','Greece':'希腊','Sweden':'瑞典',
  'Scotland':'苏格兰','Ireland':'爱尔兰','Slovakia':'斯洛伐克','Hungary':'匈牙利',
  'Panama':'巴拿马','Haiti':'海地','Curacao':'库拉索','Jamaica':'牙买加',
  'New Zealand':'新西兰','Uzbekistan':'乌兹别克斯坦','Iraq':'伊拉克',
  'Jordan':'约旦','Qatar':'卡塔尔','Bosnia':'波黑',
};

function cnName(en) {
  return TEAM_NAMES_CN_JS[en] || en;
}

async function fetchTodayMatches() {
  try {
    const resp = await fetch(API_BASE + '/api/today');
    const data = await resp.json();
    if (data.status === 'ok') {
      renderTodayMatches(data);
    } else {
      document.getElementById('today-matches').innerHTML =
        '<div class="today-empty">暂无比赛数据</div>';
    }
  } catch (e) {
    log('今日比赛加载失败: ' + e.message);
  }
}

function renderTodayMatches(data) {
  const dateShort = data.date.slice(5);
  document.getElementById('today-date-header').textContent =
    dateShort + ' · ' + data.stage_label;

  // Mini timeline
  renderTodayTimeline(data);

  if (!data.matches || data.matches.length === 0) {
    document.getElementById('today-matches').innerHTML =
      '<div class="today-empty">今日无比赛</div>';
    document.getElementById('today-actions').style.display = 'none';
    return;
  }

  let html = '';
  data.matches.forEach(m => {
    if (m.tbd) {
      html += '<div class="match-item tbd">' +
        '<div class="match-header-row">' +
          '<span class="match-group-tag">' + (m.group || '淘汰赛') + '</span>' +
          '<span>' + m.stage + '</span>' +
        '</div>' +
        '<div class="match-teams-row">' +
          '<span style="color:var(--text2);">对阵待定</span>' +
        '</div>' +
      '</div>';
      return;
    }

    const homeCN = cnName(m.home);
    const awayCN = cnName(m.away);
    const groupTag = m.group ? '<span class="match-group-tag">' + m.group + ' 组</span>' : '';

    // Determine the stronger team for color emphasis
    const homeStronger = m.home_win_pct >= m.away_win_pct;
    const maxPct = Math.max(m.home_win_pct, m.draw_pct, m.away_win_pct);

    html += '<div class="match-item">' +
      '<div class="match-header-row">' +
        groupTag +
        '<span>' + m.stage + '</span>' +
      '</div>' +
      '<div class="match-teams-row">' +
        '<div class="team-block">' +
          '<div class="tname" style="color:' + (homeStronger ? '#FFD700' : '') + '">' + homeCN + '</div>' +
          '<div class="telo">ELO ' + m.home_elo + '</div>' +
        '</div>' +
        '<div class="team-vs">VS</div>' +
        '<div class="team-block">' +
          '<div class="tname" style="color:' + (!homeStronger ? '#FFD700' : '') + '">' + awayCN + '</div>' +
          '<div class="telo">ELO ' + m.away_elo + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="prob-row">' +
        '<div class="prob-col home">' +
          '<div class="plabel">' + homeCN + '胜 ' + m.home_win_pct + '%</div>' +
          '<div class="prob-bar-wrap"><div class="prob-bar home" style="width:' + Math.max(m.home_win_pct, 5) + '%"></div></div>' +
        '</div>' +
        '<div class="prob-col draw">' +
          '<div class="plabel">平局 ' + m.draw_pct + '%</div>' +
          '<div class="prob-bar-wrap"><div class="prob-bar draw" style="width:' + Math.max(m.draw_pct, 5) + '%"></div></div>' +
        '</div>' +
        '<div class="prob-col away">' +
          '<div class="plabel">' + awayCN + '胜 ' + m.away_win_pct + '%</div>' +
          '<div class="prob-bar-wrap"><div class="prob-bar away" style="width:' + Math.max(m.away_win_pct, 5) + '%"></div></div>' +
        '</div>' +
      '</div>' +
      '<div class="goals-row">' +
        '预期进球: <span class="gval ghome">' + m.expected_goals_home + '</span>' +
        ' <span style="color:#555;">-</span> ' +
        '<span class="gval gaway">' + m.expected_goals_away + '</span>' +
        ' <span style="font-size:0.9em;">(总 <span style="color:#FFD700;">' + m.total_expected_goals + '</span>)</span>' +
      '</div>' +
    '</div>';
  });

  document.getElementById('today-matches').innerHTML = html;

  // Actions bar
  const btnNext = document.getElementById('btn-next-day');
  if (data.has_next) {
    btnNext.disabled = false;
    btnNext.textContent = '\u25B6 下一比赛日 (' + data.next_date.slice(5) + ')';
  } else {
    btnNext.disabled = true;
    btnNext.textContent = '\u2714 已是最后比赛日';
  }
  document.getElementById('today-progress-text').innerHTML =
    '第 <span>' + (data.day_index + 1) + '</span> / ' + (data.total_matchdays || 33) + ' 比赛日';

  document.getElementById('today-actions').style.display = 'flex';
}

function renderTodayTimeline(data) {
  const TOTAL = data.total_matchdays || 33;
  const current = data.day_index;
  const start = Math.max(0, current - 2);
  const end = Math.min(TOTAL, current + 3);

  let html = '';
  for (let i = start; i < end; i++) {
    let cls = 'dot';
    if (i < current) cls += ' done';
    else if (i === current) cls += ' active';
    html += '<span class="' + cls + '" title="第' + (i+1) + '比赛日"></span>';
  }
  if (start > 0) html = '<span style="font-size:0.8em;">…</span>' + html;
  if (end < TOTAL) html += '<span style="font-size:0.8em;">…</span>';

  document.getElementById('today-timeline').innerHTML = html;
}

async function advanceMatchDay() {
  const btn = document.getElementById('btn-next-day');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> 推进中...';

  try {
    const resp = await fetch(API_BASE + '/api/today/advance', { method: 'POST' });
    const data = await resp.json();
    if (data.status === 'ok') {
      renderTodayMatches(data);
      log('已推进到 ' + data.date + ' · ' + data.stage_label);
    }
  } catch (e) {
    log('推进失败: ' + e.message);
    btn.disabled = false;
  }
}

// ============================================================
// Init
// ============================================================
startAutoRefresh();
fetchPredictions();
fetchSchedule();
fetchTodayMatches();
log('仪表盘已启动，等待首次数据加载……');
</script>

</body>
</html>"""


# ============================================================
# HTTP 请求处理器
# ============================================================
class DashboardHandler(BaseHTTPRequestHandler):
    """自定义 HTTP 处理器，路由到静态页面或 API。"""

    def log_message(self, format, *args):
        """抑制默认日志，使用自定义格式。"""
        pass  # 静默模式

    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send_html(self, html: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _send_error_json(self, message: str, status: int = 500):
        self._send_json({"status": "error", "message": message}, status)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            self._send_html(get_dashboard_html())
        elif path == "/api/predictions":
            data = state.get_predictions_json()
            self._send_json(data)
        elif path == "/api/status":
            status_data = {
                "status": "ok",
                "sync_status": state.sync_status,
                "last_sim_time": state.last_sim_time,
                "last_sync_time": state.last_sync_time,
                "matches_found": state.matches_found,
                "elo_from_web": state.elo_from_web,
                "elo_from_local": state.elo_from_local,
                "num_sims": state.num_sims,
                "auto_sync_enabled": state.auto_sync_enabled,
                "auto_sync_interval_h": round(state.auto_sync_interval / 3600, 1),
                "auto_sync_interval_min": round(state.auto_sync_interval / 60),
                "next_auto_sync_time": (
                    datetime.fromtimestamp(state.next_auto_sync_time).isoformat()
                    if state.next_auto_sync_time else None
                ),
            }
            # 附加赛事实时状态
            if HAS_WORLDCUP_API:
                try:
                    t_status = get_tournament_status()
                    status_data["tournament"] = {
                        "total_matches": t_status["total_matches"],
                        "finished_matches": t_status["finished_matches"],
                        "remaining_matches": t_status["remaining_matches"],
                        "today_matches": t_status["today_matches"],
                        "today_finished": t_status["today_finished"],
                        "completed_matchdays": t_status["completed_matchdays"],
                        "total_matchdays": t_status["total_matchdays"],
                        "is_live": t_status["is_live"],
                        "data_source": t_status["data_source"],
                    }
                except Exception:
                    pass
            with STATE_LOCK:
                self._send_json(status_data)
        elif path == "/api/matches":
            # 从 worldcup_api 获取真实比赛数据
            if HAS_WORLDCUP_API:
                finished = get_finished_matches()
                today_matches = get_today_matches()
                self._send_json({
                    "status": "ok",
                    "finished": [
                        {
                            "home": m["home_cn"], "away": m["away_cn"],
                            "home_code": m["home_code"], "away_code": m["away_code"],
                            "score": m.get("score_ft"),
                            "stage": m["stage"], "group": m.get("group"),
                            "date": m["date"], "venue": m.get("venue", ""),
                        }
                        for m in finished
                    ],
                    "today": [
                        {
                            "home": m["home_cn"], "away": m["away_cn"],
                            "home_code": m["home_code"], "away_code": m["away_code"],
                            "score": m.get("score_ft"),
                            "time_bj": m["time_bj"], "stage": m["stage"],
                            "group": m.get("group"), "finished": m.get("finished", False),
                            "venue": m.get("venue", ""),
                        }
                        for m in today_matches
                    ],
                    "total_finished": len(finished),
                    "total_today": len(today_matches),
                    "message": "数据源: openfootball/worldcup.json",
                })
            else:
                self._send_json({
                    "status": "ok",
                    "matches": [],
                    "message": "世界杯尚未开赛（无实时数据源）" if datetime.now() < datetime(2026, 6, 11) else "赛果数据暂不可用",
                })
        elif path == "/api/schedule":
            days = int(parsed.query.split("=")[1]) if "days=" in parsed.query else 30
            self._send_json(state.get_schedule_json(upcoming_days=days))
        elif path == "/api/today":
            self._send_json(state.get_today_predictions())
        elif path == "/api/today/advance":
            self._send_json(state.advance_match_day())
        elif path == "/api/live" and HAS_WORLDCUP_API:
            # 实时赛况：今日比赛（含进行中和已完赛）
            today = get_today_matches()
            self._send_json({
                "status": "ok",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "matches": [
                    {
                        "home": m["home_cn"], "away": m["away_cn"],
                        "home_code": m["home_code"], "away_code": m["away_code"],
                        "score_ft": m.get("score_ft"),
                        "score_ht": m.get("score_ht"),
                        "time_bj": m["time_bj"], "stage": m["stage"],
                        "group": m.get("group"), "venue": m.get("venue", ""),
                        "finished": m.get("finished", False),
                        "started": m.get("started", False),
                        "goals_home": m.get("goals_home", []),
                        "goals_away": m.get("goals_away", []),
                    }
                    for m in today
                ],
                "source": "openfootball/worldcup.json",
            })
        elif path == "/api/live":
            self._send_json({"status": "no_data", "message": "实时数据源不可用"})
        else:
            self._send_error_json("Not Found", 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/sync":
            # 在后台线程执行同步
            self._send_json({"status": "started", "message": "数据同步已触发"})
            t = threading.Thread(target=state.sync_data, daemon=True)
            t.start()
        elif path == "/api/auto-sync/toggle":
            result = state.toggle_auto_sync()
            self._send_json(result)
        elif path == "/api/auto-sync/interval":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b"{}"
            try:
                params = json.loads(body.decode("utf-8"))
                minutes = int(params.get("minutes", 5))
                result = state.set_sync_interval(minutes)
                self._send_json(result)
            except (ValueError, json.JSONDecodeError):
                self._send_error_json("Invalid minutes parameter", 400)
        elif path == "/api/today/advance":
            self._send_json(state.advance_match_day())
        else:
            self._send_error_json("Not Found", 404)

    def do_OPTIONS(self):
        """CORS preflight。"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


# ============================================================
# 双栈 HTTP 服务器（兼容 IPv4 + IPv6）
# ============================================================
class DualStackHTTPServer(HTTPServer):
    """同时绑定 IPv4 和 IPv6 的 HTTP 服务器。"""
    allow_reuse_address = True

    def server_bind(self):
        if hasattr(socket, 'AF_INET6'):
            self.socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            host, port = self.server_address
            if host == "0.0.0.0":
                host = "::"
            self.socket.bind((host, port))
            self.server_address = self.socket.getsockname()
        else:
            super().server_bind()


# ============================================================
# 主入口
# ============================================================
def start_server(port: int = 8888, num_sims: int = 10000, seed: int = 42, auto_sync_h: float = 2.0):
    """启动仪表盘服务器。"""
    state.num_sims = num_sims
    state.seed = seed
    state.auto_sync_interval = int(auto_sync_h * 3600)

    # 后台运行首次模拟
    state.init_simulator()
    print(f"\n🔄 正在后台运行首次模拟（{num_sims:,} 次）……")
    sim_thread = threading.Thread(target=state.run_simulation, daemon=True)
    sim_thread.start()

    # 启动全自动同步定时器
    state.start_auto_sync()

    server = DualStackHTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"\n{'='*60}")
    print(f"  2026 世界杯实时仪表盘已启动")
    print(f"  地址：http://localhost:{port}")
    print(f"  全自动同步：每 {auto_sync_h} 小时一次")
    print(f"  按 Ctrl+C 停止服务器")
    print(f"{'='*60}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n服务器已停止。")
        server.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="2026 世界杯实时仪表盘服务器")
    parser.add_argument("--port", type=int, default=8888, help="HTTP 端口（默认 8888）")
    parser.add_argument("--sims", type=int, default=10000, help="模拟次数（默认 10000）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--auto-sync", type=float, default=2.0, help="自动同步间隔（小时，默认 2）")
    args = parser.parse_args()

    start_server(args.port, args.sims, args.seed, args.auto_sync)
