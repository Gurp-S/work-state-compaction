# -*- coding: utf-8 -*-
"""Score-vs-cost scatter (SVG, no dependencies) with the Pareto frontier marked.

    python -m bench22.plot --lb leaderboard-sealed.json --out charts/
"""
import argparse, json, math, os

COLORS = ["#2f6fdb", "#e0663a", "#2e9d6a", "#8a5ad6", "#c9a227", "#6b7280", "#d94f8a"]


def frontier(points):
    """Pareto-optimal points: no other point has higher-or-equal A and lower-or-equal C (strictly better in one)."""
    out = []
    for n, c, a in points:
        if not any((c2 <= c and a2 >= a) and (c2 < c or a2 > a) for n2, c2, a2 in points if n2 != n):
            out.append((n, c, a))
    return sorted(out, key=lambda p: p[1])


def svg_for(title, rows, ref_c):
    W, H, L, R, T, B = 760, 460, 70, 30, 50, 60
    cs = [max(c, ref_c / 4) for _, c, _ in rows]
    lo, hi = math.log2(min(cs)) - 0.3, math.log2(max(cs)) + 0.3
    alo = max(0, min(a for _, _, a in rows) - 5)
    ahi = min(100, max(a for _, _, a in rows) + 5)
    X = lambda c: L + (math.log2(max(c, ref_c / 4)) - lo) / (hi - lo) * (W - L - R)
    Y = lambda a: T + (1 - (a - alo) / (ahi - alo)) * (H - T - B)
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="sans-serif" font-size="12">',
         f'<rect width="{W}" height="{H}" fill="white"/>', f'<text x="{L}" y="26" font-size="15" font-weight="bold">{title}</text>']
    for k in range(5):                                           # y grid
        a = alo + (ahi - alo) * k / 4
        s.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(a):.1f}" y2="{Y(a):.1f}" stroke="#e5e7eb"/><text x="{L - 8}" y="{Y(a) + 4:.1f}" text-anchor="end">{a:.0f}</text>')
    t = math.ceil(lo)
    while t <= hi:                                               # x grid (powers of two)
        c = 2 ** t
        s.append(f'<line x1="{X(c):.1f}" x2="{X(c):.1f}" y1="{T}" y2="{H - B}" stroke="#f3f4f6"/><text x="{X(c):.1f}" y="{H - B + 16}" text-anchor="middle">¥{c:.3g}</text>')
        t += 1
    s.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 14}" text-anchor="middle">成本 C（人民币，对数刻度，每格翻一倍）→</text>')
    s.append(f'<text x="16" y="{(T + H - B) / 2:.0f}" transform="rotate(-90 16 {(T + H - B) / 2:.0f})" text-anchor="middle">成绩 A（日常分与长期分的平均，%）</text>')
    fr = frontier(rows)
    if len(fr) > 1:
        s.append('<polyline fill="none" stroke="#111827" stroke-width="1.5" stroke-dasharray="5 4" points="' + " ".join(f"{X(c):.1f},{Y(a):.1f}" for _, c, a in fr) + '"/>')
    for i, (n, c, a) in enumerate(rows):
        col = COLORS[i % len(COLORS)]
        s.append(f'<circle cx="{X(c):.1f}" cy="{Y(a):.1f}" r="6" fill="{col}"' + (' stroke="#111827" stroke-width="2"' if (n, c, a) in fr else '') + '/>')
        s.append(f'<text x="{X(c) + 9:.1f}" y="{Y(a) + 4:.1f}">{n}</text>')
    s.append(f'<text x="{W - R}" y="{T - 8}" text-anchor="end" fill="#374151">虚线 = 帕累托前沿（黑圈）</text></svg>')
    return "\n".join(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lb", required=True, help="leaderboard-<split>.json written by report.py (the public view, without private systems)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    lb = json.load(open(a.lb, encoding="utf-8"))
    for persona, b in lb["boards"].items():
        rows = [(n, m["C"], m["A"]) for n, m in b["systems"].items()]
        if len(rows) < 2:
            continue
        ref = b.get("C_ref") or min(c for _, c, _ in rows) * 4    # without a reference row the x axis floor is set from the cheapest system
        fn = os.path.join(a.out, f"scatter-{persona}.svg")
        open(fn, "w", encoding="utf-8").write(svg_for(f"{b['board']}（{lb['split']}）", rows, ref))
        print("wrote", fn)
    nat = lb.get("natural") or {}
    if len(nat) > 1:
        rows = [(n, m["C"], m["A"]) for n, m in nat.items()]
        ref = (nat.get(lb.get("reference_system", "qwen-base")) or {}).get("C") or min(c for _, c, _ in rows) * 4
        fn = os.path.join(a.out, "scatter-natural.svg")
        open(fn, "w", encoding="utf-8").write(svg_for(f"自然用记忆榜（{lb['split']}）", rows, ref))
        print("wrote", fn)


if __name__ == "__main__":
    main()
