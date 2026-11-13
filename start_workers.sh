#!/bin/bash
# Start the background workers, and put the Python toolchain back if the
# sandbox has been rebuilt.
#
# The sandbox rebuilds every hour or two and wipes the installed packages
# and every background process, so this is the first thing to run after
# one of those.  The published site is not affected - it lives on GitHub.
cd /workspace/seas5 || exit 1

# The toolchain.  It goes into the USER site, which lives under the
# workspace (/workspace/.home) and therefore survives the rebuild - the
# system site does not.  The user site is only on sys.path once the
# directory exists, so it is created first.
SITE="$HOME/.local/lib/python3.11/site-packages"
mkdir -p "$SITE"
if ! python3 -c "import requests, eccodes" >/dev/null 2>&1; then
    echo "reinstalling the python packages into $SITE"
    pip install --break-system-packages -q --index-url https://pypi.org/simple \
        --target "$SITE" requests eccodes numcodecs >/dev/null 2>&1
fi
python3 -c "import requests, eccodes" \
    || { echo "the toolchain did not come back"; exit 1; }

# the request pool
# pgrep also matches the zombies of an earlier run, so the check looks at
# the process state and ignores the dead ones
running() { ps -eo stat,cmd | grep -v "^Z" | grep -F "$1" | grep -v grep >/dev/null 2>&1; }

if ! running "run_nov_queue.py"; then
    echo "starting the request pool"
    setsid nohup bash run_nov_pool.sh >/dev/null 2>&1 </dev/null &
    sleep 3
fi

# the polar-cap puller: the daily polar-cap geopotential for the seasonal
# systems, out to each model's own end of run
if ! running "fetch_polar_models.py"; then
    echo "starting the polar-cap puller"
    setsid nohup python3 -u fetch_polar_models.py \
        >>data/polar_models.log 2>&1 </dev/null &
    sleep 3
fi

# the publisher
if ! running "auto_publish.sh"; then
    echo "starting the publisher"
    setsid nohup bash auto_publish.sh "${TOKEN:-}" \
        >logs_auto_publish_watch.log 2>&1 </dev/null &
    sleep 3
fi

echo "the pool:    $(ps -eo cmd | grep -F 'run_nov_queue.py' | grep -vc grep) process(es)"
echo "the publisher: $(ps -eo cmd | grep -F 'auto_publish.sh' | grep -vc grep) process(es)"
