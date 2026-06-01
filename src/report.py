"""
2026 世界杯预测 — HTML 中文报告生成器

输出自包含的 HTML 文件，包含：
- 夺冠概率柱状图（纯 CSS）
- 48 队完整晋级概率矩阵
- 小组难度分析
- 黑马预警
- 模型说明
"""

import os
from datetime import datetime, timedelta, timezone
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
    """返回北京时间 (UTC+8) 格式化时间，HTML 中用 JS 动态显示"X分钟前"。"""
    beijing_tz = timezone(timedelta(hours=8))
    return datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M')


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

    # 生成时间（北京时间 + UTC 用于 JS 动态显示）
    gen_timestamp_utc = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

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

/* ---- 可排序表头 ---- */
.sortable {{
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
}}
.sortable:hover {{ color: #FFD700; }}
.sortable.sort-asc::after {{ content: ' ▲'; font-size:0.75em; color:#FFD700; }}
.sortable.sort-desc::after {{ content: ' ▼'; font-size:0.75em; color:#FFD700; }}

/* ---- 球队详情弹窗 ---- */
#team-modal {{
    display:none;
    position:fixed;top:0;left:0;width:100%;height:100%;
    background:rgba(0,0,0,0.7);z-index:8888;
    align-items:center;justify-content:center;
}}
#team-modal.open {{ display:flex; }}
#team-modal-body {{
    background:#111640;border-radius:16px;padding:24px;
    max-width:480px;width:90%;max-height:85vh;overflow-y:auto;
    border:1px solid rgba(255,255,255,0.1);position:relative;
}}
#team-modal-close {{
    position:absolute;top:12px;right:14px;
    background:none;border:none;color:#8890b5;font-size:1.4em;cursor:pointer;
}}

/* ---- 竞猜弹窗 ---- */
#guess-modal {{
    display:none;
    position:fixed;top:0;left:0;width:100%;height:100%;
    background:rgba(0,0,0,0.75);z-index:8888;
    align-items:flex-start;justify-content:center;overflow-y:auto;
    padding:20px 0;
}}
#guess-modal.open {{ display:flex; }}
#guess-modal-body {{
    background:#111640;border-radius:16px;padding:24px;
    max-width:560px;width:92%;
    border:1px solid rgba(255,255,255,0.1);position:relative;
    margin:auto;
}}

/* ---- 淘汰赛图 ---- */
.bracket-wrap {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
.bracket-svg text {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; }}

/* ---- 通知按钮 ---- */
#notify-btn {{
    display:inline-flex;align-items:center;gap:6px;
    padding:8px 16px;border-radius:8px;border:1px solid rgba(255,215,0,0.4);
    background:rgba(255,215,0,0.08);color:#FFD700;font-size:0.84em;cursor:pointer;
    transition:background 0.2s;
}}
#notify-btn:hover {{ background:rgba(255,215,0,0.15); }}
#notify-btn.active {{ background:rgba(102,187,106,0.15);color:#66bb6a;border-color:rgba(102,187,106,0.4); }}
</style>
</head>
<body>

<!-- ====== 密码门遮罩 ====== -->
<div id="pwd-overlay" style="position:fixed;top:0;left:0;width:100%;height:100%;background:#0a0e27;z-index:9999;display:flex;align-items:center;justify-content:center;">
  <div style="text-align:center;max-width:360px;padding:20px;">
    <h2 style="color:#FFD700;font-size:1.6em;margin-bottom:6px;">&#x26BD; 2026 世界杯预测</h2>
    <p style="color:#8890b5;margin-bottom:20px;font-size:0.88em;">请输入访问密码</p>
    <input id="pwd-input" type="password" placeholder="输入密码..." autofocus style="width:100%;padding:12px 16px;border-radius:8px;border:1px solid rgba(255,255,255,0.15);background:#111640;color:#e8e8ec;font-size:1em;outline:none;box-sizing:border-box;"/>
    <p id="pwd-err" style="color:#ef5350;font-size:0.82em;margin-top:8px;display:none;">密码错误，请重试</p>
    <button onclick="wcCheckPwd()" style="width:100%;margin-top:16px;padding:12px;border-radius:8px;border:none;background:linear-gradient(135deg,#FFD700,#FFA726);color:#1a1a2e;font-size:1em;font-weight:700;cursor:pointer;">确认进入</button>
  </div>
</div>

