#!/usr/bin/env bash
# 26-qubit comparison, QFT and random circuit (RQC), on one machine in one sitting:
#   Aer: fusion off | Aer built-in fusion | Qiskit horizontal / vertical fusion (greedy, cost model)
#   QuEST: no fusion | Qiskit horizontal / vertical fusion (greedy, cost model) | measured-cost grouping
# Max fused width k = 2 (the best greedy width; wider dense blocks were slower in every overnight run).
# ~25 min on the qbench VM (2 vCPU). Run inside tmux:
#     tmux new -d -s meeting 'bash ~/quantum-sim/qiskit-lab/fusion_study/meeting_n26.sh'
# Resumable: a finished step leaves <step>.done in $OUT. Then on the laptop:
#     python plot_meeting.py results/meeting_n26
set -u
cd "$(dirname "$0")"
PY=${PY:-$HOME/.venv/bin/python}
OUT=${OUT:-results/meeting_n26}
T=${THREADS:-2}
N=${N:-26}
mkdir -p "$OUT"
LOG=$OUT/queue.log

step() {
    local name=$1
    shift
    if [ -f "$OUT/$name.done" ]; then
        echo "$(date -Is) SKIP  $name" | tee -a "$LOG"
        return
    fi
    echo "$(date -Is) START $name: $*" | tee -a "$LOG"
    if "$@" > "$OUT/$name.log" 2>&1; then
        touch "$OUT/$name.done"
        echo "$(date -Is) DONE  $name" | tee -a "$LOG"
    else
        echo "$(date -Is) FAIL  $name (exit $?), see $OUT/$name.log" | tee -a "$LOG"
    fi
}

{   # environment record for reproducibility
    echo "date: $(date -Is)"
    echo "host: $(hostname)"
    lscpu | grep -E "Model name|^CPU\(s\)|Thread|L3"
    free -g | head -2
    "$PY" -c "import sys, qiskit, qiskit_aer; print('python', sys.version.split()[0]); print('qiskit', qiskit.__version__); print('qiskit-aer', qiskit_aer.__version__)"
    echo "threads: $T   n: $N"
    md5sum fusion_bench.py quest_bench.py quest_ops.py dp_fusion.py quest_runner.cpp aer_fused_count.py meeting_n26.sh
} > "$OUT/ENV.txt" 2>&1

COMMON=(--min-n "$N" --max-n "$N" --threads "$T" --widths 2)
for c in qft rqc; do
    reps=2; [ "$c" = rqc ] && reps=1          # rqc at 26 qubits is ~5x slower per run
    ctrl=(); [ "$c" = qft ] && ctrl=(--control)  # identical-circuit rerun = noise check
    step ${c}_aer_greedy "$PY" fusion_bench.py --circuit $c --basis quest "${COMMON[@]}" --reps $reps \
        --modes none,horizontal,vertical --aer-fusion-ref "${ctrl[@]}" --out "$OUT/${c}_aer_greedy.csv"
    step ${c}_aer_cost "$PY" fusion_bench.py --circuit $c --basis quest "${COMMON[@]}" --reps $reps \
        --modes horizontal,vertical --cost-model --out "$OUT/${c}_aer_cost.csv"
    step ${c}_aer_ops "$PY" aer_fused_count.py --circuit $c --n "$N" --threads "$T" \
        --out "$OUT/${c}_aer_fused_ops.json"
    step ${c}_quest_greedy "$PY" quest_bench.py --circuit $c "${COMMON[@]}" --reps $reps \
        --modes none,horizontal,vertical,dp --dp-costs measured --cost-n 24 "${ctrl[@]}" \
        --out "$OUT/${c}_quest_greedy.csv"
    step ${c}_quest_cost "$PY" quest_bench.py --circuit $c "${COMMON[@]}" --reps $reps \
        --modes horizontal,vertical --cost-model --cost-n 24 --out "$OUT/${c}_quest_cost.csv"
done
echo "$(date -Is) FINISHED" | tee -a "$LOG"
