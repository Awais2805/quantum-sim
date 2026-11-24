"""Gate fusion pass: a Python port of Qiskit Aer 0.18.2's fuser (src/transpile/fusion.hpp)
that runs on a Qiskit circuit before any simulation, with a pluggable cost model.

    fuse(qc, costs="aer", mode="dp", max_qubit=5) -> QuantumCircuit   (fused copy)
        costs  "aer"       faithful port: Aer's hard-coded constants and quirks (non-AVX2 branch,
                           what Aer 0.18.2 used on the qbench VM); output == Aer's own plan
               "aer-avx2"  the same with Aer's AVX2 cost branch
               dict        a cost table {"h/1": s, "cp/2": s, "dense/3": s, "diag/4": s, ...},
                           seconds per gate kind (costs.py makes these)
        mode   "dp"        NQubitFusion<1> -> NQubitFusion<2> -> CostBasedFusion
               "diag+dp"   DiagonalFusion first (Aer's default pipeline)

    diagonal_blocks(qc, k) -> QuantumCircuit
        extra (not Aer): merge exactly-diagonal gates DAG-wise into diagonal blocks of <= k
        qubits (diagonal gates commute, so they can be gathered across unrelated gates).

Aer's passes (all work on the op LIST in circuit order, not on the DAG):
  DiagonalFusion  runs of consecutive diagonal ops (or cx..cx-diagonal-cx..cx sandwiches)
                  spanning 3..max_qubit qubits -> one diagonal op at the run's last index.
                  Any non-diagonal op, even on unrelated qubits, ends a run.
  NQubitFusion<N> around each N-qubit op, absorb earlier and later ops whose qubits lie inside
                  its N qubits, skipping ops on other qubits; an op that overlaps partly blocks
                  the shared qubits. The group goes to the seed's index. No cost check.
  CostBasedFusion DP over contiguous segments of the list: best[i] = min(best[i-1] + cost(op_i),
                  min_j best[j-1] + est(ops j..i)) over segments touching <= max_qubit qubits.
                  Ties go to the longest segment. Unfused ops cost F = 1.8 each; est = 1.0 for
                  a segment of only u1/cu1/cp (or cx-u1-cx), else F^max(w-1,1) for a w-qubit
                  segment (AVX2 branch: 1.0/1.0/1.1/3.0/F^(w-2) for w = 1/2/3/4/>=5).
                  Fused segments come out as dense unitaries.
  Between passes, consumed ops are removed. Each pass runs over windows separated by ops that
  cannot be fused (measure, save, reset, gates wider than max_qubit); barrier/id/u0 are
  skipped when windowing. Aer quirk kept in "aer" mode: the last op of the circuit is never
  fused (its window ends before it).

With a cost table the pipeline is the same but every decision is priced with the table:
  - a diagonal run / NQubit group is fused only if the fused op is predicted cheaper
  - anything exactly diagonal counts as diagonal (not just Aer's name list), min run width 1
  - a segment is priced diag/w if every op in it is exactly diagonal, else dense/w; a width
    with no table entry is never chosen
  - fused ops that are exactly diagonal are emitted as diagonal UnitaryGates
  - no last-op quirk

Checked by verify.py: port == Aer's own fused op list, and every fused circuit == unfused.
"""
import math
import warnings
from dataclasses import dataclass

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import Gate
from qiskit.circuit.library import UnitaryGate
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.dagcircuit.collect_blocks import BlockCollapser, BlockCollector
from qiskit.quantum_info import Operator

AER_COST_FACTOR = 1.8
AER_DIAG_MIN_QUBIT = 3
AER_DIAG_NAMES = {"p", "cp", "u1", "cu1", "mcu1", "rz", "rzz"}
IGNORABLE = {"barrier", "id", "u0"}


def is_diagonal(op):
    """Exact test, as Aer does: its diagonal kernel is used only when every off-diagonal entry
    is exactly 0 (even 1e-16 sends it down the dense path)."""
    m = op.to_matrix()
    return not np.any(m - np.diag(np.diagonal(m)))


# --------------------------------------------------------------------------- op list

@dataclass
class FOp:
    kind: str              # 'gate' | 'unitary' (dense) | 'diagonal' | 'other' | 'nop'
    name: str
    qubits: tuple
    inst: object = None    # original CircuitInstruction ('gate' / 'other')
    mat: object = None     # dense matrix ('unitary') or diagonal vector ('diagonal')
    _m: object = None      # cached full matrix

    def matrix(self):
        if self._m is None:
            if self.kind == "gate":
                self._m = np.asarray(self.inst.operation.to_matrix(), dtype=complex)
            elif self.kind == "unitary":
                self._m = self.mat
            elif self.kind == "diagonal":
                self._m = np.diag(self.mat)
            else:
                raise ValueError(f"no matrix for {self.kind} op {self.name}")
        return self._m

    def exactly_diagonal(self):
        if self.kind == "diagonal":
            return True
        if self.kind not in ("gate", "unitary"):
            return False
        m = self.matrix()
        return not np.any(m - np.diag(np.diagonal(m)))


