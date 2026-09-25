"""amr-sim: 2D simulator of an autonomous wheeled platform (hackathon case "Safe route")."""
import sys

# Version check goes before any other import: later modules use 3.10 syntax.
if sys.version_info < (3, 10):
    sys.stderr.write("amrsim requires Python 3.10 or newer, found %d.%d\n" % sys.version_info[:2])
    raise SystemExit(2)

__version__ = "0.2.0"
SCHEMA = "amr-1.0"
