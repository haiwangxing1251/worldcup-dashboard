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
    get_tournament_status, get_today_matches, TEAM_NAMES_CN, TEAM_NAME_TO_CODE,
)
from simulator import WorldCupSimulator
from report import generate_html_report, save_report, cn
from model import EloPoissonModel

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
# 今日赛程预测模块
# ============================================================

def compute_today_predictions(schedule_matches: list, elo_data: dict) -> dict:
    """Compute win/draw/loss predictions for today's matches."""
    model = EloPoissonModel()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Build teams_lookup: English name → code
    teams_lookup = {}
    for code, info in elo_data.get("teams", {}).items():
        name = info.get("name", "")
        if name:
            teams_lookup[name] = code

    today_matches = [m for m in schedule_matches if m["date"] == today_str]
    all_dates = sorted(set(m["date"] for m in schedule_matches))

    try:
        day_index = all_dates.index(today_str)
    except ValueError:
        day_index = 0

    matches_with_pred = []
    for m in today_matches:
        home = m.get("home", "")
        away = m.get("away", "")

        if not home or not away or home == away:
            matches_with_pred.append({
                "home": home or "待定", "away": away or "待定",
                "home_cn": home or "待定", "away_cn": away or "待定",
                "group": m.get("group"), "stage": m.get("stage", ""),
                "tbd": True, "finished": m.get("finished", False),
                "score": m.get("score_ft"),
            })
            continue

        home_code = m.get("home_code", teams_lookup.get(home, ""))
        away_code = m.get("away_code", teams_lookup.get(away, ""))
        home_elo = elo_data.get("teams", {}).get(home_code, {}).get("elo", 1500.0)
        away_elo = elo_data.get("teams", {}).get(away_code, {}).get("elo", 1500.0)

        p_home, p_draw, p_away = model.match_outcome_probabilities(home_elo, away_elo)
        lam_h, lam_a = model.expected_goals(home_elo, away_elo)

        matches_with_pred.append({
            "home": home, "away": away,
            "home_cn": TEAM_NAMES_CN.get(home_code, home),
            "away_cn": TEAM_NAMES_CN.get(away_code, away),
            "home_code": home_code, "away_code": away_code,
            "home_elo": round(home_elo), "away_elo": round(away_elo),
            "group": m.get("group"), "stage": m.get("stage", ""),
            "home_win_pct": round(p_home * 100, 1),
            "draw_pct": round(p_draw * 100, 1),
            "away_win_pct": round(p_away * 100, 1),
            "expected_goals_home": round(lam_h, 2),
            "expected_goals_away": round(lam_a, 2),
            "total_expected_goals": round(lam_h + lam_a, 2),
            "finished": m.get("finished", False),
            "score": m.get("score_ft"),
            "tbd": False,
        })

    return {
        "date": today_str,
        "day_index": day_index,
        "total_matchdays": len(all_dates),
        "matches": matches_with_pred,
        "total_matches": len(matches_with_pred),
        "has_next": day_index < len(all_dates) - 1,
        "has_prev": day_index > 0,
        "next_date": all_dates[day_index + 1] if day_index < len(all_dates) - 1 else None,
        "prev_date": all_dates[day_index - 1] if day_index > 0 else None,
        "all_dates": all_dates,
    }


