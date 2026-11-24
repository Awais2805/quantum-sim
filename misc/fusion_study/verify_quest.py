#!/usr/bin/env python3
"""Check quest_runner against Qiskit's Statevector.

verify(qc, prep, amps) is used by quest_bench.py for every plan at small n. Run as a script,
this is the mapping unit test: for n = 4..8, every gate in QUEST_BASIS alone, DENSE and DIAG
blocks for k = 1..4, and a short random mix, all on scrambled qubit orders (controls above
and below targets, matrix qubits not sorted), applied to a random product state so every
amplitude is non-zero. Any case below 1 - 1e-8 overlap fails; for a failing case the test
also tries common convention bugs (reversed qubit order, negated or halved/doubled angles,
conjugated or transposed matrices) and reports which one matches.

  python verify_quest.py                  # full test through the runner
  python verify_quest.py --python-only    # writer round-trip only (no runner needed)
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import UnitaryGate
from qiskit.quantum_info import Statevector, random_unitary

from fusion_bench import random_product_state
from quest_ops import QUEST_BASIS, read_amps, read_qops, write_qops

HERE = Path(__file__).resolve().parent
DEFAULT_RUNNER = HERE / "build" / "quest-linux" / "quest_runner"
TOL = 1e-8


def verify(qc, prep, amps):
    """|<psi|amps>| where psi = qc applied to the state prep makes from |0...0>."""
    psi = Statevector(prep).evolve(qc).data
    return float(abs(np.vdot(psi, amps)))


# --------------------------------------------------------------------------- test cases

def scrambled(rng, n, k):
    """k distinct qubits in a non-sorted order (for k >= 2)."""
    q = [int(x) for x in rng.permutation(n)[:k]]
    if k >= 2 and q == sorted(q):
        q.reverse()
    return q


def gate_cases(rng, n):
    """One case per basis gate; 2-qubit gates twice (control above and below target)."""
    cases = []
    for name in QUEST_BASIS:
        nparams = {"rx": 1, "ry": 1, "rz": 1, "p": 1, "crx": 1, "cry": 1, "crz": 1, "cp": 1,
                   "u": 3}.get(name, 0)
        nq = 2 if name in ("cx", "cy", "cz", "cp", "crx", "cry", "crz", "swap") else 1
        orders = [scrambled(rng, n, nq)]
        if nq == 2:
            orders.append(orders[0][::-1])  # the other control/target ordering
        for q in orders:
            c = QuantumCircuit(n)
            getattr(c, name)(*rng.uniform(-np.pi, np.pi, nparams), *q)
            cases.append((f"{name}{q}", c))
    return cases


def block_cases(rng, n):
    cases = []
    for k in range(1, 5):
        if k > n:
            break
        q = scrambled(rng, n, k)
        c = QuantumCircuit(n)
        c.append(UnitaryGate(random_unitary(2**k, seed=int(rng.integers(1 << 30))).data,
                             check_input=False), q)
        cases.append((f"DENSE k={k} {q}", c))
        q = scrambled(rng, n, k)
        c = QuantumCircuit(n)
        c.append(UnitaryGate(np.diag(np.exp(1j * rng.uniform(0, 2 * np.pi, 2**k))),
                             check_input=False), q)
        cases.append((f"DIAG k={k} {q}", c))
    return cases


def mixed_case(rng, n, length=40):
    c = QuantumCircuit(n)
    for _ in range(length):
        name = QUEST_BASIS[rng.integers(len(QUEST_BASIS))]
        nparams = {"rx": 1, "ry": 1, "rz": 1, "p": 1, "crx": 1, "cry": 1, "crz": 1, "cp": 1,
                   "u": 3}.get(name, 0)
        nq = 2 if name in ("cx", "cy", "cz", "cp", "crx", "cry", "crz", "swap") else 1
        getattr(c, name)(*rng.uniform(-np.pi, np.pi, nparams), *scrambled(rng, n, nq))
    k = min(3, n)
    c.append(UnitaryGate(random_unitary(2**k, seed=1).data, check_input=False),
             scrambled(rng, n, k))
    c.append(UnitaryGate(np.diag(np.exp(1j * rng.uniform(0, 6, 2**k))), check_input=False),
             scrambled(rng, n, k))
    return [(f"mixed[{length}+2 blocks]", c)]


def all_cases(n, seed):
    rng = np.random.default_rng(seed + n)
    return gate_cases(rng, n) + block_cases(rng, n) + mixed_case(rng, n)


# --------------------------------------------------------------------------- diagnosis

def variants(qc):
    """Single-op circuits rewritten with a common convention bug, to name what QuEST did."""
    if len(qc.data) != 1:
        return []
    inst = qc.data[0]
    op, n = inst.operation, qc.num_qubits
    q = [qc.find_bit(b).index for b in inst.qubits]
    out = []

    def one(label, gate, qubits):
        c = QuantumCircuit(n)
        c.append(gate, qubits)
        out.append((label, c))

    if len(q) >= 2:
        one("qubit order reversed", op, q[::-1])
    if op.params and op.name != "unitary":
        for label, f in (("angle negated", -1.0), ("angle halved", 0.5), ("angle doubled", 2.0)):
            g = op.copy()
            g.params = [f * float(p) for p in op.params]
            one(label, g, q)
    m = np.asarray(op.to_matrix())
    one("matrix conjugated", UnitaryGate(m.conj(), check_input=False), q)
    one("matrix transposed", UnitaryGate(m.T, check_input=False), q)
    if len(q) >= 2:
        one("matrix transposed + qubits reversed", UnitaryGate(m.T, check_input=False), q[::-1])
    return out


def diagnose(qc, prep, amps):
    hits = [label for label, c in variants(qc) if verify(c, prep, amps) >= 1 - TOL]
    return ", ".join(hits) if hits else "no simple convention bug matches"


# --------------------------------------------------------------------------- runners

def run_runner(runner, prep_path, plan_paths, outdir):
    cmd = [str(runner), "--reps", "0", "--verify", str(prep_path), str(outdir),
           *map(str, plan_paths)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"runner failed ({r.returncode}): {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")


def test_n(n, seed, runner, tmp, python_only):
    prep = random_product_state(n, seed=seed + 100 + n)
    cases = all_cases(n, seed)
    d = Path(tmp) / f"n{n}"
    (d / "out").mkdir(parents=True, exist_ok=True)
    prep_path = d / "prep.qops"
    write_qops(prep, prep_path)
    plan_paths = []
    for i, (_, c) in enumerate(cases):
        p = d / f"{i}.qops"
        write_qops(c, p)
        plan_paths.append(p)

    failures = []
    # writer round-trip: decode each file and compare with the original circuit
    prep_rt = read_qops(prep_path)
    for (label, c), p in zip(cases, plan_paths):
        ov = verify(read_qops(p), prep_rt, Statevector(prep).evolve(c).data)
        if ov < 1 - TOL:
            failures.append((n, label, "writer round-trip", ov, ""))
    if python_only:
        return len(cases), failures

    run_runner(runner, prep_path, plan_paths, d / "out")
    for i, (label, c) in enumerate(cases):
        amps = read_amps(d / "out" / f"{i}.amps", n)
        ov = verify(c, prep, amps)
        if ov < 1 - TOL:
            failures.append((n, label, "quest", ov, diagnose(c, prep, amps)))
    return len(cases), failures


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runner", default=str(DEFAULT_RUNNER))
    ap.add_argument("--min-n", type=int, default=4)
    ap.add_argument("--max-n", type=int, default=8)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--python-only", action="store_true", help="check the writer only")
    ap.add_argument("--keep", metavar="DIR", help="write the .qops/.amps files here and keep them")
    a = ap.parse_args()

    if not a.python_only and not Path(a.runner).exists():
        sys.exit(f"runner not found: {a.runner} (build it, or use --python-only)")

    with tempfile.TemporaryDirectory(prefix="verify_quest_") as tmp:
        tmp = a.keep or tmp
        total, failures = 0, []
        for n in range(a.min_n, a.max_n + 1):
            cnt, f = test_n(n, a.seed, a.runner, tmp, a.python_only)
            total += cnt
            failures += f
            print(f"n={n}: {cnt} cases, {len(f)} failed", flush=True)

    what = "writer round-trip" if a.python_only else "QuEST vs Statevector"
    if failures:
        print(f"\nFAIL ({what}): {len(failures)} of {total} cases below overlap 1-{TOL:g}")
        for n, label, stage, ov, why in failures:
            print(f"  n={n} {label:28s} [{stage}] overlap={ov:.10f}  {why}")
        sys.exit(1)
    print(f"\nPASS ({what}): all {total} cases, overlap >= 1-{TOL:g}")


if __name__ == "__main__":
    main()
