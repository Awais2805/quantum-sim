#!/usr/bin/env bash
# Meeting comparison: QFT and a random circuit (RQC) at one size, on one machine, in one sitting.
#   Aer:   no fusion | Aer built-in fusion | Qiskit horizontal / vertical fusion (greedy, cost model)
#   QuEST: no fusion | Qiskit horizontal / vertical fusion (greedy, cost model) | measured-cost grouping
# Horizontal / vertical are swept over max fused width k (WIDTHS). Cost tables are measured at N.
# Defaults: N=24, WIDTHS=2,3,4 -> ~20 min on the qbench VM (2 vCPU). Run inside tmux:
#     tmux new -d -s meeting 'bash ~/quantum-sim/qiskit-lab/fusion_study/meeting_run.sh'
# Resumable: a finished step leaves <step>.done in $OUT. Then, on any machine with the results:
#     python plot_meeting.py results/meeting_n24
set -u
cd "$(dirname "$0")"
PY=${PY:-$HOME/.venv/bin/python}
N=${N:-24}
WIDTHS=${WIDTHS:-2,3,4}
T=${THREADS:-2}
OUT=${OUT:-results/meeting_n$N}
QFT_REPS=${QFT_REPS:-3}
RQC_REPS=${RQC_REPS:-1}
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
    echo "threads: $T   n: $N   widths: $WIDTHS   reps: qft $QFT_REPS, rqc $RQC_REPS"
    md5sum fusion_bench.py quest_bench.py quest_ops.py dp_fusion.py quest_runner.cpp aer_fused_count.py meeting_run.sh
} > "$OUT/ENV.txt" 2>&1

COMMON=(--min-n "$N" --max-n "$N" --threads "$T" --widths "$WIDTHS")
for c in qft rqc; do
    reps=$QFT_REPS; [ "$c" = rqc ] && reps=$RQC_REPS
    # --control re-times the unfused circuit as a noise check; --basis quest = the same circuits as QuEST
    step ${c}_aer_greedy "$PY" fusion_bench.py --circuit $c --basis quest "${COMMON[@]}" --reps $reps \
        --modes none,horizontal,vertical --aer-fusion-ref --control --out "$OUT/${c}_aer_greedy.csv"
    step ${c}_aer_cost "$PY" fusion_bench.py --circuit $c --basis quest "${COMMON[@]}" --reps $reps \
        --modes horizontal,vertical --cost-model --cost-n "$N" --out "$OUT/${c}_aer_cost.csv"
    step ${c}_aer_ops "$PY" aer_fused_count.py --circuit $c --n "$N" --threads "$T" \
        --out "$OUT/${c}_aer_fused_ops.json"
    step ${c}_quest_greedy "$PY" quest_bench.py --circuit $c "${COMMON[@]}" --reps $reps \
        --modes none,horizontal,vertical,dp --dp-costs measured --cost-n "$N" --control \
        --out "$OUT/${c}_quest_greedy.csv"
    step ${c}_quest_cost "$PY" quest_bench.py --circuit $c "${COMMON[@]}" --reps $reps \
        --modes horizontal,vertical --cost-model --cost-n "$N" --out "$OUT/${c}_quest_cost.csv"
done
echo "$(date -Is) FINISHED" | tee -a "$LOG"
