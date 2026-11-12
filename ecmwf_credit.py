"""The ECMWF's attribution, shown on the graphics that use its data.

ECMWF asks that any graphic made from its data carries its credit on the
bottom right, inside the graphic.  The multi-model products average several
centres together, so they are not ECMWF products and do not carry it.
"""
from datetime import date

ECMWF_CREDIT = ("© %d European Centre for Medium-Range Weather Forecasts "
                "(ECMWF). This service is based on data and products of the "
                "ECMWF." % date.today().year)

# the systems whose data comes from ECMWF
ECMWF_TAGS = {"ecmwf-seas5", "ecmwf-s4s"}


def credit_for(tag):
    """The credit line for a model's graphic, or an empty string."""
    return ECMWF_CREDIT if tag in ECMWF_TAGS else ""