<div id="protected-content" style="display:none;">

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
        生成时间：<span data-utc="{gen_timestamp_utc}">{_today()} 北京时间</span>
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
<div class="card" id="matrix-card">
    <h2>&#x1F4CA; 全部 48 队晋级概率矩阵
        <button onclick="wcShareCard()" style="margin-left:auto;padding:6px 14px;border-radius:8px;border:none;background:linear-gradient(135deg,#FFD700,#FFA726);color:#1a1a2e;font-size:0.75em;font-weight:700;cursor:pointer;">&#x1F4F1; 分享</button>
    </h2>
    <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center;">
        <input id="matrix-search" type="text" placeholder="&#x1F50D; 搜索球队..." oninput="wcFilterMatrix()" style="flex:1;min-width:140px;padding:8px 12px;border-radius:8px;border:1px solid rgba(255,255,255,0.12);background:#0a0e27;color:#e8e8ec;font-size:0.88em;outline:none;"/>
        <select id="matrix-group-filter" onchange="wcFilterMatrix()" style="padding:8px 10px;border-radius:8px;border:1px solid rgba(255,255,255,0.12);background:#0a0e27;color:#e8e8ec;font-size:0.85em;outline:none;">
            <option value="">全部小组</option>
            <option value="A">A 组</option><option value="B">B 组</option><option value="C">C 组</option>
            <option value="D">D 组</option><option value="E">E 组</option><option value="F">F 组</option>
            <option value="G">G 组</option><option value="H">H 组</option><option value="I">I 组</option>
            <option value="J">J 组</option><option value="K">K 组</option><option value="L">L 组</option>
        </select>
        <span id="matrix-count" style="color:#8890b5;font-size:0.78em;white-space:nowrap;">48 支球队</span>
    </div>
    <div class="table-scroll">
    <table class="data-table" id="matrix-table">
        <thead>
            <tr>
                <th onclick="wcSortMatrix(0)" class="sortable" data-col="0">#</th>
                <th onclick="wcSortMatrix(1)" class="sortable" data-col="1">球队</th>
                <th onclick="wcSortMatrix(2)" class="sortable" data-col="2">小组</th>
                <th onclick="wcSortMatrix(3)" class="sortable" data-col="3">ELO &#x25BD;</th>
                <th onclick="wcSortMatrix(4)" class="sortable" data-col="4">夺冠</th>
                <th onclick="wcSortMatrix(5)" class="sortable" data-col="5">决赛</th>
                <th onclick="wcSortMatrix(6)" class="sortable" data-col="6">四强</th>
                <th onclick="wcSortMatrix(7)" class="sortable" data-col="7">八强</th>
                <th onclick="wcSortMatrix(8)" class="sortable" data-col="8">十六强</th>
                <th onclick="wcSortMatrix(9)" class="sortable" data-col="9">三十二强</th>
                <th onclick="wcSortMatrix(10)" class="sortable" data-col="10">小组出局</th>
            </tr>
        </thead>
        <tbody id="matrix-tbody">
"""
    # ---- 表格行 ----
    for i, r in enumerate(results):
        est_mark = ' &#x26A0;' if r['elo_estimated'] else ''
        group_class = 'highlight' if i < 3 else ''
        cn_name = cn(r['name'])
        # JS 字符串安全转义：生成单引号包裹的JS字符串，内部单引号转义
        name_js = "'" + r['name'].replace("\\", "\\\\").replace("'", "\\'") + "'"
        group_js = "'" + r['group'].replace("\\", "\\\\").replace("'", "\\'") + "'"
        html += f"""            <tr class="{group_class}" data-name="{cn_name}" data-en="{r['name']}" data-group="{r['group']}" data-elo="{r['elo']:.0f}" data-rank="{i+1}" onclick="wcShowTeamDetail({name_js},{r['elo']:.0f},{group_js},{r['champion_pct']:.1f},{r['final_pct']:.1f},{r['sf_pct']:.1f},{r['qf_pct']:.1f},{r['r16_pct']:.1f},{r['r32_pct']:.1f},{r['group_exit_pct']:.1f})" style="cursor:pointer;">
                <td>{i + 1}</td>
                <td><strong>{cn_name}</strong>{est_mark}</td>
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
"""

    html += """</div><!-- /.container -->
</div><!-- /#protected-content -->

<!-- ====== 球队详情弹窗 ====== -->
<div id="team-modal">
  <div id="team-modal-body">
    <button id="team-modal-close" onclick="document.getElementById('team-modal').classList.remove('open')">&#x2715;</button>
    <div id="team-modal-content"></div>
  </div>
