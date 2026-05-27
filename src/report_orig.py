"""
2026 世界杯预测 — HTML 中文报告生成器

输出自包含的 HTML 文件，包含：
- 夺冠概率柱状图（纯 CSS）
- 48 队完整晋级概率矩阵
- 小组难度分析
- 黑马预警
- 模型说明
"""

import json
import os
from datetime import datetime
from typing import List, Dict


# ============================================================
# 球队英文名 → 中文名映射（覆盖全部 48 支参赛队）
# ============================================================
TEAM_NAMES_CN = {
    "France":               "法国",
    "Spain":                "西班牙",
    "Argentina":            "阿根廷",
    "England":              "英格兰",
    "Portugal":             "葡萄牙",
    "Brazil":               "巴西",
    "Netherlands":          "荷兰",
    "Morocco":              "摩洛哥",
    "Belgium":              "比利时",
    "Germany":              "德国",
    "Croatia":              "克罗地亚",
    "Colombia":             "哥伦比亚",
    "Senegal":              "塞内加尔",
    "Mexico":               "墨西哥",
    "United States":        "美国",
    "Uruguay":              "乌拉圭",
    "Japan":                "日本",
    "Switzerland":          "瑞士",
    "Iran":                 "伊朗",
    "Turkey":               "土耳其",
    "Ecuador":              "厄瓜多尔",
    "Austria":              "奥地利",
    "South Korea":          "韩国",
    "Australia":            "澳大利亚",
    "Algeria":              "阿尔及利亚",
    "Egypt":                "埃及",
    "Canada":               "加拿大",
    "Norway":               "挪威",
    "Panama":               "巴拿马",
    "Ivory Coast":          "科特迪瓦",
    "Sweden":               "瑞典",
    "Paraguay":             "巴拉圭",
    "Czech Republic":       "捷克",
    "Scotland":             "苏格兰",
    "Tunisia":              "突尼斯",
    "DR Congo":             "刚果(金)",
    "Uzbekistan":           "乌兹别克斯坦",
    "Saudi Arabia":         "沙特阿拉伯",
    "South Africa":         "南非",
    "Bosnia & Herzegovina": "波黑",
    "Qatar":                "卡塔尔",
    "Ghana":                "加纳",
    "Jordan":               "约旦",
    "Iraq":                 "伊拉克",
    "Cape Verde":           "佛得角",
    "Haiti":                "海地",
    "Curacao":              "库拉索",
    "New Zealand":          "新西兰",
}

# 小组名称中文
GROUP_NAMES_CN = {
    "A": "A 组", "B": "B 组", "C": "C 组", "D": "D 组",
    "E": "E 组", "F": "F 组", "G": "G 组", "H": "H 组",
    "I": "I 组", "J": "J 组", "K": "K 组", "L": "L 组",
}

# 大洲名称中文
CONFED_CN = {
    "UEFA": "欧洲", "CONMEBOL": "南美", "CONCACAF": "中北美",
    "AFC": "亚洲", "CAF": "非洲", "OFC": "大洋洲",
}


def cn(name: str) -> str:
    """获取球队中文名，找不到则返回原名。"""
    return TEAM_NAMES_CN.get(name, name)


def gcn(group: str) -> str:
    """获取小组中文名。"""
    return GROUP_NAMES_CN.get(group, f"{group} 组")


# ============================================================
# 配色方案
# ============================================================
COLORS = {
    'gold':          '#FFD700',
    'silver':        '#C0C0C0',
    'bronze':        '#CD7F32',
    'bg':            '#0a0e27',
    'card_bg':       '#111640',
    'text':          '#e8e8ec',
    'text_secondary':'#8890b5',
    'accent':        '#4fc3f7',
    'accent2':       '#ff7043',
    'green':         '#66bb6a',
    'red':           '#ef5350',
    'bar_gradient': [
        '#FFD700', '#FFA726', '#ef5350', '#ab47bc', '#42a5f5',
        '#26c6da', '#9ccc65', '#ff7043', '#78909c', '#8d6e63'
    ],
}


