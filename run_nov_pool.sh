#!/bin/bash
# Keep the November request pool alive.
#
# The pool holds a couple of C3S requests, acts on each as it completes and
# re-asks the ones that are refused.  If it dies the queue stops, so restart
# it - and say so, because a silent stall is the expensive failure here.
cd /workspace/seas5 || exit 1
while true; do
    python3 -u run_nov_queue.py >> logs_nov_queue.log 2>&1
    echo "[$(date -u +%H:%M:%S)] the pool exited - restarting" >> logs_nov_queue.log
    sleep 15
done
