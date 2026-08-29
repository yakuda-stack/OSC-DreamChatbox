#!/usr/bin/env bash
# OSC-DreamChatbox - was meldet diese Maschine an CPU-Watt?
echo "=== hwmon: power- UND energy-Attribute ==="
for h in /sys/class/hwmon/hwmon*; do
  n=$(cat "$h/name" 2>/dev/null)
  files=$(ls "$h" 2>/dev/null | grep -E '^(power1_average|power1_input|energy[0-9]+_input)$' | tr '\n' ' ')
  [ -n "$files" ] && echo "$h  name=$n  ->  $files"
done
echo
echo "=== energy-Labels (welcher Zaehler ist der Socket?) ==="
for h in /sys/class/hwmon/hwmon*; do
  for l in "$h"/energy*_label; do
    [ -e "$l" ] || continue
    echo "  $(basename $l) = $(cat $l)   [$(cat $h/name 2>/dev/null)]"
  done
done
echo
echo "=== geladene Module ==="
lsmod | grep -E 'zenpower|zenergy|amd_energy|k10temp' || echo "keins davon geladen"
echo
echo "=== RAPL ==="
ls /sys/class/powercap/ 2>/dev/null | head
cat /sys/class/powercap/intel-rapl:0/energy_uj 2>&1 | head -1
echo
echo "=== GPU-Karten ==="
for c in /sys/class/drm/card[0-9]/device; do
  [ -e "$c/gpu_busy_percent" ] || continue
  echo "$c  vram=$(cat $c/mem_info_vram_total 2>/dev/null)"
  for h in "$c"/hwmon/hwmon*; do
    [ -e "$h" ] && echo "    $h name=$(cat $h/name 2>/dev/null) power1_average=$(cat $h/power1_average 2>/dev/null)"
  done
done
