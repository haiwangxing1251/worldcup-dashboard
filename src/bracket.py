"""
2026 FIFA World Cup Knockout Bracket

Defines the Round-of-32 bracket structure for the 48-team format.
Top 2 from each group (24 teams) + 8 best 3rd-place teams = 32 teams advance.

The bracket follows the official 2026 FIFA World Cup format with 12 groups (A-L).
"""

from typing import List, Dict, Tuple

# Group names in order
GROUP_NAMES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']


# Official FIFA 2026 bracket: Round of 32 match slots
# Each slot defines which group positions play each other
# Format: (slot_name, [possible_matchups])
# For group winners vs 3rd placers, the 3rd place opponent depends on
# which specific groups produce the 8 best 3rd place teams.
# We use a simplified deterministic assignment.

def build_round_of_32(qualified: Dict[str, List[Dict]]) -> List[Tuple]:
    """
    Build Round of 32 matchups from qualified teams.

    Args:
        qualified: Dict mapping group_position -> list of team dicts
                   Keys: '1st', '2nd', '3rd'
                   Each team dict has: name, code, elo, group, pts, gd, gf

    Returns:
        List of (team_a, team_b) tuples representing R32 matches
    """
    # Sort group winners by ELO for bracket seeding
    winners = qualified['1st']  # 12 group winners
    runners_up = qualified['2nd']  # 12 group runners-up
    third_place = qualified['3rd']  # 8 best 3rd place teams

    # Build a bracket following 2026 format:
    # R32 matches are pre-determined by group positions
    # We use the official bracket structure:

    # Define R32 slots: (position_a, position_b)
    # 1Wx = Winner of Group x, 2Rx = Runner-up of Group x, 3Tx = 3rd place slot x
    r32_template = [
        # Top half
        ('1WA', '3T1'),   # Winner A vs 3rd Place 1
        ('2RA', '2RB'),   # Runner-up A vs Runner-up B
        ('1WE', '3T2'),   # Winner E vs 3rd Place 2
        ('1WF', '2RC'),   # Winner F vs Runner-up C
        ('1WC', '3T3'),   # Winner C vs 3rd Place 3
        ('1WD', '2RE'),   # Winner D vs Runner-up E
        ('2RD', '2RF'),   # Runner-up D vs Runner-up F
        ('1WG', '3T4'),   # Winner G vs 3rd Place 4

        # Bottom half
        ('1WH', '2RG'),   # Winner H vs Runner-up G
        ('1WB', '3T5'),   # Winner B vs 3rd Place 5
        ('1WI', '3T6'),   # Winner I vs 3rd Place 6
        ('2RI', '2RJ'),   # Runner-up I vs Runner-up J
        ('1WJ', '3T7'),   # Winner J vs 3rd Place 7
        ('1WK', '2RL'),   # Winner K vs Runner-up L
        ('1WL', '3T8'),   # Winner L vs 3rd Place 8
        ('2RK', '2RH'),   # Runner-up K vs Runner-up H
    ]

    # Lookup helpers
    winner_map = {t['group']: t for t in winners}
    runner_map = {t['group']: t for t in runners_up}

    # Assign 3rd place teams to slots (1-8)
    # Sort 3rd place teams by points, GD, GF for ordering
    third_sorted = sorted(third_place, key=lambda t: (t['pts'], t['gd'], t['gf']), reverse=True)

    matches = []
    for slot_a, slot_b in r32_template:
        team_a = _resolve_slot(slot_a, winner_map, runner_map, third_sorted)
        team_b = _resolve_slot(slot_b, winner_map, runner_map, third_sorted)

        if team_a and team_b:
            matches.append((team_a, team_b))
        else:
            # Fallback: shouldn't happen with valid data
            # If a 3rd place slot is unresolved, skip
            pass

    # Ensure we have exactly 16 matches
    if len(matches) != 16:
        raise ValueError(f"Expected 16 R32 matches, got {len(matches)}")

    return matches


