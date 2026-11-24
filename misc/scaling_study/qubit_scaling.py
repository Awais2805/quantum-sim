r"""
Qubit-scaling latency benchmark for Qiskit Aer.

Every circuit is first lowered to BASIS with no optimisation, then the chosen
optimisation passes are applied. Each item given to --passes is one line on the plot:
    none                  no optimisation (baseline)
    merge_1q              a single pass
    merge_1q+commutation  a group of passes applied together, in that order
    all                   every pass in PASSES

Examples:
    python qubit_scaling.py --qubits 8
    python qubit_scaling.py --range 4 12 --passes merge_1q
    python qubit_scaling.py --range 4 12 --passes none merge_1q commutation
    python qubit_scaling.py --range 8 20 --circuit qft --passes none merge_1q+cancel_inverse all
    python qubit_scaling.py --range 10 24 --circuit qft --fusion on off --metric sim
    python qubit_scaling.py --range 4 16 --fusion on off --fusion-threshold 1
    python qubit_scaling.py --range 10 24 --circuit qft --threads 1 8 --metric sim

Dedicated RAM (asks for sudo once). The sim gets 2 GB that no other process can take,
is capped at 2 GB and never swaps; the rest of the system keeps using swap as normal:
    python qubit_scaling.py --dedicated-ram 2G --range 10 26 --circuit qft \
        --fusion off on --fusion-threshold 1 --metric sim gates_fused

Swap / PCIe experiments (asks for your sudo password once; restores swap at the end):
    python qubit_scaling.py --range 24 28 --circuit qft --swap-mode nvme --metric nvme_read_mb
    # low vs high target qubit: same gates, different amplitude-pair distance (fusion off!)
    python qubit_scaling.py --qubits 27 --circuit low_q --fusion off --swap-mode nvme
    python qubit_scaling.py --qubits 27 --circuit high_q --fusion off --swap-mode nvme

Runs keep the laptop awake until they finish (lid closed or idle on battery); a
blocked suspend is released automatically when the run ends. --allow-sleep opts out.

To extend:
    - new circuit           -> add a function to CIRCUITS
    - new optimisation      -> add an entry to PASSES
    - new simulator option  -> add it to SIM_OPTIONS (or pass via a new flag)
"""
import argparse
import csv
import math
import os
import re
import resource
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter, MaxNLocator, NullFormatter
from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import QFTGate
from qiskit.circuit.library import CXGate, XGate
from qiskit.circuit.random import random_circuit
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes import (CommutativeCancellation, ConsolidateBlocks,
                                      InverseCancellation, Optimize1qGatesDecomposition,
                                      UnitarySynthesis)
from qiskit_aer import AerSimulator


# ---------------------------------------------------------------- circuits
def ghz(n):
    qc = QuantumCircuit(n)
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    return qc


def qft(n):
    qc = QuantumCircuit(n)
    qc.h(range(n))
    qc.append(QFTGate(n), range(n))
    return qc


def rqc(n):
    return random_circuit(n, depth=n, max_operands=2, seed=42)


# Stride micro-benchmarks: STRIDE_GATES identical 1-qubit gates on the lowest or highest
# qubit. Gate on qubit q pairs amplitudes 2^q apart (16 * 2^q bytes), so these isolate the
# effect of pair distance. Run with --fusion off, otherwise Aer merges them into one op.
STRIDE_GATES = 16


def low_q(n):
    qc = QuantumCircuit(n)
    for _ in range(STRIDE_GATES):
        qc.sx(0)
    return qc


def high_q(n):
    qc = QuantumCircuit(n)
    for _ in range(STRIDE_GATES):
        qc.sx(n - 1)
    return qc


CIRCUITS = {"ghz": ghz, "qft": qft, "random": rqc, "low_q": low_q, "high_q": high_q}

# Final save instruction. save_amplitudes([0]) forces the full simulation but returns one
# amplitude, so Aer does not copy the whole statevector into Python (that copy would
# double peak memory: 2 GB instead of 1 GB at 26 qubits).
def add_save(qc):
    qc.save_amplitudes([0])


SAVE_OPS = {"save_amplitudes", "save_statevector"}

# Options passed to AerSimulator() for every run.
SIM_OPTIONS = {"method": "statevector"}

# Gate set every circuit is lowered to before optimising. A hardware-like basis
# gives the passes real work to do (Aer's native set would leave little to optimise).
BASIS = ["rz", "sx", "x", "cx"]

