#!/usr/bin/env bash
# TEMPORARY overseer script (not part of the study code). Waits for overnight.sh to finish, retries any
# queue step without a .done marker once (overnight.sh resumes), then runs the extension steps a-d in
# order with the same step()/.done pattern. A step is skipped if it would start after its latest start time.
set -u
cd ~/quantum-sim/qiskit-lab/fusion_study
PY=$HOME/.venv/bin/python
OUT=results/overnight
LOG=$OUT/ext_queue.log
ALL=none,horizontal,vertical,both,diagonal,dp,diag+dp
QB=("$PY" quest_bench.py --control --cost-n 24 --widths 2,3,4 --diag-widths 4,8)

echo "$(date -Is) WAIT  for overnight.sh to finish" | tee -a "$LOG"
until grep -q "QUEUE FINISHED" $OUT/queue.log 2>/dev/null && ! pgrep -f "[o]vernight.sh" >/dev/null \
      && ! pgrep -f "[q]uest_bench|[f]usion_bench" >/dev/null; do sleep 30; done

if [ "$(grep -c FAIL $OUT/queue.log)" -gt 0 ] && [ ! -f $OUT/.overseer_retried ]; then
    touch $OUT/.overseer_retried
    echo "$(date -Is) RETRY overnight.sh once (queue had FAIL lines; finished steps are skipped)" | tee -a "$LOG"
    bash ~/quantum-sim/qiskit-lab/fusion_study/overnight.sh
fi

step() {  # step <name> <latest start HHMM> cmd...
    local name=$1 latest=$2
    shift 2
    if [ -f "$OUT/$name.done" ]; then echo "$(date -Is) SKIP  $name (already done)" | tee -a "$LOG"; return; fi
    if [ $((10#$(date +%H%M))) -gt $((10#$latest)) ]; then
        echo "$(date -Is) SKIP  $name (too late: latest start $latest)" | tee -a "$LOG"; return; fi
    echo "$(date -Is) START $name: $*" | tee -a "$LOG"
    if "$@" > "$OUT/$name.log" 2>&1; then
        touch "$OUT/$name.done"
        echo "$(date -Is) DONE  $name" | tee -a "$LOG"
    else
        echo "$(date -Is) FAIL  $name (exit $?), see $OUT/$name.log" | tee -a "$LOG"
    fi
}

# a) RQC n=26, all modes
step e_rqc_26 0645 "${QB[@]}" --threads 2 --circuit rqc --modes $ALL --min-n 26 --max-n 26 --reps 1 --out $OUT/e_rqc_26.csv
# b) QFT n=29, reduced modes (8 GiB; quest_bench's memory guard may refuse)
step e_qft_29 0650 "$PY" quest_bench.py --threads 2 --control --cost-n 24 --circuit qft \
    --modes none,both,diagonal,dp,diag+dp --widths 2 --diag-widths 8 --min-n 29 --max-n 29 --reps 1 --out $OUT/e_qft_29.csv
# c) more RQC seeds at n=22
for s in 4000 5000 6000; do
    step e_rqc_seed$s 0705 "${QB[@]}" --threads 2 --circuit rqc --seed $s --modes $ALL --min-n 22 --max-n 22 --reps 2 \
        --out $OUT/e_rqc_seed$s.csv
done
# d) QuEST at 1 thread is impossible: quest_runner always creates a multithreaded Qureg, which QuEST rejects
#    when OMP_NUM_THREADS=1 (validation error in createCustomQureg; see q_qft_t1.log). Substitute: Aer at 1 thread
#    on the same circuits as a_qft_16_26 / a_rqc_16_25 (2 threads), at n=24, for Aer's thread scaling.
AB1=("$PY" fusion_bench.py --threads 1 --control --widths 2,3,4 --aer-fusion-ref)
step e_aer_qft_t1_24 0705 "${AB1[@]}" --circuit qft --min-n 24 --max-n 24 --reps 2 --out $OUT/e_aer_qft_t1_24.csv
now=$((10#$(date +%H%M)))
if [ $now -le 652 ]; then rn=24; else rn=23; fi   # est. RQC n=24: ~20 min, n=23: ~9 min at 1 thread
step e_aer_rqc_t1_$rn 0703 "${AB1[@]}" --circuit rqc --basis quest --min-n $rn --max-n $rn --reps 2 --out $OUT/e_aer_rqc_t1_$rn.csv

echo "$(date -Is) EXTENSIONS FINISHED" | tee -a "$LOG"
