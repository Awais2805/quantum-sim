#!/usr/bin/env python3
"""Plot bench.csv against n: one figure per plot type, one panel per circuit, one line per config.

  speedup  unfused sim time / config sim time
  sim      raw simulation time (s, log scale)
  fuse     fusion-pass (transpilation) time (s, log scale; 'none' left out)
  total    fusion pass + simulation (s, log scale)
  ops      gates applied: 'none' = before fusion, the others = after

  python graph.py                                   # all plots, median of reps
  python graph.py --plots sim fuse --stat min       # only these, fastest rep
  python graph.py results/ar-mbp/bench.csv --configs none aer dp
Writes bench_<plot>.png next to the csv.
"""
import argparse
import csv
import socket
from pathlib import Path

import matplotlib.pyplot as plt

PLOTS = {  # name -> (y label, log y?)
    "speedup": ("speedup vs unfused", False),
    "sim": ("simulation time (s)", True),
    "fuse": ("fusion-pass time (s)", True),
    "total": ("fusion pass + simulation (s)", True),
    "ops": ("gates applied (none = before fusion)", False),
}
COLORS = {"none": "tab:gray", "aer": "tab:orange", "dp": "tab:green", "diag8+dp": "tab:purple"}
STATS = {"min": "sim_min_s", "med": "sim_med_s", "mean": "sim_mean_s"}
STAT_LABEL = {"min": "fastest rep", "med": "median of reps", "mean": "mean of reps"}


def value(plot, r, base, col):
    sim = float(r[col])
    if plot == "speedup":
        return float(base[r["n"]][col]) / sim
    if plot == "sim":
        return sim
    if plot == "fuse":
        return float(r["fuse_s"])
    if plot == "ops":
        return int(r["ops"])
    return float(r["fuse_s"]) + sim


def graph(csv_path, plot, stat, configs=None):
    rows = list(csv.DictReader(open(csv_path)))
    if configs:
        rows = [r for r in rows if r["config"] in configs or r["config"] == "none"]
    col = STATS[stat]
    kinds = list(dict.fromkeys(r["circuit"] for r in rows))
    ylabel, logy = PLOTS[plot]
    fig, axes = plt.subplots(1, len(kinds), figsize=(5 * len(kinds), 4), squeeze=False)
    for ax, kind in zip(axes[0], kinds):
        rs = [r for r in rows if r["circuit"] == kind]
        base = {r["n"]: r for r in rs if r["config"] == "none"}
        for cfg in dict.fromkeys(r["config"] for r in rs):
            if (cfg == "none" and plot == "fuse") or (configs and cfg not in configs):
                continue
            pts = sorted((int(r["n"]), value(plot, r, base, col)) for r in rs if r["config"] == cfg)
            ax.plot(*zip(*pts), marker="o", label=cfg, color=COLORS.get(cfg))
        if plot == "speedup":
            ax.axhline(1, color="grey", lw=0.8, ls="--")
        if logy:
            ax.set_yscale("log")
        label = ylabel if plot in ("fuse", "ops") else f"{ylabel}, {STAT_LABEL[stat]}"
        ax.set(title=kind, xlabel="qubits (n)", ylabel=label, xticks=sorted(map(int, base)))
        ax.legend(fontsize="small")
    fig.tight_layout()
    out = Path(csv_path).with_name(f"{Path(csv_path).stem}_{plot}.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", default=here / "results" / socket.gethostname() / "bench.csv")
    ap.add_argument("--plots", nargs="+", choices=list(PLOTS), default=list(PLOTS))
    ap.add_argument("--stat", choices=list(STATS), default="med", help="which sim time per config")
    ap.add_argument("--configs", nargs="+", help="only these configs (default: all in the csv)")
    a = ap.parse_args()
    for plot in a.plots:
        graph(a.csv, plot, a.stat, a.configs)


if __name__ == "__main__":
    main()