def to_fops(qc):
    ops = []
    for inst in qc.data:
        op = inst.operation
        q = tuple(qc.find_bit(b).index for b in inst.qubits)
        if op.name == "unitary":
            ops.append(FOp("unitary", "unitary", q, inst, np.asarray(op.to_matrix(), dtype=complex)))
        elif isinstance(op, Gate):
            ops.append(FOp("gate", op.name, q, inst))
        else:
            ops.append(FOp("other", op.name, q, inst))
    return ops


def to_circuit(ops, template):
    out = template.copy_empty_like()
    for o in ops:
        if o.kind == "nop":
            continue
        if o.kind in ("gate", "other"):
            out.append(o.inst)
        elif o.kind == "unitary":
            out.append(UnitaryGate(o.mat, check_input=False), list(o.qubits))
        else:
            out.append(UnitaryGate(np.diag(o.mat), check_input=False), list(o.qubits))
    return out


def fused_op(ops, idxs, diagonal):
    """Aer's generate_operation: product of ops[idxs] (in index order) on the ascending union of
    their qubits. diagonal=True keeps only the diagonal (Aer's DiagonalFusion)."""
    qubits = sorted({q for i in idxs for q in ops[i].qubits})
    pos = {q: k for k, q in enumerate(qubits)}
    acc = Operator(np.eye(2 ** len(qubits), dtype=complex))
    for i in idxs:
        acc = acc.compose(Operator(ops[i].matrix()), qargs=[pos[q] for q in ops[i].qubits])
    m = acc.data
    if diagonal:
        return FOp("diagonal", "diagonal", tuple(qubits), mat=np.diagonal(m).copy())
    return FOp("unitary", "unitary", tuple(qubits), mat=m)


def allocate(ops, at, idxs, diagonal, measured):
    new = fused_op(ops, idxs, diagonal)
    if measured and new.kind == "unitary" and not np.any(new.mat - np.diag(np.diagonal(new.mat))):
        new = FOp("diagonal", "diagonal", new.qubits, mat=np.diagonal(new.mat).copy())
    for i in idxs:
        ops[i] = FOp("nop", "nop", ())
    ops[at] = new


# --------------------------------------------------------------------------- cost models

class AerCosts:
    measured = False
    min_diag_qubit = AER_DIAG_MIN_QUBIT

    def __init__(self, cost_factor=AER_COST_FACTOR, avx2=False):
        self.f, self.avx2 = cost_factor, avx2

    def op_cost(self, op):
        return 0.0 if op.name in IGNORABLE else self.f

    @staticmethod
    def is_diag_op(op):  # DiagonalFusion::is_diagonal_op
        if op.kind == "diagonal":
            return True
        if op.kind != "gate":
            return False
        if op.name in AER_DIAG_NAMES:
            return True
        if op.name == "u3":
            p = op.inst.operation.params
            return float(p[0]) == 0.0 and float(p[1]) == 0.0
        return False

    @staticmethod
    def _narrow_diag(ops, lo, hi):  # CostBasedFusion::is_diagonal
        i = lo
        while i <= hi:
            if (i + 2 <= hi and ops[i].name == "cx" and ops[i + 1].name == "u1"
                    and ops[i + 2].name == "cx"
                    and ops[i].qubits[1] == ops[i + 1].qubits[0]
                    and ops[i + 1].qubits[0] == ops[i + 2].qubits[1]
                    and ops[i].qubits[0] == ops[i + 2].qubits[0]):
                i += 3
                continue
            if ops[i].name not in ("u1", "cu1", "cp"):
                return False
            i += 1
        return True

    def seg_cost(self, ops, lo, hi, width):  # CostBasedFusion::estimate_cost
        if self._narrow_diag(ops, lo, hi):
            return 1.0
        if self.avx2:
            if width <= 2:
                return 1.0
            if width == 3:
                return 1.1
            if width == 4:
                return 3.0
            return self.f ** max(width - 2, 1)
        return self.f ** max(width - 1, 1)

    def accept_group(self, ops, idxs, diagonal):
        return True  # Aer's diagonal and N-qubit passes do not check costs


