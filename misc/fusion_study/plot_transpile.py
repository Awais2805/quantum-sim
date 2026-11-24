"""Plot fusion-pass time vs qubit count from transpile_time.py output (no simulation involved).

    ../.venv/bin/python plot_transpile.py results/transpile_ar-mbp

Writes <dir>/fusion_time.png. Same colours as plot_meeting.py: blue = horizontal, orange = vertical,
green = measured-cost fusion; dashed = cost model (the hatched bars in the meeting plots).
Lines are k = 2 (the width used in the 26-qubit meeting run).
"""
import argparse
import csv
import re
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from plot_meeting import COLOR, GRID, INK, INK2, SURFACE  # noqa: E402

CIRCUITS = {"qft": "QFT", "rqc": "Random circuit"}
LINES = [  # (method, k, colour key, dashed, legend label)
    ("horizontal, greedy", 2, "horizontal", False, "horizontal, greedy (k = 2)"),
    ("horizontal, cost model", 2, "horizontal", True, "horizontal, cost model (k = 2)"),
    ("vertical, greedy", 2, "vertical", False, "vertical, greedy (k = 2)"),
    ("vertical, cost model", 2, "vertical", True, "vertical, cost model (k = 2)"),
    ("measured-cost fusion", 0, "dp:measured", False, "measured-cost fusion"),
]


def load(d):
    """(circuit, method, k) -> {n: mean over seeds of the fastest repeat}; also gates per (circuit, n)."""
    acc, gates = defaultdict(lambda: defaultdict(list)), defaultdict(list)
    for r in csv.DictReader(open(d / "transpile_times.csv")):
        if r["error"] or not r["fuse_min_s"]:
            continue
        n = int(r["n"])
        acc[(r["circuit"], r["method"], int(r["k"]))][n].append(float(r["fuse_min_s"]))
        if r["method"] == "measured-cost fusion":
            gates[(r["circuit"], n)].append(int(r["gates_in"]))
    mean = {key: {n: statistics.fmean(v) for n, v in by_n.items()} for key, by_n in acc.items()}
    return mean, {key: statistics.fmean(v) for key, v in gates.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dir", type=Path)
    a = p.parse_args()
    data, gates = load(a.dir)
    md = (a.dir / "TRANSPILE.md").read_text() if (a.dir / "TRANSPILE.md").exists() else ""
    m = re.search(r"Machine: `([^`]*)` \((.*)\), single", md)
    machine = f"{m.group(1)} ({re.sub(r'Intel\(R\) Core\(TM\) |\(R\)|\(TM\)|CPU ', '', m.group(2))})" if m else "?"

    plt.rcParams.update({"font.size": 11, "text.color": INK, "axes.labelcolor": INK2,
                         "xtick.color": INK2, "ytick.color": INK2})
    circuits = [c for c in CIRCUITS if any(k[0] == c for k in data)]
    fig, axes = plt.subplots(1, len(circuits), figsize=(6.4 * len(circuits), 6.2), facecolor=SURFACE,
                             sharey=True, squeeze=False)
    ymax = max(v for by_n in data.values() for v in by_n.values())
    for ax, c in zip(axes[0], circuits):
        ns = sorted({n for (cc, _, _), by_n in data.items() if cc == c for n in by_n})
        for method, k, col, dashed, label in LINES:
            by_n = data.get((c, method, k))
            if not by_n:
                continue
            xs = [n for n in ns if n in by_n]
            ax.plot(xs, [by_n[n] for n in xs], color=COLOR[col], linewidth=2,
                    linestyle=(0, (4, 2)) if dashed else "-", marker="o", markersize=5,
                    markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=3, label=label)
        ax.axhline(1.0, color=INK2, linewidth=1, linestyle=":", zorder=2)
        ax.text(ns[0], 1.0, "1 second", va="bottom", fontsize=9.5, color=INK2)
        ax.set_xticks(ns, [f"{n}\n{gates.get((c, n), 0):,.0f}" for n in ns])
        ax.set_xlabel("qubits\n(gates in circuit" + (", mean of 3 random seeds)" if c == "rqc" else ")"))
        ax.set_ylim(0, max(1.1, ymax * 1.15))
        ax.set_title(CIRCUITS[c], fontsize=12, pad=8, color=INK)
        ax.set_facecolor(SURFACE)
        ax.grid(True, axis="y", color=GRID, linewidth=1, zorder=0)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
    axes[0][0].set_ylabel("Fusion pass time (s)")
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 0.935),
               labelcolor=INK, fontsize=10)
    fig.suptitle("Fusion transpilation time", y=1.0, fontsize=14, color=INK)
    fig.text(0.5, 0.945, "no simulation, just fusion · run on my own laptop", ha="center", fontsize=10,
             color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.85))
    out = a.dir / "fusion_time.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