</div>

<!-- ====== 竞猜弹窗 ====== -->
<div id="guess-modal">
  <div id="guess-modal-body">
    <button style="position:absolute;top:12px;right:14px;background:none;border:none;color:#8890b5;font-size:1.4em;cursor:pointer;" onclick="document.getElementById('guess-modal').classList.remove('open')">&#x2715;</button>
    <h3 style="color:#FFD700;margin-bottom:16px;">&#x1F3B2; 我的竞猜</h3>
    <div id="guess-content"></div>
  </div>
</div>

<!-- ====== 密码门 JS ====== -->
<script>
(function(){
  var PWD_HASH = '35d44a6de2bbd084ea8cd4fbd0dea51b9a675cf9';
  var PWD_VERSION = 'v2';
  var overlay = document.getElementById('pwd-overlay');
  var content = document.getElementById('protected-content');
  if (localStorage.getItem('wc_pwd') === '1' && localStorage.getItem('wc_pwd_ver') === PWD_VERSION) {
    overlay.style.display = 'none';
    content.style.display = '';
  }
  window.wcCheckPwd = function() {
    var input = document.getElementById('pwd-input').value.trim();
    var err = document.getElementById('pwd-err');
    if (!input) { err.style.display = ''; return; }
    crypto.subtle.digest('SHA-1', new TextEncoder().encode(input)).then(function(buf) {
      var hash = Array.from(new Uint8Array(buf)).map(function(b){ return ('0'+(b&0xFF).toString(16)).slice(-2); }).join('');
      if (hash === PWD_HASH) {
        err.style.display = 'none';
        localStorage.setItem('wc_pwd','1');
        localStorage.setItem('wc_pwd_ver', PWD_VERSION);
        overlay.style.display = 'none';
        content.style.display = '';
      } else {
        err.style.display = '';
        document.getElementById('pwd-input').value = '';
      }
    });
  };
  document.getElementById('pwd-input').addEventListener('keydown', function(e){ if (e.key === 'Enter') window.wcCheckPwd(); });
})();
</script>

<!-- ====== 动态时间 JS ====== -->
<script>
(function(){
  var el = document.querySelector('.header .meta span[data-utc]');
  if (!el) return;
  var utc = new Date(el.getAttribute('data-utc'));
  function update() {
    var diff = Math.floor((new Date() - utc) / 1000);
    var text;
    if (diff < 60) text = '刚刚';
    else if (diff < 3600) text = Math.floor(diff/60) + ' 分钟前';
    else if (diff < 86400) text = Math.floor(diff/3600) + ' 小时前';
    else text = Math.floor(diff/86400) + ' 天前';
    el.textContent = text + ' 北京时间';
  }
  update();
  setInterval(update, 60000);
})();
</script>

<!-- ====== 可搜索/排序表格 JS ====== -->
<script>
(function(){
  var sortCol = 3, sortAsc = false;

  window.wcFilterMatrix = function() {
    var q = (document.getElementById('matrix-search').value||'').toLowerCase();
    var g = document.getElementById('matrix-group-filter').value;
    var rows = document.querySelectorAll('#matrix-tbody tr');
    var shown = 0;
    rows.forEach(function(r){
      var name = (r.getAttribute('data-name')||'').toLowerCase();
      var en = (r.getAttribute('data-en')||'').toLowerCase();
      var grp = r.getAttribute('data-group')||'';
      var show = (!q || name.indexOf(q)>=0 || en.indexOf(q)>=0) && (!g || grp===g);
      r.style.display = show ? '' : 'none';
      if (show) shown++;
    });
    document.getElementById('matrix-count').textContent = shown + ' 支球队';
  };

  window.wcSortMatrix = function(col) {
    if (sortCol === col) sortAsc = !sortAsc;
    else { sortCol = col; sortAsc = col < 2; }
    var tbody = document.getElementById('matrix-tbody');
    var rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort(function(a, b){
      var va = getCellVal(a, col), vb = getCellVal(b, col);
      if (!isNaN(va) && !isNaN(vb)) return sortAsc ? va-vb : vb-va;
      return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
    });
    rows.forEach(function(r){ tbody.appendChild(r); });
    document.querySelectorAll('#matrix-table th').forEach(function(th, i){
      th.classList.remove('sort-asc','sort-desc');
      if (i===col) th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
    });
  };

  function getCellVal(row, col) {
    var cells = row.querySelectorAll('td');
    if (!cells[col]) return '';
    var t = cells[col].textContent.replace('%','').trim();
    return isNaN(t) ? t : parseFloat(t);
  }
})();
</script>

