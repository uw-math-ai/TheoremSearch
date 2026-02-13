"""
Shared regex patterns for theorem finding
"""

import re

POTENTIAL_REF_RE = re.compile(r'^[A-Z0-9.]+$')