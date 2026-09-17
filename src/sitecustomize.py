"""Compatibility for the vendor Spark image's Python 3.10 interpreter.

HydroPulse itself requires Python 3.12+.  Apache's Spark 3.5.6 image bundles
Python 3.10, which lacks ``datetime.UTC``.  Python imports ``sitecustomize``
at startup when ``/app/src`` is on ``PYTHONPATH``; define the standard alias
before Spark imports the shared application modules.
"""

import datetime
import enum

if not hasattr(datetime, "UTC"):  # pragma: no cover - only the Spark container uses Python 3.10
    datetime.UTC = datetime.timezone.utc

if not hasattr(enum, "StrEnum"):  # pragma: no cover - only the Spark container uses Python 3.10
    class StrEnum(str, enum.Enum):
        pass

    enum.StrEnum = StrEnum
