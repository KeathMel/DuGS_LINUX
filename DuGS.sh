#!/bin/bash
# DuGS launcher — starts the API server and the GUI together.
#
# Double-click this (or the DuGS.desktop shortcut) and everything comes up.
# Closing the GUI shuts the API down too, so nothing is left running.

# always work from the folder this script lives in, no matter where it's
# launched from (double-clicking often starts you in the wrong directory)
cd "$(dirname "$(readlink -f "$0")")" || exit 1

# kill any api.py left over from a previous run, so the port is free
pkill -f "python3 api.py" 2>/dev/null
sleep 0.3

# stale bytecode is the usual reason changes "don't show up"
find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null

# start the API in the background, log where we can find it
python3 api.py > /tmp/dugs-api.log 2>&1 &
API_PID=$!

# whatever happens (normal exit, crash, Ctrl+C), take the API down with us
cleanup() {
    kill "$API_PID" 2>/dev/null
    wait "$API_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

# give the server a moment to bind its port before the GUI tries to reach it
sleep 1.5

# if the API died immediately, say so instead of showing an empty palette
if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "API failed to start. Log:"
    cat /tmp/dugs-api.log
    read -rp "Press Enter to close..."
    exit 1
fi

# run the GUI in the foreground; when it closes, the trap kills the API
python3 ui.py
