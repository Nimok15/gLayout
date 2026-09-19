#!/bin/bash
#
# Usage: run_pex.sh <layout.gds> <top_cell_name> <magicrc_path> [extresist|noextresist]
#

set -u

GDS_FILE="${1:?usage: run_pex.sh <gds> <cell> <magicrc> [extresist|noextresist]}"
LAYOUT_CELL="${2:?missing top cell name}"
MAGICRC="${3:?missing magicrc path}"
MODE="${4:-extresist}"

if [ ! -f "$MAGICRC" ]; then
    echo "run_pex.sh: magicrc not found: $MAGICRC" >&2
    exit 2
fi
if [ ! -f "$GDS_FILE" ]; then
    echo "run_pex.sh: gds not found: $GDS_FILE" >&2
    exit 2
fi

OUT="${LAYOUT_CELL}_pex.spice"
rm -f "$OUT"


if [ "$MODE" = "noextresist" ]; then
magic -rcfile "$MAGICRC" -noconsole -dnull <<EOF
gds read $GDS_FILE
flatten $LAYOUT_CELL
load $LAYOUT_CELL
select top cell
extract do local
extract all
ext2sim labels on
ext2sim
ext2spice lvs
ext2spice cthresh 0
ext2spice rthresh 0
ext2spice -y 3 -o $OUT
quit -noprompt
EOF
else
magic -rcfile "$MAGICRC" -noconsole -dnull <<EOF
gds read $GDS_FILE
flatten $LAYOUT_CELL
load $LAYOUT_CELL
select top cell
extract do local
extract all
ext2sim labels on
ext2sim
extresist tolerance 10
extresist
ext2spice lvs
ext2spice cthresh 0
ext2spice rthresh 0
ext2spice extresist on
ext2spice -y 3 -o $OUT
quit -noprompt
EOF
fi

if [ ! -s "$OUT" ]; then
    echo "run_pex.sh: extraction produced no output netlist" >&2
    exit 1
fi

NDEV=$(grep -c -E '^[[:space:]]*[XxMmCcRrDdQq][^[:space:]]*[[:space:]]' "$OUT" || true)
if [ "${NDEV:-0}" -eq 0 ]; then
    echo "run_pex.sh: netlist has no devices -- is '$LAYOUT_CELL' the top cell in $GDS_FILE?" >&2
    exit 3
fi
echo "run_pex.sh: ok, $NDEV device lines" >&2
exit 0