# Optimisation methods. Each entry returns a fresh list of transpiler passes.
PASSES = {
    # merge runs of 1-qubit gates into the fewest basis gates
    "merge_1q":       lambda: [Optimize1qGatesDecomposition(basis=BASIS)],
    # remove adjacent gate pairs that undo each other (CX CX, X X)
    "cancel_inverse": lambda: [InverseCancellation([CXGate(), XGate()])],
    # cancel/merge gates that can be commuted next to each other
    "commutation":    lambda: [CommutativeCancellation(basis_gates=BASIS)],
    # collect 2-qubit blocks and re-synthesise each with the fewest CXs
    "resynth_2q":     lambda: [ConsolidateBlocks(basis_gates=BASIS),
                               UnitarySynthesis(basis_gates=BASIS)],
}

# Plot labels; the plot adds the unit (ms or s) itself for time metrics.
METRICS = {
    "total":          "Total time",                         # transpile + run (wall clock)
    "transpile":      "Transpile time",
    "run":            "Run time, wall clock",
    "sim":            "Aer gate-apply time",                # Aer's own time minus fusion
    "fusion_time":    "Aer fusion time",                    # time Aer spent fusing gates
    "sweep":          "Time per statevector sweep",         # sim time / ops executed (stored in us)
    "bandwidth":      "Effective memory bandwidth (GB/s)",  # bytes moved / sim time
    # swap / PCIe counters, measured around sim.run() only
    "swap_in_mb":     "System swap-in (MB)",                # all processes, zram + NVMe
    "swap_out_mb":    "System swap-out (MB)",               # (informational, not the sim)
    "nvme_read_mb":   "NVMe read (MB)",                     # bytes over the PCIe link
    "nvme_write_mb":  "NVMe write (MB)",
    "nvme_read_ios":  "NVMe read requests",                 # how often the link was used
    "nvme_read_mbps": "NVMe read throughput (MB/s)",        # read MB / run time
    "sv_over_link":   "Statevectors read over PCIe",        # NVMe read bytes / SV bytes
    "majflt":         "Major page faults",                  # this process, needed disk/zram
    "minflt":         "Minor page faults",                  # first touch of fresh pages, no I/O
    "mem_stall_ms":   "Memory stall time (ms)",             # PSI: time the sim waited on memory
    "cap_hits":       "RAM cap hits",                       # times the sim reached memory.max
    "gates_fused":    "Gates applied by Aer",               # after passes + fusion
}
ROW_METRICS = {"gates_fused"}               # one value per row (no repeats / std)
TIME_METRICS = {"total", "transpile", "run", "sim", "fusion_time", "sweep"}
NON_TIME_METRICS = set(METRICS) - TIME_METRICS
LOG_METRICS = TIME_METRICS | {"gates_fused"}
STORED_IN_US = {"sweep"}                    # every other time metric is stored in seconds


# --------------------------------------------------------- memory / swap I/O
SWAP_DEVICE = "nvme0n1"                     # block device the swap file lives on
SWAP_HELPER = Path(__file__).resolve().with_name("swap_mode.sh")
SLICE_HELPER = Path(__file__).resolve().with_name("svsim_slice.sh")
PAGE_BYTES = os.sysconf("SC_PAGE_SIZE")     # 4096: unit of swap traffic
AMP_BYTES = 16                              # complex128 amplitude


def io_counters():
    """Snapshot of swap, NVMe and page-fault counters."""
    with open("/proc/vmstat") as f:
        vm = dict(line.split() for line in f)
    with open(f"/sys/block/{SWAP_DEVICE}/stat") as f:
        disk = [int(x) for x in f.read().split()]
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "pswpin": int(vm["pswpin"]),        # pages
        "pswpout": int(vm["pswpout"]),
        "rd_ios": disk[0], "rd_sectors": disk[2],   # sectors are 512 B
        "wr_ios": disk[4], "wr_sectors": disk[6],
        "majflt": ru.ru_majflt,
        "minflt": ru.ru_minflt,
        "psi_us": psi_stall_us() or 0,
        "cap_hits": cap_hits(),
    }


def own_cgroup():
    """This process's cgroup v2 path, e.g. /svsim.slice/run-xyz.scope."""
    with open("/proc/self/cgroup") as f:
        return f.read().strip().split("::")[-1]


