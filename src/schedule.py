#!/usr/bin/env python3
"""
2026 FIFA World Cup Match Schedule Generator

Generates the full tournament schedule from group stage to final,
based on the 48-team / 12-group format.
"""

import json
import os
import sys
from datetime import datetime, timedelta

# Ensure sibling modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import EloPoissonModel


# ---------- 2026 World Cup tentative dates ----------
TOURNAMENT_START = datetime(2026, 6, 11)   # Opening match
TOURNAMENT_END   = datetime(2026, 7, 19)   # Final

GROUP_ROUNDS = {
    # (start_day_offset, days, label)
    1: (0, 6, "小组赛第1轮"),
    2: (6, 6, "小组赛第2轮"),
    3: (12, 5, "小组赛第3轮"),
}

KNOCKOUT_SCHEDULE = [
    # (stage, label, start_offset, days, matches, teams_per_match)
    ("R32",  "三十二强",    17, 6, 16, 2),
    ("R16",  "十六强",      23, 4, 8,  2),
    ("QF",   "四分之一决赛", 27, 2, 4,  2),
    ("SF",   "半决赛",       29, 2, 2,  2),
    ("3RD",  "三四名决赛",   34, 1, 1,  2),
    ("FINAL","决赛",         35, 1, 1,  2),
]


def generate_group_schedule(groups_data: dict) -> list:
    """Generate all group-stage matches with dates. Returns list of match dicts."""
    matches = []
    group_names = sorted(groups_data.keys())

    for round_num, (offset, days, label) in GROUP_ROUNDS.items():
        round_start = TOURNAMENT_START + timedelta(days=offset)
        match_idx = 0

        for grp in group_names:
            teams = groups_data[grp]
            a0, a1, a2, a3 = teams[0]["name"], teams[1]["name"], teams[2]["name"], teams[3]["name"]

            if round_num == 1:
                pairings = [(a0, a3), (a1, a2)]
            elif round_num == 2:
                pairings = [(a0, a2), (a3, a1)]
            else:
                pairings = [(a0, a1), (a2, a3)]

            for home, away in pairings:
                day = round_start + timedelta(days=match_idx % days)
                matches.append({
                    "date": day.strftime("%Y-%m-%d"),
                    "stage": f"小组赛R{round_num}",
                    "stage_label": label,
                    "group": grp,
                    "home": home,
                    "away": away,
                })
                match_idx += 1

    return matches


def generate_knockout_schedule() -> list:
    """Generate knockout-stage match placeholders with dates. Returns list of match dicts."""
    matches = []

    for code, label, offset, days, total, _ in KNOCKOUT_SCHEDULE:
        start = TOURNAMENT_START + timedelta(days=offset)
        for i in range(total):
            day = start + timedelta(days=i % days)
            matches.append({
                "date": day.strftime("%Y-%m-%d"),
                "stage": code,
                "stage_label": label,
                "group": None,
                "home": "待定",
                "away": "待定",
            })

    return matches


