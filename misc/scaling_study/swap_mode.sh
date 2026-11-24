#!/usr/bin/env bash
# Switch swap between normal use and an NVMe-first experiment mode.
#
#   sudo ./swap_mode.sh nvme     # NVMe swap file becomes top priority, RAM maximised
#   sudo ./swap_mode.sh normal   # restore the settings saved when nvme mode started
#   ./swap_mode.sh status        # show current swap devices and mode (no sudo needed)
#
# nvme mode:
#   - re-enables SWAPFILE at the highest priority, so new swap-outs go to the NVMe SSD
#     before zram (zram stays on as overflow; its existing contents are left alone)
#   - lowers vm.swappiness so the kernel keeps pages in RAM until it really runs out
#   - drops the page cache so as much RAM as possible is free before the run
set -euo pipefail

SWAPFILE=/swap.img
STATE=/run/qiskit-swap-mode.state      # tmpfs: cleared on reboot, like the settings themselves
EXP_SWAPPINESS=10
TOP_PRIORITY=32767

prio_of() { awk -v f="$1" '$1 == f {print $5}' /proc/swaps; }
need_root() { [[ $EUID -eq 0 ]] || { echo "swap_mode.sh: run with sudo" >&2; exit 1; }; }

case "${1:-}" in
  nvme)
    need_root
    if [[ -f $STATE ]]; then echo "swap_mode: already in nvme mode"; exit 0; fi
    echo "swappiness=$(cat /proc/sys/vm/swappiness)" >  "$STATE"
    echo "prio=$(prio_of "$SWAPFILE")"              >> "$STATE"
    swapoff "$SWAPFILE" 2>/dev/null || true          # moves any pages in it back first
    swapon -p "$TOP_PRIORITY" "$SWAPFILE"
    sysctl -q vm.swappiness="$EXP_SWAPPINESS"
    sync; echo 3 > /proc/sys/vm/drop_caches
    echo "swap_mode: nvme ($SWAPFILE priority $TOP_PRIORITY, swappiness $EXP_SWAPPINESS)"
    ;;
  normal)
    need_root
    if [[ ! -f $STATE ]]; then echo "swap_mode: already normal"; exit 0; fi
    # shellcheck disable=SC1090
    source "$STATE"
    swapoff "$SWAPFILE"                              # pages in it move back to RAM/zram
    if [[ -n ${prio:-} ]]; then swapon -p "$prio" "$SWAPFILE"; fi
    sysctl -q vm.swappiness="$swappiness"
    rm -f "$STATE"
    echo "swap_mode: normal (priority ${prio:-off}, swappiness $swappiness)"
    ;;
  status)
    cat /proc/swaps
    echo "swappiness: $(cat /proc/sys/vm/swappiness)"
    [[ -f $STATE ]] && echo "mode: nvme" || echo "mode: normal"
    ;;
  *)
    echo "usage: sudo $0 nvme|normal   or   $0 status" >&2
    exit 2
    ;;
esac