def cgroup_value(name):
    """Read a cgroup v2 file for this process (e.g. memory.max), or None."""
    try:
        with open(f"/sys/fs/cgroup{own_cgroup()}/{name}") as f:
            return f.read().strip()
    except OSError:
        return None


def protected_bytes():
    """Effective memory.min: the kernel only honours protection that every parent
    cgroup also grants, so take the smallest value on the path up to the root."""
    cg, vals = own_cgroup(), []
    while cg not in ("", "/"):
        try:
            with open(f"/sys/fs/cgroup{cg}/memory.min") as f:
                vals.append(int(f.read()))
        except (OSError, ValueError):
            return 0
        cg = os.path.dirname(cg)
    return min(vals) if vals else 0


def psi_stall_us():
    """Total time (us) tasks in this cgroup were stalled on memory (PSI 'some'), or None."""
    text = cgroup_value("memory.pressure")
    if not text:
        return None
    return int(re.search(r"^some .*total=(\d+)", text, re.M).group(1))


def cap_hits():
    """How many times this cgroup's usage reached memory.max (memory.events 'max')."""
    text = cgroup_value("memory.events") or ""
    m = re.search(r"^max (\d+)", text, re.M)
    return int(m.group(1)) if m else 0


def parse_size(text):
    """'2G' / '2048M' / '512K' / bytes -> bytes (powers of 1024, like systemd)."""
    m = re.fullmatch(r"(\d+)([KMG]?)", text)
    if not m:
        raise argparse.ArgumentTypeError(f"size like 2G or 2048M, not {text!r}")
    return int(m.group(1)) * 1024 ** " KMG".index(m.group(2) or " ")


def ram_budget_bytes():
    """RAM the sim can rely on. With dedicated RAM that is the protected amount (other
    processes are reclaimed first); otherwise MemAvailable, or a lower MemoryMax."""
    limit = cgroup_value("memory.max")
    limit = int(limit) if limit and limit != "max" else None
    prot = protected_bytes()
    if prot and limit:
        return min(prot, limit)
    with open("/proc/meminfo") as f:
        avail = next(int(l.split()[1]) * 1024 for l in f if l.startswith("MemAvailable"))
    return min(avail, limit) if limit else avail


def reexec_in_slice(size):
    """Restart this script inside svsim_slice.sh (sudo) with SIZE of dedicated RAM."""
    print(f"restarting inside {size} of dedicated RAM (sudo {SLICE_HELPER.name}) ...",
          flush=True)
    os.execvp("sudo", ["sudo", str(SLICE_HELPER), size, "--", sys.executable,
                       str(Path(__file__).resolve()), *sys.argv[1:]])


def setup_dedicated(size):
    """Verify the dedicated RAM is really in place, then touch it once so other
    processes' pages are moved out before timing starts (not during a run)."""
    prot = protected_bytes()
    limit, swap = cgroup_value("memory.max"), cgroup_value("memory.swap.max")
    if (os.environ.get("SVSIM_SLICE") != "1" or prot < size - PAGE_BYTES
            or limit in (None, "max") or swap != "0"):
        raise SystemExit(
            f"dedicated RAM is NOT in place: protected {prot / 2**30:.2f} GB "
            f"(need {size / 2**30:.2f}), memory.max={limit}, swap.max={swap}. "
            f"Start the run with --dedicated-ram so svsim_slice.sh sets it up.")
    used = int(cgroup_value("memory.current") or 0)
    touch = size - used - 256 * 2 ** 20     # leave headroom below the cap
    t0, stall0 = time.perf_counter(), psi_stall_us() or 0
    if touch > 0:
        buf = np.ones(touch, dtype=np.uint8)            # writes every page once
        del buf
    print(f"dedicated RAM: {prot / 2**30:.2f} GB protected from other processes, "
          f"capped at {int(limit) / 2**30:.2f} GB, swap off for the sim | pre-touched "
          f"{max(touch, 0) / 2**30:.2f} GB in {time.perf_counter() - t0:.1f}s "
          f"(waited {((psi_stall_us() or 0) - stall0) / 1000:.0f} ms for memory)")