class TableCosts:
    measured = True
    min_diag_qubit = 1

    def __init__(self, table):
        self.t = dict(table)
        self._warned = set()

    def _native(self, op):
        key = f"{op.name}/{len(op.qubits)}"
        if key in self.t:
            return self.t[key]
        fallback = f"dense/{len(op.qubits)}"
        if key not in self._warned:
            warnings.warn(f"cost table has no '{key}'; using '{fallback}'")
            self._warned.add(key)
        return self.t.get(fallback, math.inf)

    def op_cost(self, op):
        if op.name in IGNORABLE:
            return 0.0
        w = len(op.qubits)
        if op.kind == "diagonal":
            return self.t.get(f"diag/{w}", math.inf)
        if op.kind == "unitary":
            return self.t.get(f"{'diag' if op.exactly_diagonal() else 'dense'}/{w}", math.inf)
        return self._native(op)

    @staticmethod
    def is_diag_op(op):
        return op.kind in ("gate", "unitary", "diagonal") and op.exactly_diagonal()

    def fused_cost(self, diagonal, width):
        return self.t.get(f"{'diag' if diagonal else 'dense'}/{width}", math.inf)

    def seg_cost(self, ops, lo, hi, width):
        diag = all(ops[i].name in IGNORABLE or ops[i].exactly_diagonal() for i in range(lo, hi + 1))
        return self.fused_cost(diag, width)

    def accept_group(self, ops, idxs, diagonal):
        width = len({q for i in idxs for q in ops[i].qubits})
        diag = diagonal or all(ops[i].exactly_diagonal() for i in idxs)
        return self.fused_cost(diag, width) < sum(self.op_cost(ops[i]) for i in idxs)


# --------------------------------------------------------------------------- passes

def can_apply(op, max_qubit):  # UnitaryFusion::can_apply
    return op.kind in ("gate", "unitary", "diagonal") and len(op.qubits) <= max_qubit


def diagonal_pass(ops, start, end, max_qubit, cm):
    """DiagonalFusion::aggregate_operations over ops[start:end]."""

    def next_diag_end(frm, s):
        if frm >= len(ops) or (cm.measured and frm >= end):
            return -1  # Aer reads ops[end] here (see quirk note); never past the list
        if cm.is_diag_op(ops[frm]):
            s.update(ops[frm].qubits)
            return frm
        if ops[frm].kind != "gate":
            return -1
        pos = frm
        while pos < end and ops[pos].name == "cx":
            pos += 1
        if pos == frm or pos == end:
            return -1
        cx_end = pos - 1
        found = False
        while pos < end and cm.is_diag_op(ops[pos]):
            found = True
            pos += 1
        if not found or pos == end:
            return -1
        u1_end = pos
        while pos < end:
            o = ops[pos]
            if o.kind == "gate" and o.name == ops[cx_end].name and o.qubits == ops[cx_end].qubits:
                if cx_end == frm:
                    break
                cx_end -= 1
            else:
                return -1
            pos += 1
        if pos == end:
            return -1
        for i in range(frm, u1_end):
            s.update(ops[i].qubits)
        return pos

    op_idx = start
    while op_idx < end:
        s = set()
        nde = next_diag_end(op_idx, s)
        if nde < 0 or len(s) > max_qubit:
            op_idx += 1
            continue
        nds = nde + 1
        while True:
            # Aer quirk: an op that overflows max_qubit is not taken, but its qubits stay in s
            # (only affects the min_qubit test, which then passes anyway since |s| > max >= 3).
            trial = set(s) if cm.measured else s
            nde = next_diag_end(nds, trial)
            if nde < 0 or len(trial) > max_qubit:
                break
            s = trial
            nds = nde + 1
        if len(s) < cm.min_diag_qubit:
            op_idx += 1
            continue
        idxs = list(range(op_idx, nds))
        if len(idxs) >= 2 or not cm.measured:
            if cm.accept_group(ops, idxs, True):
                allocate(ops, nds - 1, idxs, True, cm.measured)
        op_idx = nds


def nqubit_pass(n_q, ops, start, end, max_qubit, cm):
    """NQubitFusion<n_q>::aggregate_operations over ops[start:end]."""
    for op_idx in range(start, end):
        seed = ops[op_idx]
        if seed.kind == "nop" or not can_apply(seed, max_qubit) or len(seed.qubits) != n_q:
            continue
        idxs = [op_idx]
        for rng in (range(op_idx - 1, start - 1, -1), range(op_idx + 1, end)):
            live = list(seed.qubits)
            found = []
            for j in rng:
                t = ops[j]
                if t.kind == "nop":
                    continue
                if not can_apply(t, max_qubit):
                    break
                if all(q in live for q in t.qubits):
                    found.append(j)
                else:
                    live = [q for q in live if q not in t.qubits]
                    if not live:
                        break
            idxs.extend(found)
        idxs.sort()
        if len(idxs) <= 1:
            continue
        if cm.accept_group(ops, idxs, False):
            allocate(ops, op_idx, idxs, False, cm.measured)


