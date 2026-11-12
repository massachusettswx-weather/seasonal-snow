"""Wait for the UKMO probe job and survey what the archive really returned.

The probe asked the archive for three days of the UKMO's sub-daily 10 hPa
wind and it sat in the queue for hours.  The job itself stays valid after
the script that submitted it has gone, so this watches the job and, when
it finishes, downloads the GRIB and writes down what it contains: how
many messages, how many distinct member numbers, how many distinct
perturbation numbers, which levels, and how many members there are at
each valid time.

That is the answer to the question the daily wind has been waiting on:
does the product serve the whole ensemble (and the decoder was reading
the member key wrong), or does it serve two members out of sixty (and
the request has to be split shorter)?

    python3 probe_watch.py [job-id]
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

JOB = sys.argv[1] if len(sys.argv) > 1 else \
    "d9fd789b-2001-47c5-a7d7-a1197565e356"
OUT = os.path.join(HERE, "data", "probe_ukmo-gloseas6.grib")
REPORT = os.path.join(HERE, "data", "probe_report.txt")
LOG = os.path.join(HERE, "logs_probe_watch.log")


def log(msg):
    with open(LOG, "a") as f:
        f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    print(msg, flush=True)


def main():
    import cds_direct
    c = cds_direct.CDSDirect()
    log("watching the job %s" % JOB)
    waited = 0
    while True:
        try:
            st = c.job_status(JOB)
        except Exception as e:
            log("the status could not be read (%s)" % str(e)[:100])
            st = None
        if st in ("completed", "successful"):
            log("the job is complete - downloading")
            try:
                c.download_job(JOB, OUT)
            except Exception as e:
                log("the download failed (%s)" % str(e)[:200])
                return 1
            from probe_daily_u10 import survey
            nmsg, nums, pns, levels, valids, per_valid = survey(OUT)
            lines = [
                "the job %s" % JOB,
                "messages: %d" % nmsg,
                "distinct number: %d (%s%s)"
                % (len(nums), nums[:12], " ..." if len(nums) > 12 else ""),
                "distinct perturbationNumber: %d (%s%s)"
                % (len(pns), pns[:12], " ..." if len(pns) > 12 else ""),
                "levels: %s" % levels,
                "valid times: %d" % len(valids),
                "members per valid time: %s"
                % sorted({len(v) for v in per_valid.values()}),
            ]
            txt = "\n".join(lines)
            open(REPORT, "w").write(txt + "\n")
            log(txt)
            return 0
        if st in ("failed", "error"):
            log("the job failed: %s" % st)
            return 2
        waited += 5
        log("the job is still %s (%d min)" % (st or "unknown", waited))
        time.sleep(300)


if __name__ == "__main__":
    sys.exit(main())
