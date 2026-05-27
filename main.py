#!/usr/bin/env python3
"""
2026 年 FIFA 世界杯预测系统
=====================================
基于 ELO 评分 + 泊松分布的蒙特卡洛模拟。

用法:
    python main.py [--sims N] [--seed S] [--output OUTPUT]
    python main.py --sync          # 运行前从网络同步最新数据
    python main.py --live [--port 8888]  # 启动实时仪表盘服务器

输出:
    output/prediction_report.html — 中文可视化报告

作者: WorkBuddy AI
数据来源: FIFA, worldfootballrankings.com, roadtowc.com
"""

import os
import sys
import time
import argparse

# 强制 UTF-8 输出，避免 Windows 终端 GBK 编码报错
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 添加 src 到搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from simulator import WorldCupSimulator, default_progress
from report import generate_html_report, save_report, cn, gcn
from data_fetcher import sync_all, fetch_match_results


def main():
    parser = argparse.ArgumentParser(
        description='2026 世界杯预测 — 蒙特卡洛模拟')
    parser.add_argument('--sims', type=int, default=10000,
                        help='模拟次数（默认 10000）')
    parser.add_argument('--seed', type=int, default=42,
                        help='随机种子，确保可复现（默认 42）')
    parser.add_argument('--output', type=str, default=None,
                        help='输出 HTML 路径（默认 output/prediction_report.html）')
    parser.add_argument('--groups', type=str, default=None,
                        help='分组数据 JSON 路径')
    parser.add_argument('--elo', type=str, default=None,
                        help='ELO 评分 JSON 路径')
    parser.add_argument('--sync', action='store_true',
                        help='运行前从网络同步最新 ELO 数据和赛果')
    parser.add_argument('--live', action='store_true',
                        help='启动实时仪表盘服务器（Web 界面）')
    parser.add_argument('--port', type=int, default=8888,
                        help='仪表盘端口（默认 8888，仅与 --live 联用）')
    args = parser.parse_args()

    # 文件路径
    base_dir = os.path.dirname(os.path.abspath(__file__))
    groups_file = args.groups or os.path.join(base_dir, 'data', 'groups.json')
    elo_file = args.elo or os.path.join(base_dir, 'data', 'elo_ratings.json')
    output_path = args.output or os.path.join(base_dir, 'output', 'prediction_report.html')

    # 校验输入文件
    for path, name in [(groups_file, 'groups.json'), (elo_file, 'elo_ratings.json')]:
        if not os.path.exists(path):
            print(f"❌ 错误：找不到 {name}，路径 {path}")
            sys.exit(1)

    # ========== --live 模式：启动实时仪表盘 ==========
    if args.live:
        from live_server import start_server
        print("=" * 62)
        print("  2026 世界杯实时仪表盘模式")
        print(f"  端口：{args.port}")
        print("=" * 62)
        start_server(args.port, args.sims, args.seed)
        return  # 不会执行到这里（server 阻塞）

    # ========== --sync 模式：同步最新数据 ==========
    sync_result = None
    completed_matches = []
    if args.sync:
        print("\n📡 正在从网络同步最新数据……")
        sync_result = sync_all(elo_file, groups_file)
        if sync_result['elo_updated']:
            print(f"  ✅ ELO 数据已刷新（{sync_result['elo_from_web']} 队来自网络）")
        else:
            print("  ⚠️  使用本地缓存数据")
        if sync_result['matches_found'] > 0:
            print(f"  ✅ 获取到 {sync_result['matches_found']} 场真实赛果")
            completed_matches = fetch_match_results()
        print()

    print("=" * 62)
    print("  2026 年 FIFA 世界杯预测系统")
    print("  模型：ELO 评分 → 泊松分布")
    print(f"  模拟次数：{args.sims:,}  |  随机种子：{args.seed}")
    if sync_result and sync_result.get('matches_found', 0) > 0:
        print(f"  已融入 {sync_result['matches_found']} 场真实赛果")
    print("=" * 62)
    print()

    # 初始化模拟器（如有同步到的真实赛果则传入）
    sim = WorldCupSimulator(
        groups_file=groups_file,
        elo_file=elo_file,
        num_sims=args.sims,
        seed=args.seed,
        completed_matches=completed_matches
    )

    # 运行模拟
    print(f"正在运行 {args.sims:,} 次蒙特卡洛模拟……")
    print(f"  每次模拟 = 72 场小组赛 + 32 场淘汰赛 = 104 场")
    print()

    start_time = time.time()
    stats = sim.run(progress_callback=default_progress)
    elapsed = time.time() - start_time
    print(f"\n\n✅ 模拟完成，耗时 {elapsed:.1f} 秒 "
          f"（{elapsed / args.sims * 1000:.1f} 毫秒/次）")
    print()

    # 获取排名结果
    results = sim.get_ranked_results()
    difficulties = sim.get_group_difficulty()

    # ---- 终端输出 Top 10 ----
    print("═" * 62)
    print("  夺冠概率 — 前 10 名")
    print("═" * 62)
    for i, r in enumerate(results[:10]):
        est = " [估算]" if r['elo_estimated'] else ""
        bar = "█" * int(r['champion_pct'] * 2)
        print(f"  {i+1:2d}. {cn(r['name']):<14s} {bar} {r['champion_pct']:5.1f}%  "
              f"(ELO: {r['elo']:.0f}{est})")

    print()
    print("═" * 62)
    print("  死亡之组（平均 ELO 最高）")
    print("═" * 62)
    for d in difficulties[:5]:
        tag = " ☠ 死亡之组" if d['avg_elo'] > 1620 else ""
        print(f"  {gcn(d['group'])}：平均 ELO {d['avg_elo']:.0f}{tag}")
        print(f"    {' · '.join(cn(t) for t in d['teams'])}")
    print()

    # 生成 HTML 报告
    print("正在生成中文 HTML 报告……")
    sync_info = None
    if args.sync:
        sync_info = {
            'matches_found': len(completed_matches),
            'elo_updated': os.path.getmtime(elo_file)
        }
    html_content = generate_html_report(
        results=results,
        difficulties=difficulties,
        stats=stats,
        num_sims=args.sims,
        elo_source_date="实时同步" if args.sync else "2026-05-27",
        sync_info=sync_info
    )
    save_report(html_content, output_path)
    print()
    print(f"📄 报告路径：{output_path}")
    print(f"   在浏览器中打开即可查看完整预测报告。")
    print()

    # 冠军预测
    champion = results[0]
    runner_up = results[1] if len(results) > 1 else None
    print(f"🏆 预测冠军：{cn(champion['name'])}（夺冠概率 {champion['champion_pct']:.1f}%）")
    if runner_up:
        print(f"🥈 亚军热门：{cn(runner_up['name'])}（夺冠概率 {runner_up['champion_pct']:.1f}%）")
    print()


if __name__ == '__main__':
    main()
