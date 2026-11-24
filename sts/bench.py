#!/usr/bin/env python3
"""Time fusion configs on QuEST. For each (circuit, n) one base circuit is built and every
config below fuses that same object; the fusion pass is timed separately from simulation.

  none       stock QuEST, unfused
  aer        Aer's own fusion plan (fusion.fuse with Aer's hard-coded costs)
  dp         our method: Aer's algorithm, decisions priced with the measured cost table
  diag8+dp   optional (--configs): exactly-diagonal gates merged into diagonal blocks of
             <= 8 qubits with no cost check, then dp. Experimental, not part of the method.

Cost table: one per n by default. Every gate kind is measured on QuEST here at the same n as the
benchmark (costs.calibrate), cached as results/<host>/cost_table_quest_t<threads>_n<n>.json, so
each n is priced with its own table (cache vs memory regime, memory pressure). --n-cal N or
--table FILE force one table for every n instead; rows whose n differs from the table's n are
flagged (table_n column in bench.csv, "†" in RESULTS.md).

Timing: quest_runner, all configs round-robin with a rotating start, gate loop only, best of
--reps (mean also saved). Writes results/<host>/bench.csv and RESULTS.md. Run verify.py first.

  python bench.py --circuits qft rqc --ns 18 20 22 --threads 4
"""
import argparse
import csv
import os
import re
import socket
import tempfile
import time
from pathlib import Path

import circuits
import costs
from fusion import diagonal_blocks, fuse
from qops import parse_times, run_runner, write_qops

HERE = Path(__file__).resolve().parent
MAX_W = costs.MAX_DENSE_W


MAKERS = {  # config -> (base circuit, cost table) -> fused circuit
    "none": lambda base, table: base,
    "aer": lambda base, table: fuse(base, "aer", "diag+dp", MAX_W),
    "dp": lambda base, table: fuse(base, table, "dp", MAX_W),
    "diag8+dp": lambda base, table: fuse(diagonal_blocks(base, 8), table, "dp", MAX_W),
}
DEFAULT_CONFIGS = ["none", "aer", "dp"]


def variants(base, table, configs=DEFAULT_CONFIGS):
    """config -> (fused circuit, fusion-pass seconds), all from the same base circuit."""
    out = {}
    for name in configs:
        t0 = time.perf_counter()
        qc = MAKERS[name](base, table)
        out[name] = (qc, time.perf_counter() - t0)
    return out


def time_quest(circs, env, reps):
    with tempfile.TemporaryDirectory(prefix="bench_") as td:
        plans = []
        for i, qc in enumerate(circs):
            plans.append(Path(td) / f"{i}.qops")
            write_qops(qc, plans[-1])
        return parse_times(run_runner(["--reps", reps, "--warmup", 1, *plans], env), len(plans))


def mem_available():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    return float("inf")


def fmt_t(s):
    return f"{s * 1e3:.1f} ms" if s < 1 else f"{s:.2f} s"


