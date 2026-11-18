# Source from the task workspace. Packages live in the image, not here.
source /opt/analog-layout/env.sh
export ALB_WORKSPACE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export ALB_TASK_DIR="$ALB_WORKSPACE/task"
export PYTHONPATH="/opt/analog-layout/pdks/sky130/python"
export ALB_MODEL_LIB=/opt/analog-layout/pdks/sky130/sky130A/libs.tech/combined/continuous/sky130.lib.spice
export TMPDIR="$ALB_WORKSPACE/.eda-cache/tmp"
export XDG_CACHE_HOME="$ALB_WORKSPACE/.eda-cache/xdg"
export XDG_CONFIG_HOME="$ALB_WORKSPACE/.eda-cache/config"
export KLAYOUT_HOME="$ALB_WORKSPACE/.eda-cache/klayout"
export MPLCONFIGDIR="$ALB_WORKSPACE/.eda-cache/matplotlib"
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$KLAYOUT_HOME" "$MPLCONFIGDIR" "$ALB_WORKSPACE/submission" "$ALB_WORKSPACE/work"
export ALB_NGSPICE_INIT='set num_threads=1
'