def _pct_color(pct: float) -> str:
    if pct >= 15:
        return '#FFD700'
    elif pct >= 8:
        return '#FFA726'
    elif pct >= 3:
        return '#ef5350'
    elif pct >= 1:
        return '#ab47bc'
    else:
        return '#78909c'


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M')


# ============================================================
# HTML 报告生成
# ============================================================
def generate_html_report(results: List[Dict],
                         difficulties: List[Dict],
                         stats: Dict,
                         num_sims: int,
                         elo_source_date: str = "2026-05-27",
                         sync_info: dict = None) -> str:
    """生成完整中文 HTML 报告。"""

    # 夺冠概率排序（取前 20）
    champion_probs = [(r['name'], r['champion_pct'], r['code'], r['elo'], r['elo_estimated'])
                      for r in results]
    champion_probs.sort(key=lambda x: x[1], reverse=True)

    fav_name = cn(champion_probs[0][0])

    # 数据来源描述
    if sync_info:
        data_source_note = f"ELO: 实时同步 &middot; 赛果: {sync_info.get('matches_found', 0)} 场真实比分"
    else:
        data_source_note = f"ELO 评分截止 {elo_source_date}"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>2026 世界杯预测报告 | 蒙特卡洛模拟</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    background: {COLORS['bg']};
    color: {COLORS['text']};
    line-height: 1.7;
    min-height: 100vh;
}}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}

