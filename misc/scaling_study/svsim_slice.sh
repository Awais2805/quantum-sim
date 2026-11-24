#!/usr/bin/env bash
# Run a command with RAM dedicated to it, while the rest of the system swaps as normal.
#
#   sudo ./svsim_slice.sh 2G -- .venv/bin/python qubit_scaling.py ...
#   (qubit_scaling.py --dedicated-ram 2G calls this for you)
#
# The command runs in its own top-level cgroup slice:
#   MemoryMin=SIZE      hard protection: under memory pressure the kernel reclaims or
#                       swaps OTHER processes, never this slice's memory (up to SIZE)
#   MemoryMax=SIZE      the command cannot use more than SIZE
#   MemorySwapMax=0     the command's pages never go to swap; exceeding SIZE kills it
#   oom_score_adj=-900  in a system-wide out-of-memory, other processes are killed first
#
# Why a top-level slice: memory protection only counts if every parent cgroup grants
# it too, and the user session's parents (user.slice ...) all have memory.min=0.
# The unit file lives in /run, so it is gone after a reboot. An empty slice reserves
# nothing (the kernel ignores memory.min for cgroups with no processes).
set -euo pipefail

SLICE=svsim.slice
UNIT=/run/systemd/system/$SLICE

[[ $EUID -eq 0 ]] || { echo "svsim_slice.sh: run with sudo" >&2; exit 1; }
[[ -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]] || { echo "svsim_slice.sh: run via sudo from your own user" >&2; exit 1; }
SIZE=${1:-}
[[ $SIZE =~ ^[0-9]+[KMG]?$ ]] || { echo "usage: sudo $0 SIZE(e.g. 2G) -- command..." >&2; exit 2; }
shift
[[ ${1:-} == "--" ]] && shift
[[ $# -gt 0 ]] || { echo "usage: sudo $0 SIZE -- command..." >&2; exit 2; }

cat > "$UNIT" <<EOF
[Unit]
Description=Dedicated RAM for statevector simulation

[Slice]
MemoryMin=$SIZE
MemoryMax=$SIZE
MemorySwapMax=0
EOF
systemctl daemon-reload

echo -900 > /proc/self/oom_score_adj              # inherited by the command below

# systemd-run puts this process into a scope inside the slice, then setpriv drops back
# to the calling user (uid, gid, groups, clean environment) before running the command.
exec systemd-run --scope --quiet --slice="$SLICE" \
    -p MemoryMin="$SIZE" -p MemoryMax="$SIZE" -p MemorySwapMax=0 \
    -- setpriv --reuid="$SUDO_UID" --regid="$SUDO_GID" --init-groups --reset-env \
    env SVSIM_SLICE=1 MPLBACKEND=Agg "$@"
