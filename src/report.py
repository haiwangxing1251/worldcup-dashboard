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
</style>
</head>
<body>

<script>
// ====== 密码门 ======
(function(){{
  var PWD_HASH = '7c4a8d09ca3762af61e59520943dc26494f8941b';
  var PWD_VERSION = 'v1';
  var overlay = document.getElementById('pwd-overlay');
  var content = document.getElementById('protected-content');
  if (localStorage.getItem('wc_pwd') === '1' && localStorage.getItem('wc_pwd_ver') === PWD_VERSION) {{
    overlay.style.display = 'none';
    content.style.display = '';
  }}
  window.wcCheckPwd = function() {{
    var input = document.getElementById('pwd-input').value.trim();
    var err = document.getElementById('pwd-err');
    if (!input) {{ err.style.display = ''; return; }}
    crypto.subtle.digest('SHA-1', new TextEncoder().encode(input)).then(function(buf) {{
      var hash = Array.from(new Uint8Array(buf)).map(function(b){{ return ('0'+(b&0xFF).toString(16)).slice(-2); }}).join('');
      if (hash === PWD_HASH) {{
        err.style.display = 'none';
        localStorage.setItem('wc_pwd','1');
        localStorage.setItem('wc_pwd_ver', PWD_VERSION);
        overlay.style.display = 'none';
        content.style.display = '';
      }} else {{
        err.style.display = '';
        document.getElementById('pwd-input').value = '';
      }}
    }});
  }} }};
  document.getElementById('pwd-input').addEventListener('keydown', function(e){{ if (e.key === 'Enter') window.wcCheckPwd(); }});
}})();
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