def markdown(rows, meta):
    lines = ["# Fusion on QuEST", "", meta, "",
             "Cell: best simulation time · speedup vs unfused · ops applied · fusion-pass time. "
             "**Bold** = fastest. † = cost table measured at a different n than this column.", ""]
    for kind in dict.fromkeys(r["circuit"] for r in rows):
        rs = [r for r in rows if r["circuit"] == kind]
        ns = list(dict.fromkeys(r["n"] for r in rs))
        t = {(r["config"], r["n"]): r for r in rs}
        best = {n: min((r for r in rs if r["n"] == n), key=lambda r: r["sim_min_s"])["config"] for n in ns}
        flag = lambda n: "" if str(t[("none", n)]["table_n"]) == str(n) else " †"
        lines += [f"## {kind}", "",
                  "| config | " + " | ".join(f"n={n}{flag(n)} ({t[('none', n)]['fingerprint']})" for n in ns) + " |",
                  "|---|" + "---|" * len(ns)]
        for cfg in dict.fromkeys(r["config"] for r in rs):
            cells = []
            for n in ns:
                r = t[(cfg, n)]
                txt = (f"{fmt_t(r['sim_min_s'])} · {t[('none', n)]['sim_min_s'] / r['sim_min_s']:.2f}× · "
                       f"{r['ops']} ops · {r['fuse_s'] * 1e3:.0f} ms")
                cells.append(f"**{txt}**" if best[n] == cfg else txt)
            lines.append(f"| {cfg} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--circuits", nargs="+", default=list(circuits.KINDS))
    ap.add_argument("--ns", nargs="+", type=int, default=[18, 20, 22])
    ap.add_argument("--seed", type=int, default=1234, help="rqc seed; size n uses seed+n")
    ap.add_argument("--same-seed", action="store_true", help="rqc uses --seed at every n (not seed+n)")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--threads", type=int, default=os.cpu_count())
    ap.add_argument("--table", help="one cost table JSON for every n (rows at other n are flagged)")
    ap.add_argument("--n-cal", type=int, help="one table measured at this n for every n "
                    "(default: a table per benchmark n)")
    ap.add_argument("--configs", nargs="+", choices=list(MAKERS), default=DEFAULT_CONFIGS,
                    help="must include none (the speedup baseline)")
    ap.add_argument("--out-dir", type=Path, default=HERE / "results" / socket.gethostname())
    a = ap.parse_args()
    if "none" not in a.configs:
        ap.error("--configs must include none (the speedup baseline)")

    a.out_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "OMP_NUM_THREADS": str(a.threads), "OMP_PROC_BIND": "close"}
    tables = {}

    def table_for(n):
        """(table, n it was measured at or None if unknown, source) for benchmark size n."""
        if a.table:
            m = re.search(r"_n(\d+)", Path(a.table).stem)
            return costs.load(a.table), int(m.group(1)) if m else None, a.table
        n_cal = a.n_cal or n
        if n_cal not in tables:
            cache = a.out_dir / f"cost_table_quest_t{a.threads}_n{n_cal}.json"
            tables[n_cal] = costs.calibrate(n_cal, a.threads, cache)
        return tables[n_cal], n_cal, f"cost_table_quest_t{a.threads}_n{n_cal}.json"

    rows = []
    fields = ["circuit", "n", "fingerprint", "config", "ops", "fuse_s", "sim_min_s", "sim_med_s", "sim_mean_s",
              "reps", "threads", "table_n"]
    with open(a.out_dir / "bench.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for kind in a.circuits:
            for n in a.ns:
                if 16 * 2**n > 0.7 * mem_available():
                    print(f"skip {kind} n={n}: statevector does not fit in 70% of free memory", flush=True)
                    continue
                table, table_n, table_src = table_for(n)
                if table_n != n:
                    print(f"WARNING {kind} n={n}: cost table measured at n={table_n}, not n={n} "
                          f"({table_src}); fusion decisions may be off", flush=True)
                base = circuits.build(kind, n, a.seed, same_seed=a.same_seed)
                v = variants(base, table, a.configs)
                times = time_quest([qc for qc, _ in v.values()], env, a.reps)
                for (cfg, (qc, fuse_s)), ts in zip(v.items(), times):
                    ts = sorted(ts)
                    row = {"circuit": kind, "n": n, "fingerprint": circuits.fingerprint(base), "config": cfg,
                           "ops": len(qc.data), "fuse_s": fuse_s, "sim_min_s": ts[0],
                           "sim_med_s": ts[len(ts) // 2], "sim_mean_s": sum(ts) / len(ts), "reps": a.reps, "threads": a.threads,
                           "table_n": table_n if table_n is not None else "?"}
                    rows.append(row)
                    w.writerow(row)
                fh.flush()
                print(f"{kind} n={n}: " + "  ".join(f"{r['config']}={fmt_t(r['sim_min_s'])}"
                                                    for r in rows[-len(v):]), flush=True)

    meta = (f"Host {socket.gethostname()}, {a.threads} threads, best of {a.reps} round-robin reps, "
            f"rqc seed {a.seed}{'' if a.same_seed else '+n'}, cost table: "
            + (a.table if a.table else f"measured at n={a.n_cal} for every n" if a.n_cal
               else "measured at each benchmark n") + ".")
    (a.out_dir / "RESULTS.md").write_text(markdown(rows, meta) + "\n")
    print(f"wrote {a.out_dir / 'bench.csv'} and RESULTS.md")


if __name__ == "__main__":
    main()
