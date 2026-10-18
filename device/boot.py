"""MicroPython boot script.

This runs before ``main.py`` on every reset and wake. It must stay minimal
and safe: no network access, no destructive flash operations, and no writes
to the filesystem.

Phase 1 does not require any boot-time work. Later phases may restore the
wake reason or prepare state that must exist before ``main.py`` starts.
"""

# Intentionally minimal for Phase 1.