def stride_counts(op_qubits, ram_bytes):
    """Classify ops by the distance between the amplitude pairs they combine.

    An op whose highest qubit is t pairs amplitudes 16 * 2^t bytes apart:
      cross_page : pair sits in different 4 KiB pages (t >= 8), so a swapped-out
                   statevector needs two separate pages brought in per pair
      beyond_ram : pair is further apart than the RAM budget, so both halves can
                   never be resident together
    """
    page_q = int(math.log2(PAGE_BYTES // AMP_BYTES))
    ram_q = int(math.log2(max(ram_bytes, AMP_BYTES) // AMP_BYTES))
    tops = [max(q) for q in op_qubits if q]
    return {"gates_cross_page": sum(t >= page_q for t in tops),
            "gates_beyond_ram": sum(t >= ram_q for t in tops)}


def set_swap_mode(mode):
    """Run the root helper via sudo (prompts for your password in the terminal)."""
    subprocess.run(["sudo", str(SWAP_HELPER), mode], check=True)


def stay_awake():
    """Block lid-close and suspend until this PID exits; releases itself afterwards.

    Tied to os.getpid(), which lives on as the sudo process for --dedicated-ram runs.
    systemd-inhibit stops logind suspending on lid close; gnome-session-inhibit stops
    GNOME's own idle suspend (on battery after 15 min by default)."""
    pid = os.getpid()
    why = f"qubit_scaling benchmark running (PID {pid})"
    watch = ["tail", f"--pid={pid}", "-f", "/dev/null"]   # exits when this PID does
    helpers = {
        "systemd-inhibit": ["systemd-inhibit", "--what=handle-lid-switch:sleep",
                            "--mode=block", "--who=qubit_scaling", f"--why={why}", *watch],
        "gnome-session-inhibit": ["gnome-session-inhibit", "--inhibit", "suspend",
                                  "--reason", why, *watch],
    }
    procs = {name: subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
             for name, cmd in helpers.items() if shutil.which(name)}
    time.sleep(0.5)                         # a helper that was refused exits straight away
    held = [name for name, proc in procs.items() if proc.poll() is None]
    missing = sorted(set(helpers) - set(held))
    print(f"stay awake: lid close and suspend blocked until this run ends "
          f"({', '.join(held) or 'nothing held'})"
          + (f" | NOT held: {', '.join(missing)}" if missing else ""), flush=True)


def keep_sudo_alive():
    """Refresh sudo's timestamp so restoring swap at the end needs no second password."""
    def loop():
        while True:
            time.sleep(120)
            subprocess.run(["sudo", "-n", "-v"], capture_output=True)
    threading.Thread(target=loop, daemon=True).start()


# ------------------------------------------------------------------- timing
def parse_group(spec):
    """'none' -> [], 'all' -> every pass, 'a+b' -> [a, b]."""
    if spec == "none":
        return []
    if spec == "all":
        return list(PASSES)
    names = spec.split("+")
    unknown = [x for x in names if x not in PASSES]
    if unknown:
        raise SystemExit(f"unknown pass(es) {unknown}; choose from {list(PASSES)}, none, all")
    return names


def benchmark(n, circuit_name, spec, sim, repeats):
    names = parse_group(spec)
    base = CIRCUITS[circuit_name](n)
    sv_bytes = AMP_BYTES * 2 ** n
    ram_bytes = ram_budget_bytes()

    samples = {k: [] for k in METRICS if k not in ROW_METRICS}
    for i in range(repeats + 1):            # first iteration is a warm-up
        t0 = time.perf_counter()
        lowered = transpile(base, basis_gates=BASIS, optimization_level=0)   # lower only
        pm = PassManager([p for name in names for p in PASSES[name]()])
        tqc = pm.run(lowered)                                               # chosen passes
        t1 = time.perf_counter()
        gates_passes, depth = tqc.size(), tqc.depth()
        add_save(tqc)                       # added after transpile so any basis works
        io0 = io_counters()
        result = sim.run(tqc).result()
        io1 = io_counters()
        t2 = time.perf_counter()
        if i == 0:
            continue

        exp = result.results[0]
        fusion = exp.metadata.get("fusion", {})
        fusion_s = fusion.get("time_taken", 0.0)
        sim_s = max(exp.time_taken - fusion_s, 1e-9)
        run_s = t2 - t1
        # ops Aer actually applied (and the qubits each acts on)
        if fusion.get("applied"):
            op_qubits = [op["qubits"] for op in fusion["output_ops"]
                         if op["name"] not in SAVE_OPS]
        else:
            op_qubits = [[tqc.find_bit(q).index for q in inst.qubits]
                         for inst in tqc.data if inst.operation.name not in SAVE_OPS]
        executed = max(len(op_qubits), 1)

        d = {k: io1[k] - io0[k] for k in io0}
        nvme_read = d["rd_sectors"] * 512
        samples["total"].append(t2 - t0)
        samples["transpile"].append(t1 - t0)
        samples["run"].append(run_s)
        samples["sim"].append(sim_s)
        samples["fusion_time"].append(fusion_s)
        samples["sweep"].append(sim_s / executed * 1e6)
        # each op reads + writes the whole statevector once (approximation)
        samples["bandwidth"].append(2 * executed * sv_bytes / sim_s / 1e9)
        samples["swap_in_mb"].append(d["pswpin"] * PAGE_BYTES / 2 ** 20)
        samples["swap_out_mb"].append(d["pswpout"] * PAGE_BYTES / 2 ** 20)
        samples["nvme_read_mb"].append(nvme_read / 2 ** 20)
        samples["nvme_write_mb"].append(d["wr_sectors"] * 512 / 2 ** 20)
        samples["nvme_read_ios"].append(d["rd_ios"])
        samples["nvme_read_mbps"].append(nvme_read / 2 ** 20 / run_s)
        samples["sv_over_link"].append(nvme_read / sv_bytes)
        samples["majflt"].append(d["majflt"])
        samples["minflt"].append(d["minflt"])
        samples["mem_stall_ms"].append(d["psi_us"] / 1000)
        samples["cap_hits"].append(d["cap_hits"])

    row = {
        "n": n,
        "passes": spec,
        "fusion": "on" if fusion.get("enabled") else "off",
        "fusion_applied": bool(fusion.get("applied")),
        "gates_in": lowered.size(),         # after lowering to BASIS
        "gates_passes": gates_passes,       # after chosen transpiler passes
        "gates_fused": executed,            # what Aer applied after fusion
        **stride_counts(op_qubits, ram_bytes),
        "depth": depth,
        "sv_mb": sv_bytes / 2 ** 20,
        "ram_budget_mb": ram_bytes / 2 ** 20,
        "aer_mem_mb": exp.metadata.get("required_memory_mb"),
        # thread cap Aer reports; with threads=auto Aer still runs 1 thread below 14 qubits
        "aer_threads": exp.metadata.get("parallel_state_update"),
    }
    for key, vals in samples.items():
        row[key] = statistics.median(vals)
        row[f"{key}_std"] = statistics.stdev(vals) if len(vals) > 1 else 0.0
    # clean = the sim itself never waited on memory management: no major faults, no PSI
    # memory stall, never hit its RAM cap. (Other processes swapping is fine.)
    row["clean"] = all(max(samples[k]) == 0 for k in ("majflt", "mem_stall_ms", "cap_hits"))
    return row


# ----------------------------------------------------------------- output
def save_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def plot(rows, metric, title, path):
    is_time = metric not in NON_TIME_METRICS
    ylabel, scale = METRICS[metric], 1.0
    if is_time:                             # show in s if typical value >= 1 s, else ms
        to_s = 1e-6 if metric in STORED_IN_US else 1.0
        median_s = statistics.median(r[metric] for r in rows) * to_s
        unit, unit_s = ("s", 1.0) if median_s >= 1 else ("ms", 1e-3)
        scale = unit_s / to_s
        ylabel = f"{ylabel} ({unit})"

    fig, ax = plt.subplots(figsize=(7, 4.5))
    for label in dict.fromkeys(r["label"] for r in rows):
        pts = [r for r in rows if r["label"] == label]
        ax.errorbar([r["n"] for r in pts],
                    [r[metric] / scale for r in pts],
                    yerr=[r.get(f"{metric}_std", 0.0) / scale for r in pts],
                    marker="o", capsize=3, label=label)
    ax.set_xlabel("Number of qubits")
    ax.set_ylabel(ylabel)
    if metric in LOG_METRICS:
        ax.set_yscale("log")
        # plain decimals (0.01, 0.1, 1, 10) instead of 10^x / scientific notation
        def plain(v, _=None):
            return np.format_float_positional(v, precision=3, unique=False,
                                              fractional=False, trim="-")

        def minor(v, _=None):               # only label the 2x and 5x ticks between decades
            mantissa = v / 10 ** np.floor(np.log10(v))
            return plain(v) if round(mantissa) in (2, 5) else ""

        ax.yaxis.set_major_formatter(FuncFormatter(plain))
        values = [r[metric] for r in rows if r[metric] > 0]
        if values and max(values) / min(values) < 100:  # narrow range: label some minor ticks
            ax.yaxis.set_minor_formatter(FuncFormatter(minor))
        else:
            ax.yaxis.set_minor_formatter(NullFormatter())
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(alpha=0.3)
    ax.legend(title="passes | fusion | threads")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


# ------------------------------------------------------------------- main
def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--qubits", type=int, help="run a single qubit count")
    g.add_argument("--range", type=int, nargs=2, metavar=("START", "END"),
                   help="run every qubit count from START to END inclusive")
    p.add_argument("--step", type=int, default=1)
    p.add_argument("--circuit", choices=CIRCUITS, default="ghz")
    p.add_argument("--passes", nargs="+", default=["none"], metavar="SPEC",
                   help=f"optimisations to compare: none, all, or names from "
                        f"{list(PASSES)}; join with + to group (e.g. merge_1q+commutation)")
    p.add_argument("--fusion", nargs="+", choices=["on", "off"], default=["on"],
                   help="Aer gate fusion; give 'on off' to compare both")
    p.add_argument("--fusion-threshold", type=int, default=14,
                   help="min qubits before Aer applies fusion (Aer default 14)")
    p.add_argument("--fusion-max-qubits", type=int, default=5,
                   help="max qubits in one fused gate (Aer default 5)")
    p.add_argument("--threads", type=int, nargs="+", default=[1],
                   help="Aer threads; give several to compare (e.g. 1 8). "
                        "0 = Aer's default (1 thread below 14 qubits, all cores above)")
    p.add_argument("--swap-mode", choices=["normal", "nvme"], default="normal",
                   help="nvme: make the NVMe swap file top priority and maximise free RAM "
                        "for this run (uses sudo via swap_mode.sh; restored afterwards)")
    p.add_argument("--dedicated-ram", metavar="SIZE", default=None,
                   help="e.g. 2G: run inside SIZE of RAM reserved for the sim (other "
                        "processes cannot take it), capped at SIZE, sim never swaps. "
                        "Uses sudo via svsim_slice.sh; the rest of the system is unchanged")
    p.add_argument("--allow-sleep", action="store_true",
                   help="do not block lid-close / idle suspend while the run is going")
    p.add_argument("--max-memory-mb", type=int, default=None,
                   help="raise Aer's memory limit (default: physical RAM) so statevectors "
                        "larger than RAM are allowed to spill into swap")
    p.add_argument("--metric", nargs="+", choices=METRICS, default=["total"],
                   help="value(s) to plot; one graph per metric")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--out", default="results")
    return p.parse_args()


def run_all(args, qubit_counts):
    def make_sim(fusion, threads):
        opts = dict(SIM_OPTIONS,
                    fusion_enable=(fusion == "on"),
                    fusion_verbose=True,                  # report fused ops + their qubits
                    fusion_threshold=args.fusion_threshold,
                    fusion_max_qubit=args.fusion_max_qubits)
        if threads > 0:                     # fixed thread count at every qubit size
            opts.update(max_parallel_threads=threads,
                        statevector_parallel_threshold=1)
        if args.max_memory_mb:
            opts["max_memory_mb"] = args.max_memory_mb
        return AerSimulator(**opts)

    if args.dedicated_ram:
        setup_dedicated(parse_size(args.dedicated_ram))
    if psi_stall_us() is None:
        print("note: no memory.pressure for this cgroup; memory stalls are not tracked")
    budget = ram_budget_bytes()
    with open("/proc/self/status") as f:
        rss = next(int(l.split()[1]) * 1024 for l in f if l.startswith("VmRSS"))
    n_fit = int(math.log2(max(budget - rss, AMP_BYTES) // AMP_BYTES))
    swap_max = cgroup_value("memory.swap.max")
    print(f"swap mode: {args.swap_mode} | RAM budget: {budget / 2**30:.2f} GB "
          f"(python already using {rss / 2**20:.0f} MB) -> statevector fits up to n={n_fit}"
          f" | swap allowed for this run: "
          f"{'no (exceeding the budget kills the run)' if swap_max == '0' else 'yes'}")
    print("gates: lowered -> after passes -> after fusion | far = pairs in different pages")

    rows = []
    for spec in args.passes:
        for f in args.fusion:
            for t in args.threads:
                sim = make_sim(f, t)
                label = f"{spec} | {f} | {t if t > 0 else 'auto'}"
                for n in qubit_counts:
                    row = benchmark(n, args.circuit, spec, sim, args.repeats)
                    row["label"] = label
                    row["swap_mode"] = args.swap_mode
                    row["cpus_allowed"] = " ".join(map(str, sorted(os.sched_getaffinity(0))))
                    rows.append(row)
                    print(f"{label:<28} n={n:>2}  "
                          f"gates {row['gates_in']}->{row['gates_passes']}->{row['gates_fused']}  "
                          f"far={row['gates_cross_page']}/{row['gates_fused']}  "
                          f"sim={row['sim']:.4f}s  total={row['total']:.4f}s  "
                          f"sv={row['sv_mb']:.2f}MB  bw={row['bandwidth']:.1f}GB/s\n"
                          f"{'':<34}sim: majflt={row['majflt']:.0f}  "
                          f"stall={row['mem_stall_ms']:.1f}ms  cap hits={row['cap_hits']:.0f}  | "
                          f"system swap in/out={row['swap_in_mb']:.0f}/{row['swap_out_mb']:.0f}MB  "
                          f"nvme read={row['nvme_read_mb']:.0f}MB in {row['nvme_read_ios']:.0f} reqs "
                          f"@ {row['nvme_read_mbps']:.0f}MB/s ({row['sv_over_link']:.2f} SVs)"
                          + ("" if row["clean"] else "  <-- NOT CLEAN")
                          + (f"  <-- Aer used {row['aer_threads']} thread(s), not {t}"
                             if t > 0 and row["aer_threads"] not in (None, t) else ""))
    return rows


def main():
    args = parse_args()
    cpus = sorted(os.sched_getaffinity(0))  # what taskset allows
    too_many = [t for t in args.threads if t > len(cpus)]
    if too_many:
        raise SystemExit(
            f"--threads {max(too_many)} but this process may only run on {len(cpus)} "
            f"CPU(s): {cpus} (taskset?). Aer would silently use {len(cpus)}. "
            f"Widen taskset (e.g. -c 0-3 for one thread per core, -c 0-7 for all) "
            f"or lower --threads.")
    if args.dedicated_ram:
        parse_size(args.dedicated_ram)      # validate before asking for sudo
    if not args.allow_sleep and os.environ.get("SVSIM_SLICE") != "1":
        stay_awake()                        # outer process only; it outlives the run
    if args.dedicated_ram and os.environ.get("SVSIM_SLICE") != "1":
        reexec_in_slice(args.dedicated_ram)
    if args.qubits is not None:
        qubit_counts = [args.qubits]
    else:
        qubit_counts = list(range(args.range[0], args.range[1] + 1, args.step))
    if min(qubit_counts) < 1:
        raise SystemExit("qubit counts must be >= 1")

    for spec in args.passes:                # validate before running anything
        parse_group(spec)

    rows = []
    if args.swap_mode == "nvme":
        set_swap_mode("nvme")
        keep_sudo_alive()
        # make kill / closing the terminal still run the restore in `finally`
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, lambda s, _f: sys.exit(128 + s))
    try:
        rows = run_all(args, qubit_counts)
    finally:
        if args.swap_mode == "nvme":
            set_swap_mode("normal")

    save_csv(rows, f"{args.out}.csv")
    saved = [f"{args.out}.csv"]
    for metric in args.metric:
        path = f"{args.out}_{metric}.png" if len(args.metric) > 1 else f"{args.out}.png"
        title = f"{args.circuit.upper()}: {METRICS[metric].split(' (')[0]} vs qubits"
        plot(rows, metric, title, path)
        saved.append(path)
    dirty = [r for r in rows if not r["clean"]]
    if dirty:
        print(f"WARNING: {len(dirty)} run(s) waited on memory management (major faults, "
              f"memory stalls or the RAM cap), so their timings include slowdowns "
              f"unrelated to the sim: " + ", ".join(f"{r['label']} n={r['n']}" for r in dirty))
    else:
        print("all runs clean: no major page faults, no memory stalls, RAM cap never hit")
    print("saved " + ", ".join(saved))
    if plt.get_backend().lower() != "agg":  # dedicated runs save files only
        plt.show()


if __name__ == "__main__":
    main()