def cost_based_pass(ops, start, end, max_qubit, cm):
    """CostBasedFusion::aggregate_operations: DP over contiguous segments of ops[start:end]."""
    if end - start < 2:
        return
    best = [0.0] * (end - start)
    to = list(range(start, end))
    best[0] = cm.op_cost(ops[start])
    for i in range(start + 1, end):
        r = i - start
        best[r] = best[r - 1] + cm.op_cost(ops[i])
        qs = set(ops[i].qubits)
        for j in range(i - 1, start - 1, -1):
            qs.update(ops[j].qubits)
            if len(qs) > max_qubit:
                break
            c = cm.seg_cost(ops, j, i, len(qs)) + (best[j - 1 - start] if j > start else 0.0)
            if c <= best[r]:  # '<=': ties go to the smaller j, i.e. the longer segment
                best[r], to[r] = c, j
    i = end - 1
    while i >= start:
        j = to[i - start]
        if j != i:
            allocate(ops, i, list(range(j, i + 1)), False, cm.measured)
        i = j - 1


def run_pass(ops, fuser, max_qubit, cm):
    """Fusion::optimize_circuit windowing, then drop consumed ops."""
    start = 0
    last = len(ops) - 1
    for idx in range(len(ops)):
        if ops[idx].name in IGNORABLE:
            continue
        if not can_apply(ops[idx], max_qubit):
            fuser(ops, start, idx, max_qubit, cm)
            start = idx + 1
        elif idx == last:
            fuser(ops, start, idx + 1 if cm.measured else idx, max_qubit, cm)  # Aer: last op excluded
            start = idx + 1
    if cm.measured and start < len(ops):
        fuser(ops, start, len(ops), max_qubit, cm)  # trailing ignorable ops (Aer skips this)
    return [o for o in ops if o.kind != "nop"]


def fuse(qc, costs="aer", mode="dp", max_qubit=5):
    """Fused copy of qc; see the module docstring."""
    ops = fuse_ops(qc, costs, mode, max_qubit)
    return qc.copy() if ops is None else to_circuit(ops, qc)


def fuse_ops(qc, costs="aer", mode="dp", max_qubit=5):
    """The fused op list itself (None if qc has fewer than 2 ops)."""
    if mode not in ("dp", "diag+dp"):
        raise ValueError(f"mode must be 'dp' or 'diag+dp', not {mode!r}")
    if isinstance(costs, str):
        if costs not in ("aer", "aer-avx2"):
            raise ValueError(f"costs must be 'aer', 'aer-avx2' or a dict, not {costs!r}")
        cm = AerCosts(avx2=(costs == "aer-avx2"))
    else:
        cm = TableCosts(costs)
    if cm.measured:  # never pick a width the table cannot price
        widths = [w for w in range(1, max_qubit + 1)
                  if f"dense/{w}" in cm.t or f"diag/{w}" in cm.t]
        max_qubit = max(widths) if widths else 1
    ops = to_fops(qc)
    if len(ops) < 2:
        return None
    passes = ([diagonal_pass] if mode == "diag+dp" else []) + [
        lambda o, s, e, m, c: nqubit_pass(1, o, s, e, m, c),
        lambda o, s, e, m, c: nqubit_pass(2, o, s, e, m, c),
        cost_based_pass,
    ]
    for p in passes:
        ops = run_pass(ops, p, max_qubit, cm)
    return ops


# --------------------------------------------------------------------------- diagonal blocks

_DIAG_CACHE = {}


def _node_is_diagonal(node):
    op = node.op
    if not isinstance(op, Gate):
        return False
    if op.name == "unitary":
        return is_diagonal(op)
    try:
        key = (op.name, op.num_qubits, tuple(float(p) for p in op.params))
    except (TypeError, ValueError):
        return False
    if key not in _DIAG_CACHE:
        try:
            _DIAG_CACHE[key] = is_diagonal(op)
        except Exception:  # no matrix available
            _DIAG_CACHE[key] = False
    return _DIAG_CACHE[key]


def diagonal_blocks(qc, k=8):
    """Merge exactly-diagonal gates into diagonal UnitaryGates of <= k qubits, collecting on the
    DAG with Qiskit's BlockCollector (unlike Aer's DiagonalFusion, a non-diagonal gate on other
    qubits does not end a block). No cost check: on QuEST a diagonal sweep costs about the same
    for any width up to ~8 (see results/head_to_head)."""
    dag = circuit_to_dag(qc)
    blocks = BlockCollector(dag).collect_all_matching_blocks(
        filter_fn=lambda nd: len(nd.qargs) <= k and _node_is_diagonal(nd),
        split_blocks=False, split_layers=False, min_block_size=2, max_block_width=k,
    )
    dag = BlockCollapser(dag).collapse_to_operation(
        blocks, lambda c: UnitaryGate(Operator(c), check_input=False))
    return dag_to_circuit(dag)
