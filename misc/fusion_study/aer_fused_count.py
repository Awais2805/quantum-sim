#!/usr/bin/env python3
"""Count the gates Aer really applies when its built-in fusion is on.

fusion_bench.py's 'aer' row stores the *input* gate count, because Aer fuses internally.
This runs the same circuit once with the same simulator settings plus fusion_verbose=True and
records Aer's fused op list, so 'Aer fusion on' can be shown with gates applied and time per gate.

    python aer_fused_count.py --circuit rqc --n 26 --threads 2 --out results/x/rqc_aer_fused_ops.json
"""

import argparse
import collections
import json
from pathlib import Path

import fusion_bench as fb
from quest_ops import QUEST_BASIS


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--circuit", choices=("qft", "rqc"), required=True)
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--depth", type=int, default=0)
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--threads", type=int, default=0)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()

    # same circuit as quest_bench.py and fusion_bench.py --basis quest
    qc = fb.build_circuit(a.circuit, a.n, a.depth, a.seed, basis=QUEST_BASIS)
    sim = fb.make_sim(a.threads, aer_fusion=True)  # identical to fusion_bench's 'aer' reference
    sim.set_options(fusion_verbose=True)
    c = qc.copy()
    c.save_amplitudes([0])
    res = sim.run(c, shots=1).result()
    md = res.results[0].metadata.get("fusion", {})
    if not md.get("applied"):
        raise SystemExit(f"Aer did not apply fusion: {md}")
    ops = [o for o in md["output_ops"] if not o["name"].startswith("save_")]
    out = {
        "circuit": a.circuit, "n": a.n, "seed": a.seed, "input_ops": len(qc.data),
        "fused_ops": len(ops),
        "by_name": dict(collections.Counter(o["name"] for o in ops)),
        "by_width": {str(w): c for w, c in sorted(collections.Counter(len(o["qubits"]) for o in ops).items())},
        "time_taken_s": res.results[0].time_taken,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=1))
    print(json.dumps(out))


if __name__ == "__main__":
    main()