/* ---- Header ---- */
.header {{
    text-align: center;
    padding: 64px 24px 48px;
    background: linear-gradient(135deg, #1a237e 0%, #0d47a1 50%, #01579b 100%);
    border-radius: 16px;
    margin-bottom: 30px;
    position: relative;
    overflow: hidden;
}}
.header::before {{
    content: '';
    position: absolute;
    top: -50%; left: -50%;
    width: 200%; height: 200%;
    background: radial-gradient(circle, rgba(255,255,255,0.05) 0%, transparent 60%);
    animation: rotate 20s linear infinite;
}}
@keyframes rotate {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
.header h1 {{
    font-size: 2.5em;
    font-weight: 900;
    background: linear-gradient(90deg, #FFD700, #FFA726, #FFD700);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    position: relative;
    z-index: 1;
}}
.header .subtitle {{
    color: #90caf9;
    font-size: 1.05em;
    margin-top: 12px;
    position: relative;
    z-index: 1;
}}
.header .meta {{
    color: rgba(255,255,255,0.45);
    font-size: 0.82em;
    margin-top: 16px;
    position: relative;
    z-index: 1;
}}

/* ---- Cards ---- */
.card {{
    background: {COLORS['card_bg']};
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 20px;
    border: 1px solid rgba(255,255,255,0.06);
}}
.card h2 {{
    font-size: 1.25em;
    margin-bottom: 16px;
    color: {COLORS['accent']};
    display: flex;
    align-items: center;
    gap: 8px;
}}

/* ---- 摘要卡片 ---- */
.summary-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}}
.summary-card {{
    background: {COLORS['card_bg']};
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    border: 1px solid rgba(255,255,255,0.06);
}}
.summary-card .value {{
    font-size: 2em;
    font-weight: 800;
    background: linear-gradient(135deg, #FFD700, #FFA726);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}}
.summary-card .label {{
    color: {COLORS['text_secondary']};
    font-size: 0.82em;
    margin-top: 4px;
}}

/* ---- 夺冠柱状图 ---- */
.champion-list {{ display: flex; flex-direction: column; gap: 5px; }}
.champion-row {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 5px 0;
}}
.champion-rank {{
    width: 30px; height: 30px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 50%;
    font-weight: 700;
    font-size: 0.85em;
    flex-shrink: 0;
}}
.champion-rank.top1 {{ background: #FFD700; color: #1a1a2e; }}
.champion-rank.top2 {{ background: #C0C0C0; color: #1a1a2e; }}
.champion-rank.top3 {{ background: #CD7F32; color: #1a1a2e; }}
.champion-name {{
    width: 130px;
    font-weight: 600;
    font-size: 0.9em;
    flex-shrink: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.champion-bar-bg {{
    flex: 1;
    height: 24px;
    background: rgba(255,255,255,0.05);
    border-radius: 12px;
    overflow: hidden;
}}
.champion-bar-fill {{
    height: 100%;
    border-radius: 12px;
    transition: width 0.3s ease;
}}
.champion-pct {{
    width: 58px;
    text-align: right;
    font-weight: 700;
    font-size: 0.92em;
    flex-shrink: 0;
}}
.champion-elo {{
    width: 60px;
    text-align: right;
    color: {COLORS['text_secondary']};
    font-size: 0.75em;
    flex-shrink: 0;
}}

/* ---- 数据表 ---- */
.data-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.84em;
}}
.data-table th {{
    text-align: left;
    padding: 10px 12px;
    background: rgba(79, 195, 247, 0.08);
    color: {COLORS['accent']};
    font-weight: 600;
    border-bottom: 2px solid rgba(79, 195, 247, 0.2);
    font-size: 0.82em;
    white-space: nowrap;
}}
.data-table td {{
    padding: 8px 12px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}}
.data-table tr:hover {{ background: rgba(255,255,255,0.03); }}
.data-table .highlight {{ background: rgba(255, 215, 0, 0.06); }}
.data-table .right {{ text-align: right; }}

.table-scroll {{
    max-height: 72vh;
    overflow-y: auto;
    border-radius: 8px;
}}
.table-scroll thead {{
    position: sticky;
    top: 0;
    z-index: 2;
}}

/* ---- 小组难度 ---- */
.group-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 10px;
}}
.group-item {{
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
    padding: 14px 16px;
    border-left: 3px solid #555;
}}
.group-item.death {{ border-left-color: #ef5350; }}
.group-item.wide  {{ border-left-color: #66bb6a; }}
.group-label {{
    font-weight: 700;
    font-size: 1.05em;
    margin-bottom: 4px;
}}
.group-teams {{ color: {COLORS['text_secondary']}; font-size: 0.82em; }}
.group-elo   {{ color: {COLORS['text_secondary']}; font-size: 0.76em; margin-top: 2px; }}

/* ---- 黑马 ---- */
.dark-horse {{ color: {COLORS['accent2']}; font-weight: 600; }}
.tag-est {{ color: #ff9800; font-size: 0.7em; font-weight: 700; }}

/* ---- 双栏 ---- */
.two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
}}
@media (max-width: 800px) {{
    .two-col {{ grid-template-columns: 1fr; }}
    .header h1 {{ font-size: 1.7em; }}
}}

/* ---- Footer ---- */
.footer {{
    text-align: center;
    padding: 30px;
    color: {COLORS['text_secondary']};
    font-size: 0.78em;
    border-top: 1px solid rgba(255,255,255,0.06);
    margin-top: 30px;
}}
</style>
</head>
<body>

<div class="container">

<!-- ====== 标题 ====== -->
<div class="header">
    <h1>&#x26BD; 2026 年 FIFA 世界杯 &trade; 预测报告</h1>
    <div class="subtitle">
        蒙特卡洛模拟 &middot; 10,000 次迭代 &middot; ELO 评分 + 泊松分布模型
    </div>
    <div class="meta">
        数据来源：FIFA 官方抽签（2025 年 12 月）&middot;
        {data_source_note} &middot;
        生成时间：{_today()}
    </div>
</div>

<!-- ====== 摘要卡片 ====== -->
<div class="summary-grid">
    <div class="summary-card">
        <div class="value">{num_sims:,}</div>
        <div class="label">模拟次数</div>
    </div>
    <div class="summary-card">
        <div class="value">48</div>
        <div class="label">参赛球队</div>
    </div>
    <div class="summary-card">
        <div class="value">104</div>
        <div class="label">总比赛场次</div>
    </div>
    <div class="summary-card">
        <div class="value">{fav_name}</div>
        <div class="label">最大夺冠热门</div>
    </div>
</div>

<!-- ====== 夺冠概率 Top 20 ====== -->
<div class="card">
    <h2>&#x1F3C6; 夺冠概率 — 前 20 名</h2>
    <div class="champion-list">
"""
    # ---- 柱状图行 ----
    for i, (name, pct, code, elo, estimated) in enumerate(champion_probs[:20]):
        color = COLORS['bar_gradient'][min(i, len(COLORS['bar_gradient']) - 1)]
        rank_class = ''
        if i == 0:
            rank_class = 'top1'
        elif i == 1:
            rank_class = 'top2'
        elif i == 2:
            rank_class = 'top3'
        est_tag = ' <span class="tag-est">估算</span>' if estimated else ''
        html += f"""        <div class="champion-row">
            <div class="champion-rank {rank_class}">{i + 1}</div>
            <div class="champion-name">{cn(name)}{est_tag}</div>
            <div class="champion-bar-bg">
                <div class="champion-bar-fill" style="width:{min(pct * 4, 100)}%; background:{color};"></div>
            </div>
            <div class="champion-pct" style="color:{color}">{pct:.1f}%</div>
            <div class="champion-elo">ELO {elo:.0f}</div>
        </div>
"""

    html += """    </div>
</div>

<!-- ====== 全部 48 队晋级概率矩阵 ====== -->
<div class="card">
    <h2>&#x1F4CA; 全部 48 队晋级概率矩阵</h2>
    <div class="table-scroll">
    <table class="data-table">
        <thead>
            <tr>
                <th>#</th>
                <th>球队</th>
                <th>小组</th>
                <th>ELO</th>
                <th>夺冠</th>
                <th>决赛</th>
                <th>四强</th>
                <th>八强</th>
                <th>十六强</th>
                <th>三十二强</th>
                <th>小组出局</th>
            </tr>
        </thead>
        <tbody>
"""
    # ---- 表格行 ----
    for i, r in enumerate(results):
        est_mark = ' &#x26A0;' if r['elo_estimated'] else ''
        group_class = 'highlight' if i < 3 else ''
        html += f"""            <tr class="{group_class}">
                <td>{i + 1}</td>
                <td><strong>{cn(r['name'])}</strong>{est_mark}</td>
                <td>{gcn(r['group'])}</td>
                <td class="right">{r['elo']:.0f}</td>
                <td class="right" style="color:{_pct_color(r['champion_pct'])}">{r['champion_pct']:.1f}%</td>
                <td class="right" style="color:{_pct_color(r['final_pct'])}">{r['final_pct']:.1f}%</td>
                <td class="right">{r['sf_pct']:.1f}%</td>
                <td class="right">{r['qf_pct']:.1f}%</td>
                <td class="right">{r['r16_pct']:.1f}%</td>
                <td class="right">{r['r32_pct']:.1f}%</td>
                <td class="right" style="color:{COLORS['text_secondary']}">{r['group_exit_pct']:.1f}%</td>
            </tr>
"""

    html += """        </tbody>
    </table>
    </div>
</div>
"""

    # ===== 双栏：小组难度 + 黑马预警 =====
    html += """<div class="two-col">

<!-- ---- 小组难度排名 ---- -->
<div class="card">
    <h2>&#x1F4A5; 小组难度排名</h2>
"""
    for d in difficulties:
        death_class = 'death' if d['avg_elo'] > 1650 else ('wide' if d['spread'] > 500 else '')
        teams_str = ' &middot; '.join(cn(t) for t in d['teams'])
        html += f"""    <div class="group-item {death_class}">
        <div class="group-label">{gcn(d['group'])}
            <span style="font-size:0.7em;opacity:0.7">平均 ELO {d['avg_elo']:.0f}</span>
        </div>
        <div class="group-teams">{teams_str}</div>
        <div class="group-elo">
            最高 {d['max_elo']:.0f} &middot;
            最低 {d['min_elo']:.0f} &middot;
            极差 {d['spread']:.0f}
        </div>
    </div>
"""

    html += """</div>

<!-- ---- 黑马预警 ---- -->
<div class="card">
    <h2>&#x1F40E; 黑马预警</h2>
    <p style="color:#8890b5;font-size:0.84em;margin-bottom:12px;">
        ELO 排名靠后但小组出线概率较高的球队（ELO &lt; 1590 且十六强率 &gt; 40%）
    </p>
    <table class="data-table">
        <thead><tr><th>球队</th><th>小组</th><th>ELO</th><th>十六强</th><th>八强</th></tr></thead>
        <tbody>
"""
    dark_horses = [r for r in results if r['elo'] < 1590 and r['r16_pct'] > 40]
    dark_horses.sort(key=lambda x: x['r16_pct'], reverse=True)
    for dh in dark_horses[:10]:
        html += f"""        <tr>
            <td><strong class="dark-horse">{cn(dh['name'])}</strong></td>
            <td>{gcn(dh['group'])}</td>
            <td class="right">{dh['elo']:.0f}</td>
            <td class="right" style="color:{_pct_color(dh['r16_pct'])}">{dh['r16_pct']:.1f}%</td>
            <td class="right" style="color:{_pct_color(dh['qf_pct'])}">{dh['qf_pct']:.1f}%</td>
        </tr>
"""
    if not dark_horses:
        html += """        <tr><td colspan="5" style="text-align:center;color:#8890b5;">无符合条件的黑马球队</td></tr>"""

    html += """        </tbody>
    </table>
</div>

</div>"""

    # ===== 模型说明 =====
    html += f"""
<div class="card">
    <h2>&#x2699; 模型说明</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;font-size:0.84em;color:{COLORS['text_secondary']};">
        <div>
            <strong style="color:{COLORS['accent']};">第一步：ELO 评分 → 胜率</strong>
            <p style="margin-top:4px;">P(A 胜) = 1 / (1 + 10<sup>(ELO<sub>B</sub> - ELO<sub>A</sub>) / 400</sup>)</p>
        </div>
        <div>
            <strong style="color:{COLORS['accent']};">第二步：胜率 → 预期进球数</strong>
            <p style="margin-top:4px;">200 ELO 分差 ≈ 1 球优势；世界杯场均进球约 2.6 球</p>
        </div>
        <div>
            <strong style="color:{COLORS['accent']};">第三步：泊松分布模拟比分</strong>
            <p style="margin-top:4px;">P(k) = &lambda;<sup>k</sup> &middot; e<sup>-&lambda;</sup> / k! — 双方独立采样</p>
        </div>
        <div>
            <strong style="color:{COLORS['accent']};">第四步：蒙特卡洛模拟</strong>
            <p style="margin-top:4px;">{num_sims:,} 次完整锦标赛 = 每次 72 场小组赛 + 32 场淘汰赛</p>
        </div>
    </div>
    <p style="margin-top:14px;font-size:0.74em;color:#666;line-height:1.7;">
        &#x26A0; <strong>免责声明</strong>：本预测仅基于公开 ELO 评分和历史统计模型，不构成任何博彩或投资建议。
        足球比赛结果受伤病、红黄牌、天气、临场状态等大量不可预测因素影响。
        约 11 支低排名球队的 ELO 评分基于 FIFA 排名线性回归估算（标记为"估算"）。
        数据来源：worldfootballrankings.com / FIFA / roadtowc.com / OneFootball。
    </p>
</div>
"""

    # ===== 页脚 =====
    html += f"""
<div class="footer">
    <p>2026 年 FIFA 世界杯预测引擎 &middot; Python 构建 &middot; ELO + 泊松分布模型</p>
    <p>数据截止 2026 年 5 月 &middot; 蒙特卡洛模拟（{num_sims:,} 次迭代）</p>
</div>

</div>
</body>
</html>"""

    return html


def save_report(html_content: str, output_path: str):
    """保存 HTML 报告到文件。"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"中文报告已保存至：{output_path}")