def build_today_module_html(elo_data: dict, schedule_matches: list,
                            today_pred: dict) -> str:
    """Build the complete today-match module as self-contained HTML/CSS/JS."""
    elo_json = json.dumps(elo_data, ensure_ascii=False)
    schedule_json = json.dumps(schedule_matches, ensure_ascii=False)
    today_json = json.dumps(today_pred, ensure_ascii=False)
    team_names_json = json.dumps(TEAM_NAMES_CN, ensure_ascii=False)

    return f"""
<!-- ====== 今日比赛预测模块 ====== -->
<style>
.today-match-card {{
  background: #111640; border-radius: 12px; padding: 20px;
  border: 1px solid rgba(255,255,255,0.08); margin: 20px 0;
}}
.today-match-card h2 {{
  font-size: 1.15em; color: #4fc3f7; margin-bottom: 14px;
}}
.today-date-header {{
  display: inline-block; font-weight: 600; color: #FFD700;
  font-size: 1em; margin-left: 8px;
}}
.match-item {{
  background: rgba(255,255,255,0.03); border-radius: 10px;
  padding: 14px 16px; margin-bottom: 10px;
  border: 1px solid rgba(255,255,255,0.05);
  transition: border-color 0.2s;
}}
.match-item:hover {{ border-color: rgba(79,195,247,0.25); }}
.match-item.tbd {{ opacity: 0.5; border-style: dashed; }}
.match-item.finished {{ border-left: 3px solid #66bb6a; }}
.match-item.live {{ border-left: 3px solid #FF7043; animation: livePulse 1.5s infinite; }}
@keyframes livePulse {{ 0%,100% {{ border-left-color: #FF7043; }} 50% {{ border-left-color: rgba(255,112,67,0.3); }} }}
.match-header-row {{
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 10px; font-size: 0.72em; color: #8890b5;
}}
.match-group-tag {{
  background: rgba(79,195,247,0.12); color: #4fc3f7;
  padding: 2px 8px; border-radius: 4px; font-weight: 600;
}}
.match-score-tag {{
  background: rgba(102,187,106,0.15); color: #66bb6a;
  padding: 2px 8px; border-radius: 4px; font-weight: 700;
  font-size: 0.95em;
}}
.match-live-tag {{
  background: rgba(255,112,67,0.2); color: #FF7043;
  padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 0.85em;
  animation: livePulse 1s infinite;
}}
.match-teams-row {{
  display: flex; align-items: center; justify-content: center;
  gap: 16px; margin-bottom: 12px;
}}
.team-block {{ text-align: center; min-width: 100px; }}
.team-block .tname {{
  font-weight: 700; font-size: 1em;
}}
.team-block .telo {{
  font-size: 0.7em; color: #8890b5;
}}
.team-block .tscore {{
  font-size: 1.4em; font-weight: 900; color: #e8e8ec;
  margin-top: 2px;
}}
.team-vs {{
  font-size: 1.1em; font-weight: 900; color: rgba(255,255,255,0.15);
}}
.prob-row {{
  display: flex; gap: 8px; margin-bottom: 8px;
}}
.prob-col {{ flex: 1; text-align: center; }}
.prob-col .plabel {{
  font-size: 0.72em; margin-bottom: 3px; font-weight: 600;
}}
.prob-col.home .plabel {{ color: #42a5f5; }}
.prob-col.draw .plabel {{ color: #9e9e9e; }}
.prob-col.away .plabel {{ color: #ef5350; }}
.prob-bar-wrap {{
  height: 8px; background: rgba(255,255,255,0.06);
  border-radius: 4px; overflow: hidden;
}}
.prob-bar {{
  height: 100%; border-radius: 4px; transition: width 0.5s ease;
}}
.prob-bar.home {{ background: linear-gradient(90deg, #1565c0, #42a5f5); }}
.prob-bar.draw {{ background: linear-gradient(90deg, #616161, #9e9e9e); }}
.prob-bar.away {{ background: linear-gradient(90deg, #c62828, #ef5350); }}
.goals-row {{
  text-align: center; font-size: 0.78em; color: #8890b5;
  padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.04);
}}
.goals-row .gval {{ font-weight: 700; }}
.goals-row .ghome {{ color: #42a5f5; }}
.goals-row .gaway {{ color: #ef5350; }}
.today-empty {{
  text-align: center; padding: 30px; color: #8890b5; font-size: 0.9em;
}}
.today-actions {{
  display: flex; align-items: center; justify-content: center;
  gap: 16px; padding-top: 14px; margin-top: 10px;
  border-top: 1px solid rgba(255,255,255,0.06);
}}
.btn-today-nav {{
  padding: 8px 20px; border: none; border-radius: 8px;
  cursor: pointer; font-size: 0.85em; font-weight: 600;
  background: linear-gradient(135deg, #1b5e20, #2e7d32);
  color: white; border: 1px solid rgba(102,187,106,0.3);
  transition: all 0.2s;
}}
.btn-today-nav:hover {{ background: linear-gradient(135deg, #2e7d32, #388e3c); }}
.btn-today-nav:disabled {{ opacity: 0.4; cursor: not-allowed; }}
.today-progress-text {{
  font-size: 0.78em; color: #8890b5;
}}
.today-progress-text span {{ color: #4fc3f7; font-weight: 700; }}
.tournament-timeline {{
  display: flex; align-items: center; gap: 4px;
  font-size: 0.72em; color: #8890b5; margin-bottom: 4px;
}}
.tournament-timeline .dot {{
  width: 6px; height: 6px; border-radius: 50%;
  background: rgba(255,255,255,0.15);
}}
.tournament-timeline .dot.active {{ background: #4fc3f7; }}
.tournament-timeline .dot.done {{ background: #66bb6a; }}
.today-sync-info {{
  font-size: 0.72em; color: #8890b5; text-align: center;
  padding-top: 10px;
}}
.btn-today-refresh {{
  padding: 8px 18px; border: none; border-radius: 8px;
  cursor: pointer; font-size: 0.85em; font-weight: 600;
  background: linear-gradient(135deg, #0d47a1, #1565c0);
  color: white; border: 1px solid rgba(66,165,245,0.3);
  transition: all 0.2s; display: inline-flex; align-items: center; gap: 6px;
}}
.btn-today-refresh:hover {{
  background: linear-gradient(135deg, #1565c0, #1e88e5);
  border-color: rgba(66,165,245,0.5);
}}
.btn-today-refresh:disabled {{ opacity: 0.5; cursor: not-allowed; }}
.btn-today-refresh .spin-icon {{
  display: inline-block; transition: transform 0.3s;
}}
.btn-today-refresh.spinning .spin-icon {{
  animation: spin 0.8s linear infinite;
}}
@keyframes spin {{
  from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }}
}}
@media (max-width: 768px) {{
  .match-item {{ padding: 10px 12px; margin-bottom: 8px; }}
  .match-teams-row {{ gap: 10px; }}
  .team-block {{ min-width: 70px; }}
  .team-block .tname {{ font-size: 0.85em; }}
  .team-block .telo {{ font-size: 0.62em; }}
  .team-block .tscore {{ font-size: 1.15em; }}
  .prob-row {{ gap: 4px; }}
  .prob-col .plabel {{ font-size: 0.65em; }}
  .goals-row {{ font-size: 0.72em; }}
  .today-actions {{ flex-direction: column; gap: 8px; }}
  .btn-today-nav {{ width: 100%; padding: 10px; font-size: 0.9em; }}
  .btn-today-refresh {{ width: 100%; padding: 10px; font-size: 0.9em; justify-content: center; }}
  .today-date-header {{ font-size: 0.85em; display: block; margin-left: 0; }}
}}
</style>

<div class="today-match-card" id="today-match-card">
  <h2>&#x1F4CA; 今日比赛预测
    <span class="today-date-header" id="today-date-header"></span>
  </h2>
  <div class="tournament-timeline" id="today-timeline"></div>
  <div id="today-matches">加载中…</div>
  <div class="today-actions" id="today-actions" style="display:none;">
    <button class="btn-today-nav" id="btn-prev-day" onclick="navigateDay(-1)">
      &#x25C0; 前一天
    </button>
    <button class="btn-today-nav" id="btn-next-day" onclick="navigateDay(1)">
      &#x25B6; 后一天
    </button>
    <button class="btn-today-refresh" id="btn-refresh" onclick="refreshNow()">
      <span class="spin-icon">&#x21BB;</span> 立即更新
    </button>
    <span class="today-progress-text" id="today-progress-text"></span>
  </div>
  <div class="today-sync-info" id="today-sync-info"></div>
</div>

<script>
// ====== Embedded Data ======
var TODAY_ELO_DATA = {elo_json};
var TODAY_SCHEDULE = {schedule_json};
var TODAY_INITIAL = {today_json};
var TODAY_TEAM_NAMES_CN = {team_names_json};
var TODAY_CURRENT_DATE = TODAY_INITIAL.date;
var TODAY_ALL_DATES = TODAY_INITIAL.all_dates || [];
var TODAY_REFRESH_TIMER = null;

// ====== Poisson Prediction Engine (JS port) ======
var AVG_TOTAL_GOALS = 2.6;
var ELO_PER_GOAL = 200.0;
var MIN_LAMBDA = 0.3;
var MAX_LAMBDA = 4.0;

function factorial(n) {{
  var r = 1;
  for (var i = 2; i <= n; i++) r *= i;
  return r;
}}

function poissonProb(k, lam) {{
  if (lam <= 0) return k === 0 ? 1 : 0;
  return (Math.pow(lam, k) * Math.exp(-lam)) / factorial(k);
}}

function expectedGoals(eloA, eloB) {{
  var dr = eloA - eloB;
  var gd = dr / ELO_PER_GOAL;
  var half = AVG_TOTAL_GOALS / 2;
  var la = Math.max(MIN_LAMBDA, Math.min(MAX_LAMBDA, half + gd / 2));
  var lb = Math.max(MIN_LAMBDA, Math.min(MAX_LAMBDA, half - gd / 2));
  return [la, lb];
}}

function matchOutcomeProbs(eloA, eloB, maxGoals) {{
  maxGoals = maxGoals || 8;
  var lams = expectedGoals(eloA, eloB);
  var la = lams[0], lb = lams[1];
  var pWin = 0, pDraw = 0, pLose = 0;
  for (var ga = 0; ga <= maxGoals; ga++) {{
    var pa = poissonProb(ga, la);
    for (var gb = 0; gb <= maxGoals; gb++) {{
      var joint = pa * poissonProb(gb, lb);
      if (ga > gb) pWin += joint;
      else if (gb > ga) pLose += joint;
      else pDraw += joint;
    }}
  }}
  var total = pWin + pDraw + pLose;
  if (total > 0) {{ pWin /= total; pDraw /= total; pLose /= total; }}
  return [pWin, pDraw, pLose];
}}

// ====== Lookup helpers ======
function cnName(name) {{
  // name could be English name (from schedule) or 3-letter code
  if (TODAY_TEAM_NAMES_CN[name]) return TODAY_TEAM_NAMES_CN[name];
  // Try code lookup
  for (var code in TODAY_TEAM_NAMES_CN) {{
    if (TODAY_ELO_DATA.teams && TODAY_ELO_DATA.teams[code] &&
        TODAY_ELO_DATA.teams[code].name === name) {{
      return TODAY_TEAM_NAMES_CN[code];
    }}
  }}
  return name;
}}

function getElo(enName) {{
  // Find ELO by English team name
  var teams = TODAY_ELO_DATA.teams || {{}};
  for (var code in teams) {{
    if (teams[code].name === enName) return teams[code].elo || 1500;
  }}
  return 1500;
}}

function getCode(enName) {{
  var teams = TODAY_ELO_DATA.teams || {{}};
  for (var code in teams) {{
    if (teams[code].name === enName) return code;
  }}
  return enName;
}}

// ====== Get schedule for a specific date ======
function getMatchesForDate(dateStr) {{
  return TODAY_SCHEDULE.filter(function(m) {{ return m.date === dateStr; }});
}}

// ====== Compute predictions for any date ======
function computePredictions(dateStr) {{
  var matches = getMatchesForDate(dateStr);
  if (!matches.length) return null;

  var idx = TODAY_ALL_DATES.indexOf(dateStr);
  if (idx < 0) idx = 0;

  var preds = [];
  matches.forEach(function(m) {{
    var home = m.home || '', away = m.away || '';
    if (!home || !away || home === away) {{
      preds.push({{
        home: home || '待定', away: away || '待定',
        home_cn: home || '待定', away_cn: away || '待定',
        group: m.group, stage: m.stage, tbd: true,
        finished: m.finished || false, score: m.score_ft
      }});
      return;
    }}

    var hElo = getElo(home), aElo = getElo(away);
    var probs = matchOutcomeProbs(hElo, aElo);
    var goals = expectedGoals(hElo, aElo);
    var hCode = getCode(home), aCode = getCode(away);

    preds.push({{
      home: home, away: away,
      home_cn: cnName(hCode) || cnName(home),
      away_cn: cnName(aCode) || cnName(away),
      home_code: hCode, away_code: aCode,
      home_elo: Math.round(hElo), away_elo: Math.round(aElo),
      group: m.group, stage: m.stage,
      home_win_pct: +(probs[0] * 100).toFixed(1),
      draw_pct: +(probs[1] * 100).toFixed(1),
      away_win_pct: +(probs[2] * 100).toFixed(1),
      expected_goals_home: +goals[0].toFixed(2),
      expected_goals_away: +goals[1].toFixed(2),
      total_expected_goals: +(goals[0] + goals[1]).toFixed(2),
      finished: m.finished || false, score: m.score_ft,
      tbd: false
    }});
  }});

  return {{
    date: dateStr,
    day_index: idx,
    total_matchdays: TODAY_ALL_DATES.length,
    matches: preds,
    total_matches: preds.length,
    has_next: idx < TODAY_ALL_DATES.length - 1,
    has_prev: idx > 0,
    next_date: idx < TODAY_ALL_DATES.length - 1 ? TODAY_ALL_DATES[idx + 1] : null,
    prev_date: idx > 0 ? TODAY_ALL_DATES[idx - 1] : null
  }};
}}

// ====== Live Score Fetching ======
function fetchLiveScores() {{
  try {{
    var apiUrl = 'https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json';
    return fetch(apiUrl).then(function(r) {{ return r.json(); }}).then(function(data) {{
      updateLiveScores(data);
    }}).catch(function() {{ /* silently fail */ }});
  }} catch(e) {{ return Promise.resolve(); }}
}}

function updateLiveScores(rawData) {{
  if (!rawData || !rawData.matches) return;
  var updated = false;
  rawData.matches.forEach(function(rm) {{
    var rdate = rm.date || '';
    if (rdate !== TODAY_CURRENT_DATE) return;
    var t1 = rm.team1 || '', t2 = rm.team2 || '';
    var ft = rm.goals1 !== undefined && rm.goals2 !== undefined ?
             [rm.goals1, rm.goals2] : null;
    // Update schedule data
    TODAY_SCHEDULE.forEach(function(m) {{
      if (m.date === rdate && m.home === t1 && m.away === t2) {{
        if (ft && !m.finished) {{ m.finished = true; m.score_ft = ft; updated = true; }}
        else if (ft) {{ m.score_ft = ft; updated = true; }}
      }}
    }});
  }});
  if (updated) {{
    var pred = computePredictions(TODAY_CURRENT_DATE);
    if (pred) renderTodayMatches(pred);
  }}
}}

// ====== Rendering ======
function renderTodayMatches(data) {{
  var dateShort = data.date.slice(5);
  document.getElementById('today-date-header').textContent = dateShort;

  // Timeline
  renderTimeline(data);

  if (!data.matches || data.matches.length === 0) {{
    document.getElementById('today-matches').innerHTML =
      '<div class="today-empty">该日暂无比赛 &#x1F4AD;<br><small>使用下方按钮跳转到有比赛的日期</small></div>';
    // Fall through - still show navigation and refresh buttons
  }} else {{
    renderMatchCards(data);
  }}

  // Navigation buttons (always visible if there are matchdays)
  updateNavigation(data);
}}

function renderMatchCards(data) {{
  var html = '';
  data.matches.forEach(function(m) {{
    if (m.tbd) {{
      html += '<div class="match-item tbd">' +
        '<div class="match-header-row">' +
          '<span class="match-group-tag">' + (m.group || '淘汰赛') + '</span>' +
          '<span>' + (m.stage || '') + '</span>' +
        '</div>' +
        '<div class="match-teams-row">' +
          '<span style="color:#8890b5;">对阵待定</span>' +
        '</div>' +
      '</div>';
      return;
    }}

    var homeCN = m.home_cn, awayCN = m.away_cn;
    var groupTag = m.group ? '<span class="match-group-tag">' + m.group + ' 组</span>' : '';
    var homeStronger = m.home_win_pct >= m.away_win_pct;

    // Score display
    var scoreHtml = '';
    var itemClass = 'match-item';
    if (m.finished && m.score) {{
      itemClass += ' finished';
      scoreHtml = '<span class="match-score-tag">' + m.score[0] + ' - ' + m.score[1] + '</span>';
    }}

    html += '<div class="' + itemClass + '">' +
      '<div class="match-header-row">' +
        groupTag +
        (scoreHtml || '<span>' + (m.stage || '') + '</span>') +
      '</div>' +
      '<div class="match-teams-row">' +
        '<div class="team-block">' +
          '<div class="tname" style="color:' + (homeStronger ? '#FFD700' : '') + '">' + homeCN + '</div>' +
          '<div class="telo">ELO ' + m.home_elo + '</div>' +
          (m.finished && m.score ? '<div class="tscore">' + m.score[0] + '</div>' : '') +
        '</div>' +
        '<div class="team-vs">' + (m.finished && m.score ? '' : 'VS') + '</div>' +
        '<div class="team-block">' +
          '<div class="tname" style="color:' + (!homeStronger ? '#FFD700' : '') + '">' + awayCN + '</div>' +
          '<div class="telo">ELO ' + m.away_elo + '</div>' +
          (m.finished && m.score ? '<div class="tscore">' + m.score[1] + '</div>' : '') +
        '</div>' +
      '</div>';

    // Only show predictions for non-finished matches
    if (!m.finished) {{
      html += '<div class="prob-row">' +
        '<div class="prob-col home">' +
          '<div class="plabel">' + homeCN + '胜 ' + m.home_win_pct + '%</div>' +
          '<div class="prob-bar-wrap"><div class="prob-bar home" style="width:' + Math.max(m.home_win_pct, 3) + '%"></div></div>' +
        '</div>' +
        '<div class="prob-col draw">' +
          '<div class="plabel">平局 ' + m.draw_pct + '%</div>' +
          '<div class="prob-bar-wrap"><div class="prob-bar draw" style="width:' + Math.max(m.draw_pct, 3) + '%"></div></div>' +
        '</div>' +
        '<div class="prob-col away">' +
          '<div class="plabel">' + awayCN + '胜 ' + m.away_win_pct + '%</div>' +
          '<div class="prob-bar-wrap"><div class="prob-bar away" style="width:' + Math.max(m.away_win_pct, 3) + '%"></div></div>' +
        '</div>' +
      '</div>' +
      '<div class="goals-row">' +
        '预期进球: <span class="gval ghome">' + m.expected_goals_home + '</span>' +
        ' - <span class="gval gaway">' + m.expected_goals_away + '</span>' +
        ' (总 <span style="color:#FFD700;font-weight:700;">' + m.total_expected_goals + '</span>)' +
      '</div>';
    }}

    html += '</div>';
  }});

  document.getElementById('today-matches').innerHTML = html;
}}

function updateNavigation(data) {{
  var btnPrev = document.getElementById('btn-prev-day');
  var btnNext = document.getElementById('btn-next-day');
  if (data.has_prev) {{
    btnPrev.disabled = false;
    btnPrev.textContent = '\\u25C0 前一天 (' + data.prev_date.slice(5) + ')';
  }} else {{
    btnPrev.disabled = true;
    btnPrev.textContent = '\\u25C0 前一天';
  }}
  if (data.has_next) {{
    btnNext.disabled = false;
    btnNext.textContent = '\\u25B6 后一天 (' + data.next_date.slice(5) + ')';
  }} else {{
    btnNext.disabled = true;
    btnNext.textContent = '\\u2714 已是最后比赛日';
  }}
  document.getElementById('today-progress-text').innerHTML =
    '第 <span>' + (data.day_index + 1) + '</span> / ' + data.total_matchdays + ' 比赛日';
  document.getElementById('today-actions').style.display = 'flex';
  document.getElementById('today-sync-info').textContent =
    '数据来源: openfootball API | 预测模型: ELO + Poisson | 上次生成: ' + new Date().toLocaleString('zh-CN');
}}

function renderTimeline(data) {{
  var total = data.total_matchdays;
  var current = data.day_index;
  var start = Math.max(0, current - 3);
  var end = Math.min(total, current + 4);
  var html = '';
  if (start > 0) html += '<span style="font-size:0.8em;">…</span>';
  for (var i = start; i < end; i++) {{
    var cls = 'dot';
    if (i < current) cls += ' done';
    else if (i === current) cls += ' active';
    html += '<span class="' + cls + '" title="第' + (i+1) + '比赛日"></span>';
  }}
  if (end < total) html += '<span style="font-size:0.8em;">…</span>';
  document.getElementById('today-timeline').innerHTML = html;
}}

function navigateDay(dir) {{
  var idx = TODAY_ALL_DATES.indexOf(TODAY_CURRENT_DATE);
  if (idx < 0) idx = 0;
  var newIdx = idx + dir;
  if (newIdx < 0 || newIdx >= TODAY_ALL_DATES.length) return;
  TODAY_CURRENT_DATE = TODAY_ALL_DATES[newIdx];
  // Save to localStorage
  try {{ localStorage.setItem('wc2026_today_date', TODAY_CURRENT_DATE); }} catch(e) {{}}
  var pred = computePredictions(TODAY_CURRENT_DATE);
  if (pred) renderTodayMatches(pred);
  // Also refresh live scores when navigating
  fetchLiveScores();
}}

// ====== Manual Refresh ======
function refreshNow() {{
  var btn = document.getElementById('btn-refresh');
  if (btn.disabled) return;
  btn.disabled = true;
  btn.classList.add('spinning');
  btn.innerHTML = '<span class="spin-icon">&#x21BB;</span> 刷新中…';

  var started = Date.now();
  fetchLiveScores().finally(function() {{
    var elapsed = Date.now() - started;
    // Ensure minimum 600ms visible feedback
    var delay = Math.max(0, 600 - elapsed);
    setTimeout(function() {{
      btn.classList.remove('spinning');
      btn.innerHTML = '<span class="spin-icon">&#x21BB;</span> 立即更新';
      btn.disabled = false;
    }}, delay);
  }});
}}

// ====== Init ======
(function() {{
  // Restore saved date
  try {{
    var saved = localStorage.getItem('wc2026_today_date');
    if (saved && TODAY_ALL_DATES.indexOf(saved) >= 0) {{
      TODAY_CURRENT_DATE = saved;
    }}
  }} catch(e) {{}}

  var pred = computePredictions(TODAY_CURRENT_DATE);
  if (!pred && TODAY_ALL_DATES.length > 0) {{
    // Auto-navigate to first date that has matches
    for (var i = 0; i < TODAY_ALL_DATES.length; i++) {{
      pred = computePredictions(TODAY_ALL_DATES[i]);
      if (pred && pred.matches && pred.matches.length > 0) {{
        TODAY_CURRENT_DATE = TODAY_ALL_DATES[i];
        break;
      }}
    }}
  }}
  if (pred) {{
    renderTodayMatches(pred);
  }} else {{
    document.getElementById('today-matches').innerHTML =
      '<div class="today-empty">暂无比赛数据</div>';
  }}

  // Fetch live scores every 5 minutes
  fetchLiveScores();
  TODAY_REFRESH_TIMER = setInterval(fetchLiveScores, 5 * 60 * 1000);
}})();
</script>
<!-- ====== End 今日比赛预测模块 ====== -->"""


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

    # ---- 第 3.5 步：加载赛程 + 计算今日预测 ----
    print("\n[3.5/5] 📅 加载赛程数据 + 计算今日比赛预测...")

    schedule_matches = []
    today_pred = None
    try:
        schedule_matches = get_all_matches(force=False)
        # Also load ELO data if not already from update
        if not results:
            with open(ELO_FILE, "r", encoding="utf-8") as f:
                elo_data = json.load(f)
        today_pred = compute_today_predictions(schedule_matches, elo_data)
        print(f"  赛程: {len(schedule_matches)} 场比赛")
        print(f"  今日: {len(today_pred['matches'])} 场 ({today_pred['date']})")
    except Exception as e:
        print(f"  ⚠️ 赛程/预测加载失败: {e}")
        today_pred = None

    # ---- 第 4 步：生成 HTML 仪表盘 ----
    print("\n[4/5] 📄 生成 HTML 仪表盘...")

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

    # ---- 注入移动端全页优化 CSS（插入到 </style> 前）----
    mobile_css = """
/* ====== 移动端全页优化 ====== */
@media (max-width: 768px) {
    body { font-size: 14px; line-height: 1.55; }
    .container { padding: 8px; }

    /* Header */
    .header { padding: 28px 16px 24px; border-radius: 10px; margin-bottom: 12px; }
    .header h1 { font-size: 1.25em; }
    .header .subtitle { font-size: 0.82em; margin-top: 6px; }
    .header .meta { font-size: 0.7em; margin-top: 8px; }

    /* 摘要卡片: 2x2 */
    .summary-grid { grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; }
    .summary-card { padding: 12px 8px; border-radius: 8px; }
    .summary-card .value { font-size: 1.4em; }
    .summary-card .label { font-size: 0.72em; }

    /* 通用卡片 */
    .card { padding: 14px 12px; margin-bottom: 12px; border-radius: 10px; }
    .card h2 { font-size: 1.05em; margin-bottom: 10px; }

    /* 夺冠 Top 20: 紧凑布局，隐藏 ELO */
    .champion-list { gap: 3px; }
    .champion-row { gap: 6px; padding: 3px 0; }
    .champion-rank { width: 22px; height: 22px; font-size: 0.7em; }
    .champion-name { width: 80px; font-size: 0.78em; }
    .champion-bar-bg { height: 16px; border-radius: 8px; }
    .champion-bar-fill { border-radius: 8px; }
    .champion-pct { width: 44px; font-size: 0.78em; }
    .champion-elo { display: none; }

    /* 数据表: 水平滚动 */
    .table-scroll { max-height: 50vh; -webkit-overflow-scrolling: touch; }
    .data-table { font-size: 0.72em; }
    .data-table th, .data-table td { padding: 6px 8px; }

    /* 双栏 → 单栏 */
    .two-col { grid-template-columns: 1fr; gap: 12px; }

    /* 小组网格 */
    .group-grid { grid-template-columns: 1fr; gap: 6px; }
    .group-item { padding: 10px 12px; }
    .group-label { font-size: 0.95em; }
    .group-teams, .group-elo { font-size: 0.74em; }

    /* Footer */
    .footer { padding: 18px; font-size: 0.72em; margin-top: 16px; }
}"""
    html = html.replace("</style>", mobile_css + "\n</style>")

    # ---- 注入今日比赛预测模块 ----
    if today_pred and schedule_matches:
        print("\n[5/5] 💉 注入今日比赛预测模块...")
        today_module_html = build_today_module_html(
            elo_data, schedule_matches, today_pred
        )
        html = html.replace(
            "<!-- ====== 全部 48 队晋级概率矩阵 ====== -->",
            today_module_html + "\n\n<!-- ====== 全部 48 队晋级概率矩阵 ====== -->"
        )
        print(f"  模块大小: {len(today_module_html):,} 字符")
    else:
        print("\n[5/5] ⏭️ 跳过今日预测（无数据）")

    save_report(html, OUTPUT_FILE)

    elapsed = time.time() - t0
    print(f"\n✅ 全部完成! 耗时 {elapsed:.1f}s")
    print(f"   仪表盘: {OUTPUT_FILE}")
    print(f"   球队数: {len(ranked)}")
    print(f"   赛果:   {len(results)} 场")
    print(f"   ELO:    {num_teams_updated} 队已更新")


if __name__ == "__main__":
    main()
