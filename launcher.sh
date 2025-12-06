#!/bin/bash

# ---------------------------------------
#  Auto-detect location of this script
# ---------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/show_eposters.py"

# ---------------------------------------
#  Hardcoded environment variables
#  (EDIT THESE AS YOU WANT)
# ---------------------------------------
export POSTER_TOKEN="API_TOEKN"
export CACHE_REFRESH=60        # seconds between API polls
export DISPLAY_TIME=5          # seconds to show each poster

# ---------------------------------------
#  Log information
# ---------------------------------------
echo "Running ePoster viewer:"
echo "  POSTER_TOKEN: [HIDDEN]"
echo "  CACHE_REFRESH: $CACHE_REFRESH"
echo "  DISPLAY_TIME: $DISPLAY_TIME"
echo "  Script path: $PY_SCRIPT"
echo ""

# ---------------------------------------
#  Run the Python script
# ---------------------------------------
/usr/bin/python3 "$PY_SCRIPT"
