"""
Monte Carlo Simulation Engine for 2026 FIFA World Cup

Runs N simulations of the entire tournament:
1. Group stage: 12 groups × 6 matches = 72 matches
2. Determine qualifiers: Top 2 + 8 best 3rd place teams
3. Knockout stage: R32 → R16 → QF → SF → Final
4. Aggregate statistics across all simulations
"""

import json
import sys
import os
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import EloPoissonModel
from bracket import build_round_of_32, simulate_full_knockout


class WorldCupSimulator:
    """Full tournament simulator with Monte Carlo aggregation."""

    def __init__(self, groups_file: str, elo_file: str, num_sims: int = 10000, seed: int = 42,
                 completed_matches: List[Dict] = None):
        self.groups_data = self._load_json(groups_file)
        self.elo_data = self._load_json(elo_file)
        self.num_sims = num_sims
        self.model = EloPoissonModel(seed=seed)

        # 已完赛真实比分（融入模拟中）
        #   [{team_a, team_b, goals_a, goals_b, stage, group}, ...]
        self.completed_matches = completed_matches or []

        # Build team list with ELO
        self.teams = self._build_team_list()

        # 根据赛果预先更新 ELO（确保跑 N 次模拟时基数是赛后 ELO）
        self._apply_completed_elo_updates()

        # Statistics accumulators
        self.reset_stats()

    @staticmethod
    def _load_json(path: str) -> dict:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _build_team_list(self) -> Dict[str, Dict]:
        """Build a lookup of all 48 teams with their group and ELO."""
        teams = {}
        elo_team_data = self.elo_data['teams']

        for group_name, group_teams in self.groups_data['groups'].items():
            for team in group_teams:
                code = team['code']
                elo_info = elo_team_data.get(code, {'elo': 1400, 'estimated': True})
                teams[code] = {
                    'name': team['name'],
                    'code': code,
                    'group': group_name,
                    'confederation': team['confederation'],
                    'fifa_rank': team['fifa_rank'],
                    'elo': elo_info['elo'],
                    'elo_estimated': elo_info.get('estimated', False)
                }
        return teams

    def _apply_completed_elo_updates(self):
        """根据已完赛真实比分更新 ELO 基数。
        
        使用标准 ELO 公式更新一次（赛前 → 赛后），之后的蒙特卡洛模拟
        都基于赛后 ELO。这确保已发生的比赛结果被正确反映。
        """
        if not self.completed_matches:
            return

        K = 30  # 世界杯权重
        for match in self.completed_matches:
            a = match.get("team_a", "")
            b = match.get("team_b", "")
            ga = match.get("goals_a", 0)
            gb = match.get("goals_b", 0)
            if a not in self.teams or b not in self.teams:
                continue

            elo_a = self.teams[a]["elo"]
            elo_b = self.teams[b]["elo"]
            e_a = 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))

            if ga > gb:
                actual = 1.0
            elif gb > ga:
                actual = 0.0
            else:
                actual = 0.5

            delta = K * (actual - e_a)
            self.teams[a]["elo"] = elo_a + delta
            self.teams[b]["elo"] = elo_b - delta

    def _get_completed_group_match(self, team_a_code: str, team_b_code: str,
                                   group_name: str) -> Optional[Dict]:
        """查找小组赛中两队之间是否已有真实完赛记录。"""
        for m in self.completed_matches:
            if m.get("stage") != "group":
                continue
            if m.get("group") != group_name:
                continue
            codes = {m.get("team_a", ""), m.get("team_b", "")}
            if codes == {team_a_code, team_b_code}:
                return m
        return None

    def reset_stats(self):
        """Reset all simulation statistics."""
        self.stats = {
            # Per-team stats
            'champion_count': defaultdict(int),
            'final_count': defaultdict(int),
            'sf_count': defaultdict(int),
            'qf_count': defaultdict(int),
            'r16_count': defaultdict(int),
            'r32_count': defaultdict(int),
            'group_exit_count': defaultdict(int),

            # Group stage stats
            'group_standings': defaultdict(lambda: defaultdict(lambda: {
                'pts': 0, 'goals_for': 0, 'goals_against': 0, 'wins': 0, 'draws': 0, 'losses': 0
            })),

            # Counters
            'total_sims': 0,
            'most_common_champion': None,
            'most_common_final': None,
        }

    def simulate_group_stage(self) -> Tuple[Dict, List[Dict]]:
        """
        Simulate the entire group stage (72 matches).

        Returns:
            standings: Dict[group_name] → sorted list of team stats
            all_third: List of 3rd place team stats from all groups
        """
        group_names = list(self.groups_data['groups'].keys())
        standings = {}
        all_third = []

        for group_name in group_names:
            group_teams = self.groups_data['groups'][group_name]

            # Initialize team records
            records = {}
            for team in group_teams:
                code = team['code']
                records[code] = {
                    'code': code,
                    'name': team['name'],
                    'group': group_name,
                    'elo': self.teams[code]['elo'],
                    'pts': 0,
                    'gf': 0,   # goals for
                    'ga': 0,   # goals against
                    'gd': 0,   # goal difference
                    'w': 0, 'd': 0, 'l': 0
                }

            # Play all 6 matches in the group (round-robin)
            for i in range(4):
                for j in range(i + 1, 4):
                    team_a = group_teams[i]
                    team_b = group_teams[j]

                    # 检查是否有真实完赛比分
                    completed = self._get_completed_group_match(
                        team_a['code'], team_b['code'], group_name
                    )

                    if completed:
                        # 使用真实比分（不模拟）
                        ga = completed["goals_a"]
                        gb = completed["goals_b"]
                        # 判断主客方向
                        if completed["team_a"] == team_a['code']:
                            pts_a = 3 if ga > gb else (1 if ga == gb else 0)
                            pts_b = 3 if gb > ga else (1 if ga == gb else 0)
                        else:
                            # 数据中 team_a/team_b 方向可能与 group_teams 一致，
                            # 但进球数需要调整
                            pts_a = 3 if gb > ga else (1 if gb == ga else 0)
                            pts_b = 3 if ga > gb else (1 if ga == gb else 0)
                            ga, gb = gb, ga  # 交换进球数
                    else:
                        # 泊松模拟
                        elo_a = self.teams[team_a['code']]['elo']
                        elo_b = self.teams[team_b['code']]['elo']
                        ga, gb, pts_a, pts_b = self.model.simulate_group_match(elo_a, elo_b)

                    # Update records
                    rec_a = records[team_a['code']]
                    rec_b = records[team_b['code']]
                    rec_a['gf'] += ga
                    rec_a['ga'] += gb
                    rec_b['gf'] += gb
                    rec_b['ga'] += ga
                    rec_a['pts'] += pts_a
                    rec_b['pts'] += pts_b

                    if pts_a == 3:
                        rec_a['w'] += 1
                        rec_b['l'] += 1
                    elif pts_b == 3:
                        rec_b['w'] += 1
                        rec_a['l'] += 1
                    else:
                        rec_a['d'] += 1
                        rec_b['d'] += 1

            # Calculate goal difference
            for rec in records.values():
                rec['gd'] = rec['gf'] - rec['ga']

            # Sort by points, then GD, then GF
            sorted_teams = sorted(records.values(),
                                  key=lambda t: (t['pts'], t['gd'], t['gf']),
                                  reverse=True)

            standings[group_name] = sorted_teams
            all_third.append(sorted_teams[2])  # 3rd place team

        return standings, all_third

    def determine_qualifiers(self, standings: Dict, all_third: List[Dict]) -> Dict:
        """
        Determine the 32 teams advancing to knockout stage.

        Returns:
            qualified: Dict with keys '1st', '2nd', '3rd'
        """
        qualified = {'1st': [], '2nd': [], '3rd': []}

        for group_name, teams in standings.items():
            qualified['1st'].append(teams[0])
            qualified['2nd'].append(teams[1])

        # Sort 3rd place teams: points, GD, GF → take top 8
        sorted_third = sorted(all_third, key=lambda t: (t['pts'], t['gd'], t['gf']), reverse=True)
        qualified['3rd'] = sorted_third[:8]

        return qualified

    def run_single_simulation(self) -> Dict:
        """Run one complete tournament simulation."""
        # 1. Group stage
        standings, all_third = self.simulate_group_stage()

        # 2. Determine qualifiers
        qualified = self.determine_qualifiers(standings, all_third)

        # 3. Build R32 bracket
        r32_matches = build_round_of_32(qualified)

        # 4. Run knockout stage
        knockout_result = simulate_full_knockout(r32_matches, self.model, self.completed_matches)

        return {
            'standings': standings,
            'qualified': qualified,
            'r32_matches': r32_matches,
            'knockout': knockout_result
        }

    def update_stats(self, result: Dict):
        """Update cumulative statistics with one simulation result."""
        knockout = result['knockout']
        qualified = result['qualified']

        # Track knockout progression
        champion = knockout['champion']
        self.stats['champion_count'][champion['code']] += 1

        for team in knockout['finalists']:
            self.stats['final_count'][team['code']] += 1
        for team in knockout['sf']:
            self.stats['sf_count'][team['code']] += 1
        for team in knockout['qf']:
            self.stats['qf_count'][team['code']] += 1
        for team in knockout['r16']:
            self.stats['r16_count'][team['code']] += 1
        for cat in ['1st', '2nd', '3rd']:
            for team in qualified[cat]:
                self.stats['r32_count'][team['code']] += 1

        # Track group stage exits
        all_qualifier_codes = set()
        for cat in ['1st', '2nd', '3rd']:
            for team in qualified[cat]:
                all_qualifier_codes.add(team['code'])

        for code in self.teams:
            if code not in all_qualifier_codes:
                self.stats['group_exit_count'][code] += 1

        self.stats['total_sims'] += 1

    def run(self, progress_callback=None) -> Dict:
        """
        Run all Monte Carlo simulations.

        Args:
            progress_callback: Optional callback(sim_index, total) for progress reporting

        Returns:
            Aggregated statistics dictionary
        """
        self.reset_stats()

        for i in range(self.num_sims):
            result = self.run_single_simulation()
            self.update_stats(result)

            if progress_callback and (i + 1) % max(1, self.num_sims // 20) == 0:
                progress_callback(i + 1, self.num_sims)

        return self.stats

    def get_ranked_results(self) -> List[Dict]:
        """Get teams ranked by championship probability."""
        results = []
        total = self.stats['total_sims']
        if total == 0:
            return results

        for code, team in self.teams.items():
            results.append({
                'code': code,
                'name': team['name'],
                'group': team['group'],
                'elo': team['elo'],
                'elo_estimated': team['elo_estimated'],
                'fifa_rank': team['fifa_rank'],
                'champion_pct': self.stats['champion_count'][code] / total * 100,
                'final_pct': self.stats['final_count'][code] / total * 100,
                'sf_pct': self.stats['sf_count'][code] / total * 100,
                'qf_pct': self.stats['qf_count'][code] / total * 100,
                'r16_pct': self.stats['r16_count'][code] / total * 100,
                'r32_pct': self.stats['r32_count'][code] / total * 100,
                'group_exit_pct': self.stats['group_exit_count'][code] / total * 100,
                'champion_count': self.stats['champion_count'][code],
            })

        results.sort(key=lambda x: x['champion_pct'], reverse=True)
        return results

    def get_group_difficulty(self) -> List[Dict]:
        """Calculate group difficulty (average ELO of group)."""
        difficulties = []
        for group_name, group_teams in self.groups_data['groups'].items():
            elos = [self.teams[t['code']]['elo'] for t in group_teams]
            avg_elo = sum(elos) / len(elos)
            max_elo = max(elos)
            min_elo = min(elos)
            spread = max_elo - min_elo
            difficulties.append({
                'group': group_name,
                'avg_elo': avg_elo,
                'max_elo': max_elo,
                'min_elo': min_elo,
                'spread': spread,
                'teams': [t['name'] for t in group_teams]
            })
        difficulties.sort(key=lambda x: x['avg_elo'], reverse=True)
        return difficulties


def default_progress(current, total):
    """Default progress callback: print to console."""
    pct = current / total * 100
    print(f"\r  Simulating... {current}/{total} ({pct:.0f}%)", end='', flush=True)


if __name__ == "__main__":
    # Quick test with fewer sims
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    groups_file = os.path.join(base_dir, 'data', 'groups.json')
    elo_file = os.path.join(base_dir, 'data', 'elo_ratings.json')

    sim = WorldCupSimulator(groups_file, elo_file, num_sims=1000, seed=42)
    print("Running 1000 simulations...")
    stats = sim.run(progress_callback=default_progress)
    print("\n")

    results = sim.get_ranked_results()
    print("Top 10 Champion Probabilities:")
    print("-" * 60)
    for i, r in enumerate(results[:10]):
        est = " (est.)" if r['elo_estimated'] else ""
        print(f"  {i+1:2d}. {r['name']:<20s} ELO:{r['elo']:.0f}{est}  "
              f"Champion: {r['champion_pct']:5.1f}%  Final: {r['final_pct']:5.1f}%")
