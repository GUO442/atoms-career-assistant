# -*- coding: utf-8 -*-
"""Packaged data root; development keeps the current workspace by default."""
import os
from pathlib import Path
WORKSPACE = Path(os.environ.get('CAREER_HOME', str(Path(__file__).resolve().parent))).expanduser().resolve()
