"""
Black Hole Lens Shader — Shelf Tool Script for Houdini

Add this as a shelf tool in Houdini:
  1. Right-click shelf bar > New Tool
  2. Set Script to: exec(open("path/to/blackhole_shelf.py").read())
  3. Or paste the contents directly

Alternative: In Houdini Python Shell, run:
  import blackhole_houdini; blackhole_houdini.build_blackhole_shader()
"""

import blackhole_houdini
blackhole_houdini.build_blackhole_shader()
