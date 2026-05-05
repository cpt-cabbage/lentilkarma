# LentilKarma for Houdini 20.5

LentilKarma physically simulates real camera lenses in Karma CPU by tracing rays
through multi-element optical systems using real-world lens prescription data.
Each lens generates a specialized CVEX lens shader with all optical constants
baked for maximum render performance.

**Supported renderer:** Karma CPU only (CVEX lens shaders are not supported in Karma XPU)

> **Disclaimer — experimental project**
>
> LentilKarma is a personal experiment and is **not intended for production use**.
> It is not actively maintained. A few things to keep in mind:
>
> - **No warranty.** The code is provided as-is. Incorrect optical math or edge-case lens data could produce subtly wrong renders without any obvious error.
> - **Houdini version lock.** The package targets Houdini 20.5 specifically. Other versions may silently break.
> - **Pre-compiled shaders may be stale.** `lentilkarma.vex` and `lentilkarma_small.vex` were compiled at a point in time — if you modify the VEX source you must recompile.
> - **No test suite.** There is no automated testing, so regressions are possible after any change.
>
> Use it to learn, experiment, and have fun — but don't build a pipeline around it.

## Quick Start

### 1. Install the Package

Copy `houdini/LentilKarma.json` to your Houdini packages directory:

```
# Windows
copy houdini\LentilKarma.json %USERPROFILE%\Documents\houdini20.5\packages\

# macOS/Linux
cp houdini/LentilKarma.json ~/houdini20.5/packages/
```

Edit the copied `LentilKarma.json` and set the path to the LentilKarma root directory:

```json
{
    "env": [
        { "LENTILKARMA": "/path/to/lentilkarma" }
    ],
    "path": "$LENTILKARMA/houdini"
}
```

### 2. Generate a Lens Shader

In Houdini's Python Shell:

```python
import lentilkarma_houdini
lentilkarma_houdini.show_lens_browser()
```

The lens browser lets you select individual lenses or apply all lenses at once to generate a combined multi-lens shader.

Or generate from a specific lens file:

```python
import lentilkarma_houdini
result = lentilkarma_houdini.apply_lens_to_camera(
    "/path/to/lentilkarma/LentilKarma_Data/lenses/100mm f1.4 W Merte 1928 Baltar.txt"
)
```

### 3. Apply to Karma Camera

The lens browser automatically:
- Generates a **Lens Material USDA** (same structure as SideFX's `kma_camera_lens.usd`)
- Creates an **Edit Material Properties** LOP in `/stage` (same node type SideFX uses)
- Wires it above the Camera LOP and links the camera's **Lens Material** parameter
- Creates a **VOP node** in `/mat` (legacy fallback)

If auto-configuration doesn't find the camera, manually:
1. In your LOP network, select or create a **Camera** LOP
2. In the camera's **Karma** tab:
   - Enable **Use Lens Shader**
   - Set **Lens Material** to reference the `lentilkarmamaterial1` node's prim path
   - (Or legacy: set **Lens Shader VOP** to the VOP path in `/mat`)
3. Set renderer to **Karma CPU** (not XPU)
4. Render

To debug camera parameter names:
```python
import lentilkarma_houdini
lentilkarma_houdini.discover_camera_parms()
```

To manually set up the stage after compiling:
```python
import lentilkarma_houdini
lentilkarma_houdini.setup_lens_in_stage()
```

## Command-Line Usage (No Houdini Required)

Generate VEX source from a lens file:

```bash
cd houdini/python
python lentilkarma_codegen.py "../../LentilKarma_Data/lenses/100mm f1.4 W Merte 1928 Baltar.txt" output.vfl
```

Then compile with Houdini's VEX compiler:

```bash
vcc -I ../vex -o output.vex output.vfl
```

## Directory Structure

```
lentilkarma/
├── LentilKarma_Data/
│   ├── lenses/               # Lens prescription .txt files
│   ├── presets/              # Chromatic aberration, sensor size, color ramp presets
│   └── textures/             # Bokeh shape textures
├── houdini/
│   ├── LentilKarma.json      # Houdini package descriptor
│   ├── vex/
│   │   ├── lentilkarma_core.h      # Core optical functions (VEX header)
│   │   └── lentilkarma_shader.vfl  # Reference/template shader
│   ├── python/
│   │   ├── lentilkarma_data.py     # Lens data parser
│   │   ├── lentilkarma_codegen.py  # VEX code generator
│   │   └── lentilkarma_houdini.py  # Houdini integration API
│   └── scripts/
│       └── lentilkarma_shelf.py    # Shelf tool script
├── lentilkarma.vex            # Pre-compiled shader (full lens set)
└── lentilkarma_small.vex      # Pre-compiled shader (reduced lens set)
```

## Shader Parameters

Generated shaders expose these user-controllable parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| fstop_override | float | 0.0 | Override f-stop (0 = use camera) |
| focus_dist_override | float | 0.0 | Override focus distance (0 = use camera) |
| chromatic_aberration | float | 0.0 | Chromatic aberration strength (0-1) |
| exposure | float | 0.0 | Exposure compensation (stops) |
| aperture_ray_guiding | int | 1 | Enable ray guiding optimization |
| aperture_auto_exposure | int | 1 | Auto-compensate exposure for aperture |
| tilt_shift_angle_x/y | float | 0.0 | Tilt angles (degrees) |
| tilt_shift_offset_x/y | float | 0.0 | Shift offsets (mm) |
| dof_factor | float | 1.0 | Depth of field multiplier |
| dof_remove | float | 0.0 | DOF removal (0=full DOF, 1=no DOF) |
| flip | int | 1 | Flip image (1=normal) |
| global_scale | float | 1.0 | Scene scale factor |
| distortion_amount | float | 0.0 | Barrel/pincushion distortion |
| bokeh_swirliness | float | 0.0 | Swirly bokeh effect |

## Technical Notes

- Each lens generates a specialized shader with baked constants (no runtime overhead)
- The focus system uses a 200-sample lookup table traced through the optical system
- Ray guiding optimization reduces noise by directing samples toward valid optical paths
- Chromatic aberration uses 40 wavelength samples with stochastic selection
- All optical functions are in `lentilkarma_core.h` and prefixed with `ls_` to avoid conflicts

## Attribution

LentilKarma is based on [Lentil](https://github.com/zpelgrims/lentil) by Zeno Pelgrims — a physically accurate lens simulation shader for Arnold. The optical model, lens prescription data format, and core ray-tracing approach originate from that project.
