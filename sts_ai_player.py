#!/usr/bin/env python3
"""Compatibility entrypoint for the Slay the Spire AI process."""

from __future__ import annotations

import sys

from _sts_ai_player import engine as _engine


if __name__ == "__main__":
    raise SystemExit(_engine.main())

sys.modules[__name__] = _engine
