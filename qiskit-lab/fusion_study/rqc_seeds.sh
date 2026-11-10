#!/usr/bin/env bash
# The random-circuit (RQC) part of meeting_run.sh, repeated over several random circuits (seeds),
# so results can be averaged across circuits instead of resting on one. Same steps and settings:
#   Aer:   no fusion | Aer built-in fusion | horizontal / vertical (greedy, cost model)
#   QuEST: no fusion | horizontal / vertical (greedy, cost model) | measured-cost grouping (dp)
# Every seed uses the SAME cost tables (copied from $COSTS_FROM if given), so circuits are judged
# by identical costs. Size n uses circuit seed (SEED + n), as in fusion_bench/quest_bench.
#     tmux new -d -s seeds 'SEEDS="1000 2000 3000" bash fusion_study/rqc_seeds.sh'
#     python fusion_study/seed_summary.py results/rqc_seeds_n24 [results/meeting_n24]
# Resumable: a finished step leaves <step>.done in $OUT.
set -u
cd "$(dirname "$0")"
PY=${PY:-$HOME/.venv/bin/python}
N=${N:-24}
WIDTHS=${WIDTHS:-2,3,4}
T=${THREADS:-2}
REPS=${REPS:-1}
SEEDS=${SEEDS:-"1000 2000 3000 4000 5000 6000"}
OUT=${OUT:-results/rqc_seeds_n$N}
COSTS_FROM=${COSTS_FROM:-results/meeting_n$N}
mkdir -p "$OUT"
LOG=$OUT/queue.log

if [ -d "$COSTS_FROM" ]; then  # reuse the meeting run's cost tables (same host, threads, n)
    for f in "$COSTS_FROM"/cost_table_v2_*_t${T}_n${N}.json; do
        [ -f "$f" ] && [ ! -f "$OUT/$(basename "$f")" ] && cp "$f" "$OUT/"
    done
fi

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

{
    echo "date: $(date -Is)"
    echo "host: $(hostname)"
    lscpu | grep -E "Model name|^CPU\(s\)|Thread|L3"
    "$PY" -c "import qiskit, qiskit_aer; print('qiskit', qiskit.__version__, 'qiskit-aer', qiskit_aer.__version__)"
    echo "threads: $T   n: $N   widths: $WIDTHS   reps: $REPS   seeds: $SEEDS   costs from: $COSTS_FROM"
    md5sum fusion_bench.py quest_bench.py quest_ops.py dp_fusion.py quest_runner.cpp rqc_seeds.sh
} > "$OUT/ENV.txt" 2>&1

COMMON=(--circuit rqc --min-n "$N" --max-n "$N" --threads "$T" --widths "$WIDTHS" --reps "$REPS")
for s in $SEEDS; do
    step seed${s}_aer_greedy "$PY" fusion_bench.py "${COMMON[@]}" --seed "$s" --basis quest \
        --modes none,horizontal,vertical --aer-fusion-ref --control --out "$OUT/rqc_seed${s}_aer_greedy.csv"
    step seed${s}_aer_cost "$PY" fusion_bench.py "${COMMON[@]}" --seed "$s" --basis quest \
        --modes horizontal,vertical --cost-model --cost-n "$N" --out "$OUT/rqc_seed${s}_aer_cost.csv"
    step seed${s}_quest_greedy "$PY" quest_bench.py "${COMMON[@]}" --seed "$s" \
        --modes none,horizontal,vertical,dp --dp-costs measured --cost-n "$N" --control \
        --out "$OUT/rqc_seed${s}_quest_greedy.csv"
    step seed${s}_quest_cost "$PY" quest_bench.py "${COMMON[@]}" --seed "$s" \
        --modes horizontal,vertical --cost-model --cost-n "$N" --out "$OUT/rqc_seed${s}_quest_cost.csv"
done
echo "$(date -Is) FINISHED" | tee -a "$LOG"
