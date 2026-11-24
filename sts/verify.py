#!/usr/bin/env python3
"""Correctness checks. Any failure exits non-zero.

  mapping  quest_runner vs Qiskit Statevector: every gate in QUEST_BASIS (both control/target
           orders), DENSE and DIAG blocks k = 1..4, and a random mix, on scrambled qubit
           orders, n = 4..8, from a random product state.
  port     fusion.fuse(costs="aer") produces exactly Aer's own fused op list (Aer run with
           fusion_verbose), op by op, for qft and rqc, n = 4..12.
  fused    every fusion config in bench.variants gives the unfused circuit's state, on
           Statevector and on QuEST (n = 10; uses the cost table given, or a toy one).

  python verify.py                      # all three
  python verify.py port fused --table results/<host>/cost_table.json
"""
import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import UnitaryGate
from qiskit.quantum_info import Statevector, random_unitary

import circuits
import costs
from fusion import fuse_ops, to_fops
from qops import read_amps, read_qops, run_runner, write_qops

TOL = 1e-8
PARAMS = {"rx": 1, "ry": 1, "rz": 1, "p": 1, "crx": 1, "cry": 1, "crz": 1, "cp": 1, "u": 3}
TWO_Q = {"cx", "cy", "cz", "cp", "crx", "cry", "crz", "swap"}


def overlap(qc, prep, amps):
    """|<psi|amps>| where psi = qc applied to the state prep makes from |0...0>."""
    return float(abs(np.vdot(Statevector(prep).evolve(qc).data, amps)))


def quest_states(prep, circs, n):
    """Run each circuit on QuEST from prep; returns the output amplitude vectors."""
    with tempfile.TemporaryDirectory(prefix="verify_") as td:
        td = Path(td)
        write_qops(prep, td / "prep.qops")
        plans = []
        for i, c in enumerate(circs):
            plans.append(td / f"{i}.qops")
            write_qops(c, plans[-1])
        run_runner(["--reps", 0, "--verify", td / "prep.qops", td, *plans])
        # writer round-trip on the way: decoding each file must give the same circuit
        for c, p in zip(circs, plans):
            want = Statevector(prep).evolve(c).data
            if overlap(read_qops(p), prep, want) < 1 - TOL:
                raise AssertionError(f"qops writer round-trip failed for {p.name}")
        return [read_amps(td / f"{i}.amps", n) for i in range(len(circs))]


# --------------------------------------------------------------------------- mapping

def scrambled(rng, n, k):
    q = [int(x) for x in rng.permutation(n)[:k]]
    if k >= 2 and q == sorted(q):
        q.reverse()
    return q


def mapping_cases(n, rng):
    cases = []
    for name in circuits.QUEST_BASIS:
        q = scrambled(rng, n, 2 if name in TWO_Q else 1)
        for order in ([q, q[::-1]] if len(q) == 2 else [q]):
            c = QuantumCircuit(n)
            getattr(c, name)(*rng.uniform(-np.pi, np.pi, PARAMS.get(name, 0)), *order)
            cases.append((f"{name}{order}", c))
    for k in range(1, min(4, n) + 1):
        c = QuantumCircuit(n)
        c.append(UnitaryGate(random_unitary(2**k, seed=int(rng.integers(1 << 30))).data,
                             check_input=False), scrambled(rng, n, k))
        cases.append((f"DENSE k={k}", c))
        c = QuantumCircuit(n)
        c.append(UnitaryGate(np.diag(np.exp(1j * rng.uniform(0, 2 * np.pi, 2**k))),
                             check_input=False), scrambled(rng, n, k))
        cases.append((f"DIAG k={k}", c))
    c = QuantumCircuit(n)
    for _ in range(40):
        name = circuits.QUEST_BASIS[rng.integers(len(circuits.QUEST_BASIS))]
        getattr(c, name)(*rng.uniform(-np.pi, np.pi, PARAMS.get(name, 0)),
                         *scrambled(rng, n, 2 if name in TWO_Q else 1))
    cases.append(("random mix", c))
    return cases


def check_mapping(seed=2026):
    bad = []
    for n in range(4, 9):
        rng = np.random.default_rng(seed + n)
        prep = circuits.random_product_state(n, seed=seed + 100 + n)
        cases = mapping_cases(n, rng)
        worst = 1.0
        for (label, c), amps in zip(cases, quest_states(prep, [c for _, c in cases], n)):
            ov = overlap(c, prep, amps)
            worst = min(worst, ov)
            if ov < 1 - TOL:
                bad.append(f"mapping n={n} {label}: overlap {ov:.12f}")
        print(f"  n={n}: {len(cases)} cases (each gate, DENSE/DIAG k=1..4, random mix), "
              f"worst overlap {worst:.12f}", flush=True)
    return bad


# --------------------------------------------------------------------------- port

