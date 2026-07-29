from __future__ import annotations

import re

HEX_COLOR_RE: re.Pattern[str] = re.compile(r"^#[0-9A-Fa-f]{6}$")