<!-- ====== 球队详情弹窗 JS ====== -->
<script>
window.wcShowTeamDetail = function(name, elo, group, champ, fin, sf, qf, r16, r32, out) {
  var cn_names = window._wcTeamCN || {};
  var cnName = cn_names[name] || name;
  var stages = [
    {label:'夺冠',pct:champ,col:'#FFD700'},
    {label:'决赛',pct:fin,col:'#FFA726'},
    {label:'四强',pct:sf,col:'#ef5350'},
    {label:'八强',pct:qf,col:'#ab47bc'},
    {label:'十六强',pct:r16,col:'#42a5f5'},
    {label:'三十二强',pct:r32,col:'#26c6da'},
    {label:'小组出局',pct:out,col:'#78909c'},
  ];
  var bars = stages.map(function(s){
    var w = Math.min(s.pct * 3, 100);
    return '<div style="margin-bottom:10px;">' +
      '<div style="display:flex;justify-content:space-between;font-size:0.84em;margin-bottom:3px;">' +
        '<span style="color:#c8cce8;">' + s.label + '</span>' +
        '<span style="font-weight:700;color:' + s.col + '">' + s.pct.toFixed(1) + '%</span>' +
      '</div>' +
      '<div style="height:10px;background:rgba(255,255,255,0.06);border-radius:5px;overflow:hidden;">' +
        '<div style="height:100%;width:' + w + '%;background:' + s.col + ';border-radius:5px;transition:width 0.5s;"></div>' +
      '</div></div>';
  }).join('');

  var guess = JSON.parse(localStorage.getItem('wc_champ_guess')||'{}');
  var isGuessed = guess.team === name;
  var safeName = name.replace(/'/g, "\\'");
  var safeCnName = cnName.replace(/'/g, "\\'");
  var guessBtn = '<button onclick="wcGuessChamp(\'' + safeName + '\',\'' + safeCnName + '\')" style="width:100%;margin-top:14px;padding:10px;border-radius:8px;border:none;background:' +
    (isGuessed ? 'rgba(102,187,106,0.2);color:#66bb6a;border:1px solid #66bb6a' : 'rgba(255,215,0,0.15);color:#FFD700;border:1px solid rgba(255,215,0,0.4)') +
    ';font-size:0.9em;font-weight:600;cursor:pointer;">' +
    (isGuessed ? '✅ 已竞猜 ' + cnName + ' 夺冠' : '🎯 竞猜 ' + cnName + ' 夺冠') + '</button>';

  document.getElementById('team-modal-content').innerHTML =
    '<div style="text-align:center;margin-bottom:18px;">' +
      '<div style="font-size:2em;font-weight:900;color:#FFD700;">' + cnName + '</div>' +
      '<div style="color:#8890b5;font-size:0.84em;margin-top:4px;">' + group + ' 组 · ELO ' + elo + '</div>' +
    '</div>' + bars + guessBtn;
  document.getElementById('team-modal').classList.add('open');
};

window.wcGuessChamp = function(name, cnName) {
  localStorage.setItem('wc_champ_guess', JSON.stringify({team:name,cnName:cnName,time:Date.now()}));
  document.getElementById('team-modal').classList.remove('open');
  wcOpenGuess();
};
</script>

<!-- ====== 我的竞猜 JS ====== -->
<script>
window.wcOpenGuess = function() {
  var champ = JSON.parse(localStorage.getItem('wc_champ_guess')||'null');
  var html = '';

  if (champ) {
    var t = new Date(champ.time);
    html += '<div style="background:rgba(255,215,0,0.08);border:1px solid rgba(255,215,0,0.3);border-radius:10px;padding:14px;margin-bottom:16px;">' +
      '<div style="font-size:0.8em;color:#8890b5;margin-bottom:6px;">&#x1F3C6; 我的夺冠预测</div>' +
      '<div style="font-size:1.4em;font-weight:800;color:#FFD700;">' + champ.cnName + '</div>' +
      '<div style="font-size:0.76em;color:#8890b5;margin-top:4px;">下注于 ' + t.toLocaleString('zh-CN') + '</div>' +
      '<button onclick="localStorage.removeItem(&quot;wc_champ_guess&quot;);wcOpenGuess();" style="margin-top:10px;padding:6px 12px;border-radius:6px;border:1px solid rgba(255,255,255,0.15);background:none;color:#8890b5;font-size:0.78em;cursor:pointer;">取消竞猜</button>' +
    '</div>';
  } else {
    html += '<div style="color:#8890b5;font-size:0.88em;margin-bottom:14px;padding:12px;background:rgba(255,255,255,0.03);border-radius:8px;">' +
      '点击下方表格中的任意球队行，即可竞猜该球队夺冠。' +
    '</div>';
  }

  // 场次竞猜
  var matchGuesses = JSON.parse(localStorage.getItem('wc_match_guesses')||'{}');
  var guessCount = Object.keys(matchGuesses).length;
  var correctCount = 0;
  var settledCount = 0;

  if (guessCount > 0) {
    html += '<div style="font-size:0.88em;color:#8890b5;margin-bottom:8px;">&#x26BD; 比赛竞猜记录（' + guessCount + ' 场）</div>';
    html += '<div style="max-height:300px;overflow-y:auto;">';
    Object.values(matchGuesses).forEach(function(g){
      var icon = '⏳', color = '#8890b5';
      if (g.result) {
        settledCount++;
        if (g.guess === g.result) { icon='✅'; color='#66bb6a'; correctCount++; }
        else { icon='❌'; color='#ef5350'; }
      }
      html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 10px;margin-bottom:4px;background:rgba(255,255,255,0.03);border-radius:6px;">' +
        '<span style="font-size:0.85em;">' + (g.homeCN||g.home) + ' vs ' + (g.awayCN||g.away) + '</span>' +
        '<span style="font-size:0.8em;color:' + color + ';">' + icon + ' ' + wcGuessLabel(g.guess) + '</span>' +
      '</div>';
    });
    html += '</div>';
    if (settledCount > 0) {
      var rate = (correctCount/settledCount*100).toFixed(0);
      html += '<div style="text-align:center;margin-top:12px;padding:10px;background:rgba(79,195,247,0.08);border-radius:8px;">' +
        '已结算 ' + settledCount + ' 场 · 猜中 <span style="color:#66bb6a;font-weight:700;">' + correctCount + '</span> 场 · 准确率 <span style="color:#FFD700;font-weight:800;">' + rate + '%</span>' +
      '</div>';
    }
    html += '<button onclick="if(confirm(&quot;确定清空所有竞猜记录？&quot;)){localStorage.removeItem(&quot;wc_match_guesses&quot;);wcOpenGuess();}" style="margin-top:10px;width:100%;padding:8px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:none;color:#8890b5;font-size:0.78em;cursor:pointer;">清空比赛竞猜记录</button>';
  } else {
    html += '<div style="color:#8890b5;font-size:0.82em;text-align:center;padding:12px;">在今日比赛模块中点击比赛卡片可进行竞猜</div>';
  }

  document.getElementById('guess-content').innerHTML = html;
  document.getElementById('guess-modal').classList.add('open');
};

window.wcGuessLabel = function(g) {
  return g==='home'?'主队胜':g==='draw'?'平局':'客队胜';
};

window.wcGuessMatch = function(home, homeCN, away, awayCN, guess) {
  var key = home + '_' + away;
  var all = JSON.parse(localStorage.getItem('wc_match_guesses')||'{}');
  all[key] = {home:home, away:away, homeCN:homeCN, awayCN:awayCN, guess:guess, time:Date.now()};
  localStorage.setItem('wc_match_guesses', JSON.stringify(all));
  alert('✅ 已记录：' + homeCN + ' vs ' + awayCN + ' — ' + wcGuessLabel(guess));
};

window._wcTeamCN = {};
</script>

<!-- ====== 分享卡片 JS ====== -->
<script>
window.wcShareCard = function() {
  var topTeams = [];
  var rows = document.querySelectorAll('#matrix-tbody tr');
  var shown = 0;
  rows.forEach(function(r){
    if (shown >= 5) return;
    if (r.style.display === 'none') return;
    var cells = r.querySelectorAll('td');
    if (cells.length < 5) return;
    topTeams.push({
      rank: cells[0].textContent,
      name: cells[1].textContent.replace('⚠','').trim(),
      group: cells[2].textContent,
      pct: cells[4].textContent
    });
    shown++;
  });

  var now = new Date().toLocaleDateString('zh-CN');
  var html = '<div style="background:linear-gradient(135deg,#0a0e27,#1a237e);padding:20px;border-radius:12px;font-family:-apple-system,sans-serif;max-width:320px;">' +
    '<div style="text-align:center;margin-bottom:14px;">' +
      '<div style="font-size:1.5em;font-weight:900;background:linear-gradient(90deg,#FFD700,#FFA726);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">⚽ 2026 世界杯夺冠预测</div>' +
      '<div style="color:#8890b5;font-size:0.72em;margin-top:4px;">' + now + ' · 蒙特卡洛模拟</div>' +
    '</div>';

  topTeams.forEach(function(t){
    var icons = ['🥇','🥈','🥉','4️⃣','5️⃣'];
    var idx = parseInt(t.rank)-1;
    html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 12px;margin-bottom:6px;background:rgba(255,255,255,0.06);border-radius:8px;">' +
      '<span style="font-size:1.1em;">' + (icons[idx]||t.rank) + '</span>' +
      '<span style="font-weight:700;color:#e8e8ec;flex:1;margin:0 10px;">' + t.name + '</span>' +
      '<span style="font-weight:800;color:#FFD700;">' + t.pct + '</span>' +
    '</div>';
  });

  html += '<div style="text-align:center;margin-top:12px;color:#8890b5;font-size:0.7em;">haiwangxing1251.github.io/worldcup-dashboard</div></div>';

  var win = window.open('', '_blank', 'width=400,height=480');
  if (!win) { alert('请允许弹窗以查看分享卡片'); return; }
  win.document.write('<!DOCTYPE html><html><head><meta charset="UTF-8"><title>分享</title></head><body style="margin:0;background:#0a0e27;display:flex;align-items:center;justify-content:center;min-height:100vh;">' + html + '<p style="text-align:center;color:#8890b5;font-size:12px;margin-top:10px;">长按图片保存</p></body></html>');
  win.document.close();
};
</script>

<!-- ====== 比赛日推送提醒 JS ====== -->
<script>
(function(){
  var btn = document.getElementById('notify-btn');
  if (!btn) return;

  function updateBtn() {
    var on = localStorage.getItem('wc_notify') === '1';
    btn.className = 'active' ? (on ? 'active' : '') : '';
    if (on) {
      btn.className = 'active';
      btn.innerHTML = '🔔 提醒已开启';
    } else {
      btn.className = '';
      btn.innerHTML = '🔔 开启比赛提醒';
    }
  }

  btn.addEventListener('click', function(){
    var on = localStorage.getItem('wc_notify') === '1';
    if (on) {
      localStorage.removeItem('wc_notify');
      updateBtn();
      return;
    }
    if (!('Notification' in window)) {
      alert('您的浏览器不支持桌面通知');
      return;
    }
    Notification.requestPermission().then(function(p){
      if (p === 'granted') {
        localStorage.setItem('wc_notify', '1');
        updateBtn();
        new Notification('⚽ 世界杯预测', {
          body: '提醒已开启！比赛前 30 分钟将收到通知',
          icon: 'https://haiwangxing1251.github.io/worldcup-dashboard/favicon.ico'
        });
        scheduleNotifications();
      } else {
        alert('请在浏览器设置中允许通知权限');
      }
    });
  });

  function scheduleNotifications() {
    if (!window.TODAY_SCHEDULE) return;
    var now = Date.now();
    TODAY_SCHEDULE.forEach(function(m){
      if (m.finished || !m.date || !m.time) return;
      try {
        var mt = new Date(m.date + 'T' + m.time + ':00+08:00').getTime();
        var remind = mt - 30*60*1000;
        var delay = remind - now;
        if (delay > 0 && delay < 24*60*60*1000) {
          setTimeout(function(){
            if (localStorage.getItem('wc_notify') !== '1') return;
            new Notification('⚽ 比赛即将开始', {
              body: (m.home||'') + ' vs ' + (m.away||'') + ' · 30分钟后开球',
              icon: 'https://haiwangxing1251.github.io/worldcup-dashboard/favicon.ico'
            });
          }, delay);
        }
      } catch(e){}
    });
  }

  updateBtn();
  if (localStorage.getItem('wc_notify') === '1') {
    Notification.requestPermission().then(function(p){
      if (p === 'granted') scheduleNotifications();
    });
  }
})();
</script>

</body>
</html>"""

    return html


def save_report(html_content: str, output_path: str):
    """保存 HTML 报告到文件。"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"中文报告已保存至：{output_path}")