def aer_fused_ops(qc, max_qubit=5):
    """Aer's own fusion output for qc (fusion_threshold=1, single thread), as dicts."""
    from qiskit_aer import AerSimulator
    sim = AerSimulator(method="statevector", fusion_enable=True, fusion_threshold=1,
                       fusion_verbose=True, fusion_max_qubit=max_qubit,
                       enable_truncation=False, max_parallel_threads=1)
    c = qc.copy()
    c.save_amplitudes([0])
    md = sim.run(c, shots=1).result().results[0].metadata.get("fusion", {})
    return md.get("output_ops") if md.get("applied") else None


def _cplx(x):
    x = np.asarray(x, dtype=float)
    return x[..., 0] + 1j * x[..., 1]


def compare_with_aer(qc, max_qubit=5, atol=1e-10):
    """Port (Aer constants) vs Aer, op by op. Returns mismatch descriptions (empty = match)."""
    ref = aer_fused_ops(qc, max_qubit)
    c = qc.copy()
    c.save_amplitudes([0])  # Aer sees this trailing op too; it bounds the last fusion window
    ours = fuse_ops(c, "aer", "diag+dp", max_qubit) or to_fops(c)
    if ref is None:
        return [] if all(o.kind in ("gate", "other") for o in ours) else ["Aer did not fuse; port did"]
    print(f", Aer {len(ref)} ops, port {len(ours)} ops", end="", flush=True)
    if len(ref) != len(ours):
        return [f"op count: aer {len(ref)} vs port {len(ours)}"]
    for k, (a, o) in enumerate(zip(ref, ours)):
        if a["name"] != o.name or list(a["qubits"]) != list(o.qubits):
            return [f"op {k}: aer {a['name']}{list(a['qubits'])} vs port {o.name}{list(o.qubits)}"]
        if a["name"] == "diagonal" and not np.allclose(_cplx(a["params"]), o.mat, atol=atol):
            return [f"op {k}: diagonal entries differ"]
        if a["name"] == "unitary" and not np.allclose(_cplx(a["mats"][0]), o.mat, atol=atol):
            return [f"op {k}: unitary matrix differs"]
    return []


def check_port():
    bad = []
    for kind in circuits.KINDS:
        for n in range(4, 13):
            qc = circuits.build(kind, n)
            print(f"  {kind} n={n}: {len(qc.data)} gates", end="", flush=True)
            problems = compare_with_aer(qc)
            print(" -> " + ("match" if not problems else "MISMATCH: " + problems[0]), flush=True)
            bad += [f"port {kind} n={n}: {p}" for p in problems]
    return bad


# --------------------------------------------------------------------------- fused

TOY_TABLE = {  # Aer-like shape, only used when no measured table is given
    **{f"{g}/1": 8 for g in ("h", "x", "y", "sx", "sxdg", "rx", "ry", "u")},
    **{f"{g}/1": 3 for g in ("z", "s", "sdg", "t", "tdg", "p", "rz")},
    **{f"{g}/2": 3 for g in ("cx", "cy", "cz", "cp", "crz", "swap")}, "crx/2": 9, "cry/2": 9,
    **{f"dense/{w}": [8, 14, 39, 54, 103][w - 1] for w in range(1, 6)},
    **{f"diag/{w}": [6, 12, 18, 16, 28, 30, 32, 34][w - 1] for w in range(1, 9)},
}


def check_fused(table, n=10):
    from bench import MAKERS, variants
    bad = []
    prep = circuits.random_product_state(n, seed=99)
    for kind in circuits.KINDS:
        base = circuits.build(kind, n)
        want = Statevector(prep).evolve(base).data
        v = variants(base, table, list(MAKERS))
        for (name, (qc, _)), amps in zip(v.items(), quest_states(prep, [qc for qc, _ in v.values()], n)):
            ov_sv, ov_q = overlap(qc, prep, want), float(abs(np.vdot(want, amps)))
            print(f"  {kind} n={n} {name:9s} {len(base.data):4d} -> {len(qc.data):4d} ops   "
                  f"overlap Statevector {ov_sv:.12f}  QuEST {ov_q:.12f}", flush=True)
            if ov_sv < 1 - TOL:
                bad.append(f"fused {kind} {name} (Statevector)")
            if ov_q < 1 - TOL:
                bad.append(f"fused {kind} {name} (QuEST)")
    return bad


ABOUT = {
    "mapping": "quest_runner vs Qiskit Statevector, gate by gate (pass: overlap >= 1 - 1e-8)",
    "port": "our Python fuser with Aer's costs vs Aer's own fused op list, op by op",
    "fused": "every bench config vs the unfused circuit, on Statevector and on QuEST",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("checks", nargs="*", default=["mapping", "port", "fused"])
    ap.add_argument("--table", help="cost table JSON for the 'fused' check (default: a toy table)")
    a = ap.parse_args()
    table = costs.load(a.table) if a.table else TOY_TABLE
    run = {"mapping": check_mapping, "port": check_port, "fused": lambda: check_fused(table)}
    failed = []
    for name in a.checks:
        print(f"\n[{name}] {ABOUT[name]}", flush=True)
        bad = run[name]()
        print(f"{name:8s} {'PASS' if not bad else f'FAIL ({len(bad)})'}", flush=True)
        failed += bad
    for b in failed:
        print("  " + b)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
