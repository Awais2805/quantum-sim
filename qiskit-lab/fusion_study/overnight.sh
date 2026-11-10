#!/usr/bin/env bash
# Overnight experiment queue for the qbench VM (2 vCPU, ~15 GB). Run inside tmux from anywhere:
#     tmux new -d -s overnight 'bash ~/quantum-sim/qiskit-lab/fusion_study/overnight.sh'
# Steps run in priority order. Each is independent: a failure is logged and the queue moves on.
# A finished step leaves results/overnight/<step>.done, so re-running the script resumes where
# it stopped. Progress: results/overnight/queue.log; per-step output: results/overnight/<step>.log.
set -u
cd "$(dirname "$0")"
PY=${PY:-$HOME/.venv/bin/python}
OUT=results/overnight
T=${THREADS:-2}
mkdir -p "$OUT"
LOG=$OUT/queue.log

step() {
    local name=$1
    shift
    if [ -f "$OUT/$name.done" ]; then
        echo "$(date -Is) SKIP  $name (already done)" | tee -a "$LOG"
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

ALL=none,horizontal,vertical,both,diagonal,dp,diag+dp
GREEDY=none,horizontal,vertical,both,diagonal
QB=("$PY" quest_bench.py --threads "$T" --control --cost-n 24 --widths 2,3,4 --diag-widths 4,8)
AB=("$PY" fusion_bench.py --threads "$T" --control --widths 2,3,4 --aer-fusion-ref)

# P1-P2: QuEST, every fusion mode (greedy H/V/B, diagonal, Aer's fuser port, measured-cost DP)
step q_qft_16_23 "${QB[@]}" --circuit qft --modes $ALL --min-n 16 --max-n 23 --reps 3 --out $OUT/q_qft_16_23.csv
step q_rqc_16_22 "${QB[@]}" --circuit rqc --modes $ALL --min-n 16 --max-n 22 --reps 3 --out $OUT/q_rqc_16_22.csv
step q_qft_24_26 "${QB[@]}" --circuit qft --modes $ALL --min-n 24 --max-n 26 --reps 2 --out $OUT/q_qft_24_26.csv
step q_rqc_23_25 "${QB[@]}" --circuit rqc --modes $ALL --min-n 23 --max-n 25 --reps 2 --out $OUT/q_rqc_23_25.csv

# P3: QuEST, greedy modes gated by the QuEST-measured cost model
step q_qft_cost "${QB[@]}" --cost-model --circuit qft --modes $GREEDY --min-n 16 --max-n 26 --reps 2 --out $OUT/q_qft_cost.csv
step q_rqc_cost "${QB[@]}" --cost-model --circuit rqc --modes $GREEDY --min-n 16 --max-n 25 --reps 2 --out $OUT/q_rqc_cost.csv

# P4: QuEST, larger QFT with a reduced mode set
step q_qft_27_28 "$PY" quest_bench.py --threads "$T" --control --cost-n 24 --circuit qft \
    --modes none,both,diagonal,dp,diag+dp --widths 2 --diag-widths 8 --min-n 27 --max-n 28 --reps 1 \
    --out $OUT/q_qft_27_28.csv

# P5: Aer on the SAME circuits (rqc in QuEST's gate set), for an Aer-vs-QuEST comparison
step a_qft_16_26 "${AB[@]}" --circuit qft --min-n 16 --max-n 26 --reps 2 --out $OUT/a_qft_16_26.csv
step a_rqc_16_25 "${AB[@]}" --circuit rqc --basis quest --min-n 16 --max-n 25 --reps 2 --out $OUT/a_rqc_16_25.csv

# P6: QuEST thread scaling at n=24 (1 thread vs the 2-thread runs above)
for c in qft rqc; do
    step q_${c}_t1 "$PY" quest_bench.py --threads 1 --control --cost-n 24 --circuit $c \
        --modes none,both,diagonal,diag+dp --widths 2,4 --diag-widths 8 --min-n 24 --max-n 24 --reps 2 \
        --out $OUT/q_${c}_t1.csv
done

# P7: RQC robustness across random seeds at n=22 (all modes)
for s in 1000 2000 3000; do
    step q_rqc_seed$s "${QB[@]}" --circuit rqc --seed $s --modes $ALL --min-n 22 --max-n 22 --reps 2 \
        --out $OUT/q_rqc_seed$s.csv
done

echo "$(date -Is) QUEUE FINISHED" | tee -a "$LOG"
