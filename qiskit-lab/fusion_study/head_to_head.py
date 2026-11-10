#!/usr/bin/env python3
"""Head-to-head: Aer vs QuEST, no fusion vs Aer's fuser vs our fusers, on IDENTICAL circuits.

For every (circuit, n) ONE base circuit is built and every configuration below runs that same
object. rqc is built in QuEST's gate set (quest_ops.QUEST_BASIS) for BOTH simulators, so Aer
and QuEST execute exactly the same gates; the script checks that the build is deterministic and
prints a fingerprint per circuit so other runs (fusion_bench --basis quest, quest_bench) can be
matched against it. Each n is its own random circuit (seed + n), as in the other benchmarks.

Configurations
  Aer   no fusion                   Aer statevector, fusion off
  Aer   Aer built-in fusion         Aer's own fuser (fusion_enable, threshold 1)
  Aer   Aer fuser (offline port)    dp_fusion 'diag+dp' with Aer's constants, Aer fusion off
  Aer   ours: dp / diag+dp          dp_fusion with an Aer-measured cost table
  Aer   ours: diagonal k=8          fusion_bench 'diagonal' blocks up to 8 qubits
  QuEST no fusion
  QuEST Aer fuser plan              dp_fusion 'diag+dp' with Aer's constants
  QuEST ours: dp / diag+dp          dp_fusion with a QuEST-measured cost table
  QuEST ours: diagonal k=8

Timing: sim_min over --reps round-robin reps (Aer: result time_taken; QuEST: quest_runner op
loop), same thread count on both. Before timing, every configuration is checked for state
equivalence with the unfused circuit at --verify-n qubits (Statevector, and QuEST's output).

  python head_to_head.py --ns 18 20 22 24 --reps 3 --threads 4
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit

import fusion_bench as fb
import quest_bench as qb
from dp_fusion import fuse_dp
from quest_ops import QUEST_BASIS, read_amps, write_qops
from verify_quest import verify

HERE = Path(__file__).resolve().parent
OURS_W = 5  # max fused width for the DP fusers

# (id, backend, label)
CONFIGS = [
    ("aer:none", "aer", "Aer · no fusion"),
    ("aer:builtin", "aer", "Aer · Aer built-in fusion"),
    ("aer:aer-port", "aer", "Aer · Aer fuser (offline port)"),
    ("aer:dp", "aer", "Aer · ours: dp (Aer costs)"),
    ("aer:diag+dp", "aer", "Aer · ours: diag+dp (Aer costs)"),
    ("aer:diag8", "aer", "Aer · ours: diagonal k=8"),
    ("quest:none", "quest", "QuEST · no fusion"),
    ("quest:aer-port", "quest", "QuEST · Aer fuser plan"),
    ("quest:dp", "quest", "QuEST · ours: dp (QuEST costs)"),
    ("quest:diag+dp", "quest", "QuEST · ours: diag+dp (QuEST costs)"),
    ("quest:diag8", "quest", "QuEST · ours: diagonal k=8"),
]


def build(kind, n, seed):
    """The one base circuit for (kind, n); asserts the build is deterministic."""
    qc = fb.build_circuit(kind, n, None, seed, basis=QUEST_BASIS)
    again = fb.build_circuit(kind, n, None, seed, basis=QUEST_BASIS)
    if qc != again:
        sys.exit(f"{kind} n={n}: circuit build is not deterministic")
    return qc


def fingerprint(qc):
    h = hashlib.sha256()
    for inst in qc.data:
        h.update(inst.operation.name.encode())
        h.update(str([qc.find_bit(q).index for q in inst.qubits]).encode())
        h.update(str([round(float(p), 12) for p in inst.operation.params]).encode())
    return h.hexdigest()[:12]


def variants(base, aer_table, quest_table):
    """config id -> (simulator kind, circuit). All derived from the same base object."""
    return {
        "aer:none": ("raw", base),
        "aer:builtin": ("fused", base),
        "aer:aer-port": ("raw", fuse_dp(base, "diag+dp", "aer", OURS_W)),
        "aer:dp": ("raw", fuse_dp(base, "dp", aer_table, OURS_W)),
        "aer:diag+dp": ("raw", fuse_dp(base, "diag+dp", aer_table, OURS_W)),
        "aer:diag8": ("raw", fb.fuse(base, "diagonal", 8)),
        "quest:none": ("quest", base),
        "quest:aer-port": ("quest", fuse_dp(base, "diag+dp", "aer", OURS_W)),
        "quest:dp": ("quest", fuse_dp(base, "dp", quest_table, OURS_W)),
        "quest:diag+dp": ("quest", fuse_dp(base, "diag+dp", quest_table, OURS_W)),
        "quest:diag8": ("quest", fb.fuse(base, "diagonal", 8)),
    }


# --------------------------------------------------------------------------- cost tables

def aer_cost_table(sim, n_cal, cache):
    cm = fb.CostModel(sim, n_cal, cache)
    t0 = time.perf_counter()
    for gate in qb.calibration_gates(8, np.random.default_rng(0)).values():
        cm.op_cost(gate)
    print(f"Aer cost table: {len(cm.table)} kinds at {n_cal} qubits ({time.perf_counter() - t0:.0f}s, {cache.name})",
          flush=True)
    return dict(cm.table)


def quest_cost_table(runner, env, n_cal, cache, seed_from=None):
    if not cache.exists() and seed_from and Path(seed_from).exists():
        shutil.copy(seed_from, cache)  # reuse an existing table; calibrate() fills any gaps
    return qb.calibrate(runner, env, n_cal, 8, cache)


# --------------------------------------------------------------------------- checks & timing

def check(kinds, n, seed, aer_table, quest_table, runner, env):
    """Every configuration must reproduce the unfused state (Statevector, and QuEST's output)."""
    prep = fb.random_product_state(n, seed=99)
    bad = []
    with tempfile.TemporaryDirectory(prefix="h2h_") as td:
        td = Path(td)
        write_qops(prep, td / "prep.qops")
        for kind in kinds:
            base = build(kind, n, seed)
            v = variants(base, aer_table, quest_table)
            from qiskit.quantum_info import Statevector
            want = Statevector(prep).evolve(base).data
            for cid, (_, qc) in v.items():
                if verify(qc, prep, want) < 1 - 1e-8:
                    bad.append(f"{kind} {cid} (Statevector)")
            qids = [cid for cid, (s, _) in v.items() if s == "quest"]
            plans = []
            for i, cid in enumerate(qids):
                plans.append(td / f"{kind}_{i}.qops")
                write_qops(v[cid][1], plans[-1])
            out = td / f"out_{kind}"
            out.mkdir()
            qb.run_runner(runner, ["--reps", 0, "--verify", td / "prep.qops", out, *plans], env)
            for i, cid in enumerate(qids):
                if verify(base, prep, read_amps(out / f"{i}.amps", n)) < 1 - 1e-8:
                    bad.append(f"{kind} {cid} (QuEST output)")
    return bad


def time_aer(circs, sims, reps):
    ids = list(circs)
    prepared = {}
    for cid in ids:
        c = circs[cid][1].copy()
        c.save_amplitudes([0])
        prepared[cid] = c
    times = {cid: [] for cid in ids}
    for r in range(reps):
        for cid in ids[r % len(ids):] + ids[:r % len(ids)]:  # rotate the start each rep
            times[cid].append(fb.run_once(sims[circs[cid][0]], prepared[cid])[0])
    return times


def time_quest(circs, runner, env, reps, warmup):
    ids = list(circs)
    with tempfile.TemporaryDirectory(prefix="h2h_") as td:
        plans = []
        for i, cid in enumerate(ids):
            plans.append(Path(td) / f"{i}.qops")
            write_qops(circs[cid][1], plans[-1])
        t = qb.parse_times(qb.run_runner(runner, ["--reps", reps, "--warmup", warmup, *plans], env), len(ids))
    return dict(zip(ids, t))


# --------------------------------------------------------------------------- report

def markdown(results, meta):
    lines = ["# Head-to-head: Aer vs QuEST, no fusion vs Aer's fuser vs ours", "",
             f"{meta}", "",
             "Every row of a table runs the **same circuit object** (rqc in QuEST's gate set on both "
             "simulators). Cells: fastest-rep time, then speedup vs **Aer · no fusion** (the common "
             "reference); in brackets, speedup vs the same simulator's no-fusion. **Bold** = fastest.", ""]
    for kind in sorted({r["circuit"] for r in results}):
        rs = [r for r in results if r["circuit"] == kind]
        ns = sorted({r["n"] for r in rs})
        t = {(r["config"], r["n"]): r for r in rs}
        lines.append(f"## {kind}")
        lines.append("")
        lines.append("| configuration | " + " | ".join(f"n={n} ({t[('aer:none', n)]['ops']} gates, "
                                                       f"{t[('aer:none', n)]['fingerprint']})" for n in ns) + " |")
        lines.append("|---|" + "---|" * len(ns))
        fastest = {n: min((r for r in rs if r["n"] == n), key=lambda r: r["sim_min_s"])["config"] for n in ns}
        for cid, backend, lab in CONFIGS:
            cells = []
            for n in ns:
                r = t.get((cid, n))
                if not r:
                    cells.append("–")
                    continue
                ref = t[("aer:none", n)]["sim_min_s"]
                own = t[(f"{backend}:none", n)]["sim_min_s"]
                s = r["sim_min_s"]
                txt = f"{fmt_t(s)} · {ref / s:.2f}× ({own / s:.2f}×) · {r['ops']} ops"
                cells.append(f"**{txt}**" if fastest[n] == cid else txt)
            lines.append(f"| {lab} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"


def fmt_t(s):
    return f"{s * 1e3:.1f} ms" if s < 1 else f"{s:.2f} s"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--circuits", nargs="+", default=["qft", "rqc"])
    ap.add_argument("--ns", nargs="+", type=int, default=[18, 20, 22, 24])
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1234, help="rqc seed; size n uses seed+n (as elsewhere)")
    ap.add_argument("--n-cal", type=int, default=22, help="qubits for both cost tables")
    ap.add_argument("--verify-n", type=int, default=10)
    ap.add_argument("--runner", default=str(qb.DEFAULT_RUNNER) if hasattr(qb, "DEFAULT_RUNNER")
                    else str(HERE / "build" / "quest-linux" / "quest_runner"))
    ap.add_argument("--quest-table-from", default=None,
                    help="existing QuEST cost table JSON to start from (same host/threads/n)")
    ap.add_argument("--out-dir", default=str(HERE / "results" / "head_to_head"))
    a = ap.parse_args()

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    host = socket.gethostname()
    env = {**os.environ, "OMP_NUM_THREADS": str(a.threads), "OMP_PROC_BIND": "close"}
    raw, fused = fb.make_sim(a.threads), fb.make_sim(a.threads, aer_fusion=True)
    sims = {"raw": raw, "fused": fused}

    aer_table = aer_cost_table(raw, a.n_cal, out / f"cost_table_v2_{host}_CPU_t{a.threads}_n{a.n_cal}_questbasis.json")
    quest_table = quest_cost_table(a.runner, env, a.n_cal, out / f"cost_table_v2_{host}_quest_t{a.threads}_n{a.n_cal}.json",
                                   a.quest_table_from)

    bad = check(a.circuits, a.verify_n, a.seed, aer_table, quest_table, a.runner, env)
    if bad:
        sys.exit("state check FAILED at n=%d: %s" % (a.verify_n, ", ".join(bad)))
    print(f"state check passed at n={a.verify_n}: all {len(CONFIGS)} configurations x {len(a.circuits)} circuits",
          flush=True)

    results = []
    csv_path = out / "head_to_head.csv"
    fields = ["circuit", "n", "fingerprint", "config", "backend", "label", "ops", "sim_min_s", "sim_med_s",
              "sim_max_s", "reps", "threads"]
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for kind in a.circuits:
            for n in a.ns:
                if 16 * 2**n > 0.35 * fb.mem_available_bytes():  # two simulators' states + headroom
                    print(f"skip {kind} n={n}: not enough free memory", flush=True)
                    continue
                t0 = time.time()
                base = build(kind, n, a.seed)
                fp = fingerprint(base)
                v = variants(base, aer_table, quest_table)
                aer_ids = {c: v[c] for c, b, _ in CONFIGS if b == "aer"}
                q_ids = {c: v[c] for c, b, _ in CONFIGS if b == "quest"}
                times = {**time_aer(aer_ids, sims, a.reps),
                         **time_quest(q_ids, a.runner, env, a.reps, int(n < 20))}
                for cid, backend, lab in CONFIGS:
                    ts = sorted(times[cid])
                    row = {"circuit": kind, "n": n, "fingerprint": fp, "config": cid, "backend": backend,
                           "label": lab, "ops": len(v[cid][1].data), "sim_min_s": ts[0],
                           "sim_med_s": ts[len(ts) // 2], "sim_max_s": ts[-1], "reps": a.reps,
                           "threads": a.threads}
                    results.append(row)
                    w.writerow(row)
                fh.flush()
                best = min((r for r in results if r["circuit"] == kind and r["n"] == n), key=lambda r: r["sim_min_s"])
                print(f"{kind} n={n} [{fp}] done in {time.time() - t0:.0f}s; fastest: {best['label']} "
                      f"{fmt_t(best['sim_min_s'])}", flush=True)

    meta = (f"Host {host}, {a.threads} threads, min of {a.reps} round-robin reps, rqc seed {a.seed}+n, "
            f"cost tables at n={a.n_cal}. State check passed at n={a.verify_n}.")
    md = out / "HEAD_TO_HEAD.md"
    md.write_text(markdown(results, meta))
    print(f"wrote {csv_path} and {md}")


if __name__ == "__main__":
    main()
