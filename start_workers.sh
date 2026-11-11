#!/bin/bash
# Start the background workers, and put the Python toolchain back if the
# sandbox has been rebuilt.
#
# The sandbox rebuilds every hour or two and wipes the installed packages
# and every background process, so this is the first thing to run after
# one of those.  The published site is not affected - it lives on GitHub.
cd /workspace/seas5 || exit 1

# the toolchain
if ! python3 -c "import requests, eccodes, xarray, h5netcdf, zarr, s3fs, numpy" \
        >/dev/null 2>&1; then
    echo "reinstalling the python packages"
    pip install --break-system-packages -q -i https://pypi.org/simple \
        requests eccodes numcodecs cdsapi zarr xarray h5netcdf fsspec s3fs \
        h5py >/dev/null 2>&1
fi
python3 -c "import requests, eccodes, xarray, h5netcdf, zarr, s3fs, numpy" \
    || { echo "the toolchain did not come back"; exit 1; }

# the request pool
if ! pgrep -f "run_nov_queue.py" >/dev/null 2>&1; then
    echo "starting the request pool"
    setsid nohup bash run_nov_pool.sh >/dev/null 2>&1 </dev/null &
    sleep 3
fi

# the publisher
if ! pgrep -f "auto_publish.sh" >/dev/null 2>&1; then
    echo "starting the publisher"
    setsid nohup bash auto_publish.sh "${TOKEN:-}" \
        >logs_auto_publish_watch.log 2>&1 </dev/null &
    sleep 3
fi

echo "the pool:    $(pgrep -fc 'run_nov_queue.py') process(es)"
echo "the publisher: $(pgrep -fc 'auto_publish.sh') process(es)"
