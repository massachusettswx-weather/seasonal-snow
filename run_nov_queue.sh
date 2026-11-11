#!/bin/bash
# Keep the queue runner alive.
#
# The runner walks the C3S November steps one request at a time.  If it dies
# for any reason the queue simply stops, and with the CDS taking hours to
# serve a request that silence is expensive - so restart it and say so.
cd /workspace/seas5 || exit 1
while true; do
    python3 -u run_nov_queue.py >> logs_nov_queue.log 2>&1
    echo "[$(date -u +%H:%M:%S)] the runner exited - restarting" >> logs_nov_queue.log
    sleep 20
done