def build_full_schedule(groups_file: str) -> list:
    """Build the complete tournament schedule from groups.json."""
    with open(groups_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    groups = data["groups"]
    group_matches = generate_group_schedule(groups)
    knockout_matches = generate_knockout_schedule()
    return group_matches + knockout_matches


def get_daily_summary(schedule: list) -> dict:
    """Return a dict of {date: {teams: set, matches: list}} grouped by date."""
    daily = {}
    for m in schedule:
        d = m["date"]
        if d not in daily:
            daily[d] = {"teams": set(), "matches": [], "stages": set()}
        if m["home"] != "待定":
            daily[d]["teams"].add(m["home"])
        if m["away"] != "待定":
            daily[d]["teams"].add(m["away"])
        daily[d]["matches"].append(m)
        daily[d]["stages"].add(m["stage_label"])

    return daily


def get_today_summary(schedule: list) -> dict:
    """Get today's match summary. Returns None if no matches today."""
    today = datetime.now().strftime("%Y-%m-%d")
    daily = get_daily_summary(schedule)

    if today in daily:
        info = daily[today]
        return {
            "date": today,
            "team_count": len(info["teams"]),
            "match_count": len(info["matches"]),
            "teams": sorted(list(info["teams"])),
            "matches": info["matches"],
            "stages": list(info["stages"]),
        }
    return None


def get_upcoming_summary(schedule: list, days: int = 7) -> list:
    """Get upcoming N days of match summaries from today onwards."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    daily = get_daily_summary(schedule)

    result = []
    for d in sorted(daily.keys()):
        if d >= today_str and len(result) < days:
            info = daily[d]
            result.append({
                "date": d,
                "day_of_week": datetime.strptime(d, "%Y-%m-%d").strftime("%A"),
                "team_count": len(info["teams"]),
                "match_count": len(info["matches"]),
                "teams": sorted(list(info["teams"])),
                "matches": info["matches"][:6],  # limit matches in summary
                "stages": list(info["stages"]),
            })

    return result


def get_match_predictions(schedule: list, effective_date: str,
                          elo_data: dict, teams_lookup: dict) -> dict:
    """Get today's matches with win/draw/loss probabilities and expected goals.

    Args:
        schedule: Full match schedule list
        effective_date: The date to query (YYYY-MM-DD)
        elo_data: Dict of {code: {"elo": float, "name": str, ...}}
        teams_lookup: Dict of {team_name_en: code} for ELO lookup

    Returns:
        Dict with matches array containing prediction data, or None if no matches.
    """
    model = EloPoissonModel()

    today_matches = [m for m in schedule if m["date"] == effective_date]
    if not today_matches:
        return None

    all_dates = sorted(set(m["date"] for m in schedule))
    try:
        day_index = all_dates.index(effective_date)
    except ValueError:
        day_index = 0

    matches_with_pred = []
    for m in today_matches:
        home = m["home"]
        away = m["away"]
        stage = m["stage_label"]
        grp = m.get("group")

        # Knockout TBD matches — show placeholder
        if home == "待定" or away == "待定":
            matches_with_pred.append({
                "home": home, "away": away,
                "home_cn": home, "away_cn": away,
                "group": grp, "stage": stage,
                "tbd": True, "completed": False,
            })
            continue

        # Look up ELO ratings
        home_code = teams_lookup.get(home, "")
        away_code = teams_lookup.get(away, "")
        home_elo_info = elo_data.get(home_code, {}) if home_code else {}
        away_elo_info = elo_data.get(away_code, {}) if away_code else {}
        home_elo = home_elo_info.get("elo", 1500.0)
        away_elo = away_elo_info.get("elo", 1500.0)

        # Calculate probabilities (Poisson exact)
        p_home, p_draw, p_away = model.match_outcome_probabilities(home_elo, away_elo)

        # Expected goals (lambda)
        lambda_home, lambda_away = model.expected_goals(home_elo, away_elo)

        matches_with_pred.append({
            "home": home,
            "away": away,
            "home_code": home_code,
            "away_code": away_code,
            "home_elo": round(home_elo),
            "away_elo": round(away_elo),
            "group": grp,
            "stage": stage,
            "home_win_pct": round(p_home * 100, 1),
            "draw_pct": round(p_draw * 100, 1),
            "away_win_pct": round(p_away * 100, 1),
            "expected_goals_home": round(lambda_home, 2),
            "expected_goals_away": round(lambda_away, 2),
            "total_expected_goals": round(lambda_home + lambda_away, 2),
            "completed": False,
            "tbd": False,
        })

    # Build summary
    total_real = sum(1 for m in matches_with_pred if not m.get("tbd"))

    return {
        "date": effective_date,
        "day_index": day_index,
        "total_matchdays": len(all_dates),
        "stage_label": today_matches[0]["stage_label"] if today_matches else "",
        "matches": matches_with_pred,
        "total_matches": len(matches_with_pred),
        "total_real_matches": total_real,
        "has_next": day_index < len(all_dates) - 1,
        "has_prev": day_index > 0,
        "next_date": all_dates[day_index + 1] if day_index < len(all_dates) - 1 else None,
        "prev_date": all_dates[day_index - 1] if day_index > 0 else None,
    }


def get_tournament_progress(schedule: list) -> dict:
    """Return overall tournament progress statistics."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    all_dates = sorted(set(m["date"] for m in schedule))
    total_dates = len(all_dates)
    completed = sum(1 for d in all_dates if d < today_str)
    
    total_matches = len(schedule)
    completed_matches = sum(1 for m in schedule if m["date"] < today_str)
    remaining = total_matches - completed_matches

    # Total unique teams  
    all_teams = set()
    for m in schedule:
        if m["home"] != "待定":
            all_teams.add(m["home"])
        if m["away"] != "待定":
            all_teams.add(m["away"])

    return {
        "tournament_start": TOURNAMENT_START.strftime("%Y-%m-%d"),
        "tournament_end": TOURNAMENT_END.strftime("%Y-%m-%d"),
        "total_teams": len(all_teams),
        "total_matches": total_matches,
        "total_matchdays": total_dates,
        "completed_matchdays": completed,
        "completed_matches": completed_matches,
        "remaining_matches": remaining,
        "today": today_str,
    }
