"""Which init a seasonal run is on, and which one it should be on.

The C3S seasonal archive publishes a new init every month: the ECMWF on
the 6th and every other centre on the 10th.  A centre is therefore on
this month's init from its release day, and before that the newest init
it can have is last month's.

Everything that has to know the init asks here, so that the December
release moves the whole pipeline on its own instead of waiting for a
constant in a script to be edited.
"""
import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
STATE = os.path.join(DATA, "models_fetched.json")

# the day of the month each centre's monthly forecast is released
RELEASE_DAY = {"ecmwf": 6}
DEFAULT_RELEASE_DAY = 10

# tag -> (centre, system) for the C3S centres
CENTRES = {
    "ecmwf-seas5": ("ecmwf", "51"),
    "ukmo-gloseas6": ("ukmo", "610"),
    "meteo-france-s9": ("meteo-france", "9"),
    "cmcc-sps4": ("cmcc", "4"),
    "dwd-gcfs2": ("dwd", "22"),
    "eccc-canesm5": ("eccc", "4"),
    "eccc-gem5": ("eccc", "5"),
    "jma-jra3": ("jma", "4"),
    "bom-access-s2": ("bom", "2"),
}


def centre_of(tag):
    """The C3S centre a model tag belongs to."""
    if tag in CENTRES:
        return CENTRES[tag][0]
    return CENTRES.get(tag, (tag, ""))[0]


def newest_init(tag):
    """The newest init a centre could be serving today.

    Before its release day a centre is still on last month's init, so a
    request is not made for a date the archive does not have yet and the
    queue is not spent on it.
    """
    centre = centre_of(tag)
    today = date.today()
    day = RELEASE_DAY.get(centre, DEFAULT_RELEASE_DAY)
    y, m = today.year, today.month
    if today.day < day:
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return "%04d-%02d" % (y, m)


def recorded_init(tag, default=None):
    """The init a model is recorded on in the state file."""
    st = {}
    if os.path.exists(STATE):
        try:
            st = json.load(open(STATE))
        except Exception:
            st = {}
    return st.get(tag, {}).get("init") or (default or newest_init(tag))


def state():
    """The whole state file, or an empty dict."""
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE))
        except Exception:
            pass
    return {}