def _resolve_slot(slot: str, winner_map: Dict, runner_map: Dict, third_sorted: List[Dict]) -> Dict:
    """Resolve a bracket slot to an actual team."""
    if slot.startswith('1W'):
        group = slot[2]
        return winner_map.get(group)
    elif slot.startswith('2R'):
        group = slot[2]
        return runner_map.get(group)
    elif slot.startswith('3T'):
        idx = int(slot[2:]) - 1  # 0-indexed
        if idx < len(third_sorted):
            return third_sorted[idx]
    return None


def run_knockout_round(teams: List[Dict], model, completed_matches: List[Dict] = None) -> List[Dict]:
    """
    Run one knockout round. Takes list of paired teams, returns list of winners.

    Args:
        teams: List of team dicts, paired as [a1, b1, a2, b2, ...]
        model: EloPoissonModel instance
        completed_matches: List of completed match dicts (optional)

    Returns:
        List of winning team dicts (half the original length)
    """
    completed = completed_matches or []
    completed_codes = set()
    for m in completed:
        if m.get("stage") not in ("group",):
            completed_codes.add(frozenset([m.get("team_a", ""), m.get("team_b", "")]))

    winners = []
    for i in range(0, len(teams), 2):
        team_a = teams[i]
        team_b = teams[i + 1]

        # 检查是否有真实完赛记录
        pair_key = frozenset([team_a['code'], team_b['code']])
        real_result = None
        for m in completed:
            m_key = frozenset([m.get("team_a", ""), m.get("team_b", "")])
            if m_key == pair_key and m.get("stage") != "group":
                real_result = m
                break

        if real_result:
            # 使用真实比分
            ga = real_result.get("goals_a", 0)
            gb = real_result.get("goals_b", 0)
            if real_result["team_a"] == team_a['code']:
                winner = team_a if ga > gb else team_b
            else:
                winner = team_a if gb > ga else team_b
            winners.append(winner)
        else:
            result = model.simulate_knockout_match(team_a['elo'], team_b['elo'])
            winners.append(team_a if result == 'A' else team_b)

    return winners


def simulate_full_knockout(r32_matches: List[Tuple], model, completed_matches: List[Dict] = None) -> Dict:
    """
    Run the entire knockout stage from R32 to champion.

    Args:
        r32_matches: R32 pairings
        model: EloPoissonModel instance
        completed_matches: Optional list of real match results

    Returns:
        Dict with r16, qf, sf, finalists, champion, third_place
    """
    # R32: 32 teams → 16
    r32_teams = []
    for a, b in r32_matches:
        r32_teams.append(a)
        r32_teams.append(b)
    r16_teams = run_knockout_round(r32_teams, model, completed_matches)

    # R16: 16 teams → 8
    qf_teams = run_knockout_round(r16_teams, model, completed_matches)

    # Quarter-finals: 8 teams → 4
    sf_teams = run_knockout_round(qf_teams, model, completed_matches)

    # Semi-finals: 4 teams → 2
    finalists = run_knockout_round(sf_teams, model, completed_matches)

    # Final
    champion_team = run_knockout_round(finalists, model, completed_matches)[0]

    # Third place match
    third_place = [t for t in sf_teams if t not in finalists]
    if len(third_place) == 2:
        third_winner = run_knockout_round(third_place, model, completed_matches)[0]
    else:
        third_winner = None

    return {
        'r16': r16_teams,
        'qf': qf_teams,
        'sf': sf_teams,
        'finalists': finalists,
        'champion': champion_team,
        'third_place': third_winner
    }


def get_knockout_tree(r32_matches: List[Tuple]) -> Dict:
    """
    Build the full knockout tree structure for visualization.
    Returns a nested dict representing the complete bracket.
    """
    # 16 R32 matches → 8 R16 → 4 QF → 2 SF → Final
    tree = {
        'r32': [],
        'r16': [],
        'qf': [],
        'sf': [],
        'final': None,
        'third_place': None
    }
    for a, b in r32_matches:
        tree['r32'].append({
            'team_a': a['name'], 'code_a': a['code'],
            'team_b': b['name'], 'code_b': b['code'],
            'winner': None
        })
    return tree
