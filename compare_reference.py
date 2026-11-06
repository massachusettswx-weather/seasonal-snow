"""Read the published reference figure's ECMWF Mean (black) line and compare it
with what our pipeline produces for the SAME run (init 1 Oct 2026).

Calibration is taken from the figure itself:
  * grid colour (240,240,240); the 80 m/s line is at row 45 and the -20 m/s
    line at row 557  -> 5.12 px per m/s
  * the vertical grid lines are the month ticks (01 Oct 2026 -> 01 May 2027)
"""
import json
import numpy as np
from PIL import Image

REF = "/workspace/attachments/0bb5177c122cab74/image.png"
GRID = 240
Y_TOP, Y_VAL_TOP = 45.0, 80.0
Y_BOT, Y_VAL_BOT = 557.0, -20.0
PX_PER_MS = (Y_BOT - Y_TOP) / (Y_VAL_TOP - Y_VAL_BOT)
MONTHS = ["01 Oct", "01 Nov", "01 Dec", "01 Jan", "01 Feb", "01 Mar", "01 Apr", "01 May"]


def main():
    im = np.array(Image.open(REF).convert("RGB")).astype(int)
    h, w, _ = im.shape
    g = (np.abs(im[:, :, 0] - GRID) < 7) & (np.abs(im[:, :, 1] - GRID) < 7) \
        & (np.abs(im[:, :, 2] - GRID) < 7)

    # --- vertical grid lines -> month tick columns -----------------------
    profc = g.sum(axis=0)
    cols = [i for i, v in enumerate(profc) if v > 100]
    vgrp, cur = [], [cols[0]]
    for x in cols[1:]:
        if x - cur[-1] <= 3:
            cur.append(x)
        else:
            vgrp.append(sum(cur) / len(cur)); cur = [x]
    vgrp.append(sum(cur) / len(cur))
    print("vertical grid columns:", [round(x, 1) for x in vgrp])
    # month lattice: the rightmost column is 01 May 2027; spacing is uniform
    x_last = max(vgrp)
    step = 178.0          # 1252 px / 7 months
    ticks = {i: x_last - (len(MONTHS) - 1 - i) * step for i in range(len(MONTHS))}
    for i in range(len(MONTHS)):
        print("  %-7s px %7.1f" % (MONTHS[i], ticks[i]))

    # --- the black trace -------------------------------------------------
    black = (im[:, :, 0] < 80) & (im[:, :, 1] < 80) & (im[:, :, 2] < 80)
    black[:int(h * 0.45), :int(w * 0.27)] = False   # legend box
    black[int(h * 0.93):, :] = False               # x tick labels
    black[:, :int(w * 0.045)] = False               # y tick labels

    print("\nreference (published) ECMWF Mean read at each month tick:")
    out = {}
    for i, mo in enumerate(MONTHS):
        if i not in ticks:
            continue
        xv = ticks[i]
        seg = black[:, max(0, int(xv) - 2):int(xv) + 3]
        ys = np.where(seg.any(axis=1))[0]
        ys = ys[(ys > Y_TOP - 20) & (ys < Y_BOT + 20)]
        if len(ys) == 0:
            continue
        # take the darkest contiguous run near the trace
        val = Y_VAL_TOP - (ys.mean() - Y_TOP) / PX_PER_MS
        out[mo] = round(float(val), 2)
        print("  %-7s -> %6.2f m/s" % (mo, val))
    print()
    print(json.dumps(out))


if __name__ == "__main__":
    main()
