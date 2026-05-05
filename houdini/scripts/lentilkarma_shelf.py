"""
LentilKarma Shelf Tool Script for Houdini

Add this as a shelf tool in Houdini:
  1. Right-click shelf bar > New Tool
  2. Set Script to: exec(open("path/to/lentilkarma_shelf.py").read())
  3. Or paste the contents directly

Alternative: In Houdini Python Shell, run:
  import lentilkarma_houdini; lentilkarma_houdini.show_lens_browser()
"""

import lentilkarma_houdini
lentilkarma_houdini.show_lens_browser()
