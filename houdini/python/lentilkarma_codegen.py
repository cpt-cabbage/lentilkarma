"""
LentilKarma VEX Code Generator for Houdini
Generates specialized CVEX lens shaders from lens data files.

This is the Houdini equivalent of LentilKarma's compile_osl_shader().
It generates VEX code with all optical constants baked as literals
for maximum render performance.
"""

import os
import math
from lentilkarma_data import (
    get_lens_data, abbe_to_cauchy, wavelength_to_rgb, lerp,
    generate_focus_lut
)


def generate_vex_shader(lens_filepath, output_filepath=None,
                        ca_samples=40, min_wl=410.0, max_wl=680.0):
    """Generate a specialized VEX lens shader for a specific lens.

    Args:
        lens_filepath: Path to the .txt lens data file
        output_filepath: Path to write the .vfl file (optional)
        ca_samples: Number of chromatic aberration wavelength samples
        min_wl: Minimum wavelength in nm for CA
        max_wl: Maximum wavelength in nm for CA

    Returns:
        str: The generated VEX shader source code
    """
    lens = get_lens_data(lens_filepath)
    lens_name = os.path.basename(lens_filepath).replace(".txt", "")

    # Determine which features this lens uses
    has_anamorphic = any(tt in (1, 2) for tt in lens["t"][:lens["lenses"]])
    has_asphere = len(lens["asphere_data"]) > 0
    is_zoom = any(z["idx"] > 0 for z in lens["zoom_data"])

    # Create a valid VEX identifier from the lens name
    import re
    opname = "lentilkarma_" + re.sub(r'[^a-zA-Z0-9]', '_', lens_name).strip('_').lower()

    lines = []
    lines.append(_header(lens_name))
    lines.append(_pragmas(opname, lens_name))
    lines.append(_includes(has_anamorphic, has_asphere))
    lines.append(_constants(lens))
    lines.append(_function_signature(opname))
    lines.append(_pixel_setup())
    lines.append(_camera_params())
    lines.append(_sensor_setup(lens))
    lines.append(_tilt_shift())
    lines.append(_ray_guiding(lens))
    lines.append(_chromatic_aberration(lens, ca_samples, min_wl, max_wl))
    lines.append(_trace_lens_elements(lens, has_anamorphic, has_asphere))
    lines.append(_post_trace_effects(lens))
    lines.append(_final_output())
    lines.append("}")  # close cvex function

    source = "\n".join(lines)

    if output_filepath:
        with open(output_filepath, 'w') as f:
            f.write(source)

    return source


def _header(lens_name):
    return f"""// LentilKarma CVEX Lens Shader — Auto-generated
// Lens: {lens_name}
// Target: Houdini 20.5+ Karma CPU
// DO NOT EDIT — regenerate from lens data file
"""


def _pragmas(opname, lens_name):
    return f"""#pragma opname      {opname}
#pragma oplabel     "LentilKarma: {lens_name}"

#pragma hint x invisible
#pragma hint y invisible
#pragma hint Time invisible
#pragma hint dofx invisible
#pragma hint dofy invisible
#pragma hint aspect invisible
#pragma hint P invisible
#pragma hint I invisible
#pragma hint tint invisible

#pragma label lens_fstop "F-Stop"
#pragma label lens_focus_dist "Focus Distance"
#pragma label chromatic_aberration "Chromatic Aberration"
#pragma label exposure "Exposure"
#pragma label aperture_ray_guiding "Ray Guiding"
#pragma label aperture_auto_exposure "Auto Exposure"
#pragma label tilt_shift_angle_x "Tilt X"
#pragma label tilt_shift_angle_y "Tilt Y"
#pragma label tilt_shift_offset_x "Shift X"
#pragma label tilt_shift_offset_y "Shift Y"
#pragma label dof_factor "DOF Factor"
#pragma label dof_remove "DOF Remove"
#pragma label flip "Flip Image"
#pragma label global_scale "Global Scale"
#pragma label distortion_amount "Distortion Amount"
#pragma label distortion_exponent "Distortion Exponent"
#pragma label bokeh_swirliness "Bokeh Swirliness"
#pragma label sensor_scale "Sensor Scale"

#pragma range lens_fstop 0 32
#pragma range lens_focus_dist 0 100
#pragma range chromatic_aberration 0 1
#pragma range exposure -5 5
#pragma range dof_factor 0 2
#pragma range dof_remove 0 1
#pragma range global_scale 0.01 10
#pragma range distortion_amount -1 1
#pragma range bokeh_swirliness 0 1
#pragma range sensor_scale 0.1 4

#pragma label focal_length "Focal Length"
#pragma label horizontal_aperture "Horizontal Aperture"
"""


def _includes(has_anamorphic, has_asphere):
    return '#include "lentilkarma_core.h"\n'


def _constants(lens):
    rg = lens["ray_guiding"]
    return f"""// Baked lens constants
#define LS_F_NUMBER {lens['f_number']}
#define LS_DEFAULT_SENSOR_SIZE {lens['default_sensor_size']}
#define LS_UNIT_SCALE {lens['unit_scale']}
#define LS_APERTURE_IDX {lens['aperture_idx']}
#define LS_APERTURE_R {lens['aperture_r']}
#define LS_APERTURE_D {lens['aperture_d']}
#define LS_SENSOR_POS_NEAR {lens['f_s_pos_near'] * lens['unit_scale']}
#define LS_SENSOR_POS_START {lens['f_s_pos_start'] * lens['unit_scale']}
#define LS_SENSOR_POS_FAR {lens['f_s_pos_end'] * lens['unit_scale']}
#define LS_RAY_SPREAD {rg['ray_spread']}
#define LS_RAY_SPREAD_500M {rg['ray_spread_500m']}
#define LS_RAY_SPREAD_NEAR {rg['ray_spread_near']}
#define LS_RAY_EDGE_ANGLE {rg['ray_edge_angle']}
#define LS_RAY_EDGE_ANGLE_500M {rg['ray_edge_angle_500m']}
#define LS_RAY_EDGE_ANGLE_NEAR {rg['ray_edge_angle_near']}
#define LS_RAY_GUIDING_SPREAD {rg['ray_guiding_spread']}
#define LS_RAMP_COVERAGE {rg['ramp_coverage']}
#define LS_RAMP_V1 {rg['ramp_v1']}
#define LS_RAMP_V2 {rg['ramp_v2']}
#define LS_RAMP_V3 {rg['ramp_v3']}
#define LS_RAMP_V4 {rg['ramp_v4']}
#define LS_RAMP_V5 {rg['ramp_v5']}
#define LS_RAY_GUIDING_FOCUS_SHIFT_500M {rg['focus_shift_500m']}
#define LS_RAY_GUIDING_FOCUS_SHIFT_NEAR {rg['focus_shift_near']}

#define LS_CA_SEED 0xBF31C7E2
"""


def _function_signature(opname):
    return f"""cvex {opname}(
    // Legacy CVEX inputs (provided by Karma to compiled VOPs)
    float x = 0; float y = 0; float Time = 0;
    float dofx = 0; float dofy = 0; float aspect = 1;
    // Outputs
    export vector P = 0; export vector I = 0;
    export vector tint = 1;
    // User parameters
    float lens_fstop = 0.0; float lens_focus_dist = 0.0;
    float chromatic_aberration = 0.0; float exposure = 0.0;
    int aperture_ray_guiding = 1; int aperture_auto_exposure = 1;
    float tilt_shift_angle_x = 0.0; float tilt_shift_angle_y = 0.0;
    float tilt_shift_offset_x = 0.0; float tilt_shift_offset_y = 0.0;
    float dof_factor = 1.0; float dof_remove = 0.0;
    int flip = 1; float global_scale = 1.0;
    float distortion_amount = 0.0; float distortion_exponent = 2.0;
    float bokeh_swirliness = 0.0;
    float sensor_scale = 1.0;
    // Camera passthrough (for OpenGL viewport settings — not used by lens shader)
    float focal_length = 0.0; float horizontal_aperture = 0.0;
)
{{"""


def _pixel_setup():
    return """
    // Legacy CVEX: x,y are NDC [-1, 1] provided by Karma.
    // Karma handles pixel sampling/jitter internally.
    // Convert to [0,1] for sensor mapping.
    float px = (x + 1.0) / 2.0;
    float py = (y + 1.0) / 2.0;
"""


def _camera_params():
    return """
    // Resolve camera parameters (legacy CVEX — no Karma focus/fstop available)
    float focus_dist_val = lens_focus_dist;
    if (focus_dist_val <= 0.0) focus_dist_val = 1.0;  // Default 1m
    focus_dist_val *= 1.0 / global_scale;
    float fstop_val = lens_fstop;
    if (fstop_val <= 0.0) fstop_val = LS_F_NUMBER;  // Use lens native f-number
    fstop_val = max(fstop_val, LS_F_NUMBER);  // Can't open wider than lens physical maximum
    float fstop01 = min(sqrt(pow(LS_F_NUMBER, 2.0) / pow(fstop_val, 2.0)), 1.0);
    // Sensor size: lens native scaled by user multiplier
    float _sensor_size = LS_DEFAULT_SENSOR_SIZE * sensor_scale;
"""


def _sensor_setup(lens):
    # Generate focus LUT
    focus_dists, sensor_positions = generate_focus_lut(lens, n_points=200)

    if len(focus_dists) > 0:
        fd_arr = ", ".join(f"{v:.10f}" for v in focus_dists)
        sp_arr = ", ".join(f"{v:.10f}" for v in sensor_positions)
        lut_code = f"""
    // Focus distance to sensor position LUT ({len(focus_dists)} samples)
    float _focus_dists[] = {{ {fd_arr} }};
    float _sensor_lut[] = {{ {sp_arr} }};
    float _sensor_position = ls_lookup_table(focus_dist_val, _focus_dists, _sensor_lut);"""
    else:
        # Fallback: use lens length as approximate sensor position
        sp_fallback = lens["lens_length"]
        lut_code = f"""
    // Focus LUT generation failed — using lens length as fallback
    float _sensor_position = {sp_fallback};"""

    return f"""
    // Sensor position and initial ray setup
    float flip_sign = flip ? 1.0 : -1.0;
    float s_px = (0.5 - px) * _sensor_size * flip_sign;
    float s_py = (0.5 - py) * _sensor_size / aspect * flip_sign;
{lut_code}

    vector ray_p = set(s_px, s_py, -_sensor_position);
    vector ray_d = set(0.0, 0.0, 1.0);
    vector _T = set(1.0, 1.0, 1.0);
    vector surface_n = set(0.0, 0.0, 1.0);
    vector sensor_pos = ray_p;
"""


def _tilt_shift():
    return """
    // Tilt-shift
    ray_p[0] += tilt_shift_offset_x * 0.001;
    ray_p[1] += tilt_shift_offset_y * 0.001;
    if (tilt_shift_angle_x != 0.0 || tilt_shift_angle_y != 0.0) {
        vector _ray_p = set(ray_p[0], ray_p[1], 0.0);
        _ray_p = qrotate(quaternion(tilt_shift_angle_x, set(1.0, 0.0, 0.0)), _ray_p);
        _ray_p = qrotate(quaternion(tilt_shift_angle_y, set(0.0, 1.0, 0.0)), _ray_p);
        ray_p = set(_ray_p[0], _ray_p[1], _ray_p[2] + ray_p[2]);
    }
"""


def _ray_guiding(lens):
    return """
    // Edge angle correction (deterministic, position-dependent ray steering)
    // Helps edge-pixel rays enter the lens at better angles for improved coverage
    float ray_angle = ls_ray_guiding_val(ray_p[2],
        LS_SENSOR_POS_NEAR, LS_SENSOR_POS_START, LS_SENSOR_POS_FAR,
        LS_RAY_EDGE_ANGLE_NEAR, LS_RAY_EDGE_ANGLE, LS_RAY_EDGE_ANGLE_500M);
    vector _pos = ray_p * set(1.0, 1.0, 0.0);
    float _pos_l = length(_pos);
    if (_pos_l > 0.00001) {
        ray_angle *= -5.5 * _pos_l;
        vector _pos_n = normalize(_pos);
        vector _cross = cross(ray_d, _pos_n);
        ray_d = qrotate(quaternion(radians(ray_angle), _cross), ray_d);
    }
"""


def _chromatic_aberration(lens, ca_samples, min_wl, max_wl):
    """Generate chromatic aberration code with baked wavelength color LUT."""
    # Build wavelength color table
    colors = []
    avg = [0.0, 0.0, 0.0]
    for i in range(ca_samples):
        value = i / (ca_samples - 1)
        c = wavelength_to_rgb(lerp(min_wl, max_wl, value))
        avg[0] += c[0]
        avg[1] += c[1]
        avg[2] += c[2]

    avg = [a / ca_samples for a in avg]
    avg_m = [1.0 - a for a in avg]

    # Normalize colors
    wl_colors = []
    for i in range(ca_samples):
        value = i / (ca_samples - 1)
        c = wavelength_to_rgb(lerp(min_wl, max_wl, value))
        wl_colors.append((c[0] + avg_m[0], c[1] + avg_m[1], c[2] + avg_m[2]))

    # Clamp negatives and rescale to preserve totals
    orig_r = sum(c[0] for c in wl_colors)
    orig_g = sum(c[1] for c in wl_colors)
    orig_b = sum(c[2] for c in wl_colors)

    clamped = [(max(0, c[0]), max(0, c[1]), max(0, c[2])) for c in wl_colors]
    clamp_r = sum(c[0] for c in clamped)
    clamp_g = sum(c[1] for c in clamped)
    clamp_b = sum(c[2] for c in clamped)

    sr = orig_r / clamp_r if clamp_r > 0 else 0.0
    sg = orig_g / clamp_g if clamp_g > 0 else 0.0
    sb = orig_b / clamp_b if clamp_b > 0 else 0.0

    final_colors = [(c[0] * sr, c[1] * sg, c[2] * sb) for c in clamped]

    # Build VEX array literal (use {r,g,b} vector literals, not set() in array init)
    arr = ", ".join(
        f"{{{c[0]:.6f}, {c[1]:.6f}, {c[2]:.6f}}}"
        for c in final_colors
    )

    return f"""
    // Chromatic aberration ({ca_samples} wavelength samples, {min_wl}-{max_wl}nm)
    if (chromatic_aberration != 0.0) {{
        // Hash-based random from pixel position and DOF sample (legacy CVEX)
        float ca_noise = rand(x * 7919.0 + y * 104729.0 + dofx * 32749.0 + float(LS_CA_SEED));
        int ca_sample = int(floor(ca_noise * {ca_samples}));
        ca_sample = clamp(ca_sample, 0, {ca_samples - 1});

        vector wl_colors[] = {{ {arr} }};
        _T *= wl_colors[ca_sample];
    }}
"""


def _trace_lens_elements(lens, has_anamorphic, has_asphere):
    """Generate the per-surface ray tracing code with baked constants.

    CRITICAL: Surfaces are iterated in REVERSE order (image side -> object side)
    because CVEX lens shaders trace backward from the sensor through the lens.
    This matches the Blender OSL code exactly.

    Convention (matching Blender):
    - dist starts at unit_scale (1mm offset matching Blender's dist=1.0) and accumulates d[i] BEFORE each surface intersection
    - Surfaces are processed from the last (image side) to the first (object side)
    - ls_lineSphereIntersect takes (dist, r[i]) and computes center = dist - radius
    - hit_idx: 1 if r[i] > 0, else 0
    - inside: 1 if surface index is even (surface 1 of group), 0 if odd (surface 2)
    """
    lenses = lens["lenses"]
    r = lens["r"]
    d = lens["d"]
    ior = lens["ior"]
    dia = lens["dia"]
    t = lens["t"]
    rot = lens["rot"]
    unit_scale = lens["unit_scale"]
    aperture_idx = lens["aperture_idx"]
    aperture_r = lens["aperture_r"]
    ior_corr = lens["ior_lens_grp_correction"]

    lines = []
    lines.append("\n    // ===== TRACE THROUGH LENS ELEMENTS (backward: image -> object) =====")
    lines.append(f"    float dist = {unit_scale};  // 1 unit offset (matching Blender's dist=1.0)")

    # Build asphere lookup: surface_idx -> asphere_data entry
    asphere_map = {}
    for asp in lens["asphere_data"]:
        asphere_map[asp["surface_idx"]] = asp

    # Iterate surfaces in REVERSE order (image side -> object side)
    # This is the backward trace convention used by the Blender OSL shader
    for i in range((lenses * 2) - 1, -1, -1):
        group = i // 2  # Lens group index (0-based)
        is_even = (i % 2 == 0)  # Even = surface 1 of group

        r_i = r[i]
        d_i = d[i]
        dia_i = dia[i]
        element_type = t[group] if group < len(t) else 0

        # IOR for this group
        ior_use = ior[group]

        # hit_idx: 1 for positive radius, 0 for negative (matching Blender)
        hit_idx = 1 if r_i > 0 else 0

        # inside: 1 for even index (surface 1), 0 for odd (surface 2)
        # (matching Blender: `if not i%2: inside = 1`)
        inside = 1 if is_even else 0

        lines.append(f"\n    // Surface {i+1} (group {group+1}, {'S1' if is_even else 'S2'}): r={r_i/unit_scale:.3f}mm")

        # Accumulate distance BEFORE intersection (matching Blender: dist += _d[i])
        if d_i != 0.0:
            lines.append(f"    dist += {d_i};")

        # Intersection
        asp = asphere_map.get(i + 1)  # 1-based surface index in data
        if asp:
            coeffs = asp["coefficients"]
            coeffs_str = ", ".join(str(c) for c in coeffs)
            lines.append(f"    {{ float _coeffs[] = {{ {coeffs_str} }};")
            lines.append(f"    ls_traceAsphericalElementFull(ray_p, ray_d, dist, {r_i}, {asp['k']}, _coeffs, surface_n, _T, {hit_idx}, {inside}, {unit_scale}); }}")
        elif element_type == 0:
            # Spherical — pass (dist, r_i), function computes center = dist - r_i
            lines.append(f"    ls_lineSphereIntersect(ray_p, ray_d, dist, {r_i}, surface_n, _T, {hit_idx}, {inside});")
        else:
            # Cylindrical (anamorphic)
            axis = "set(1.0, 0.0, 0.0)" if element_type == 1 else "set(0.0, 1.0, 0.0)"
            lines.append(f"    ls_lineCylinderIntersect(ray_p, ray_d, dist, {axis}, {r_i}, surface_n, _T, {hit_idx}, {inside});")

        # Diameter check (after intersection, before refraction — matching Blender)
        if dia_i < 99999.0:
            lines.append(f"    if (length(ray_p * set(1.0, 1.0, 0.0)) > {dia_i * 0.5}) _T = set(0.0, 0.0, 0.0);")

        # Refract at this surface
        lines.append(f"    ls_refract(ray_d, surface_n, {ior_use}, _T, {inside});")

        # Aperture check: insert after surface 2 (odd) of the aperture group
        # In the reversed iteration, surface 2 is processed first, then the
        # aperture stop, then surface 1
        if aperture_idx > 0 and i == (aperture_idx * 2) - 1:
            lines.append(f"\n    // Aperture stop")
            lines.append(f"    if (length(ray_p * set(1.0, 1.0, 0.0)) > {aperture_r}) _T = set(0.0, 0.0, 0.0);")

    return "\n".join(lines)


def _post_trace_effects(lens):
    return f"""

    // Post-trace effects
    _T *= pow(2, exposure);

    if (aperture_auto_exposure == 1) {{
        _T *= 1.0 / pow(fstop01, 2.0);
    }}

    // Thin-lens DOF using Karma-provided dofx/dofy samples (legacy CVEX)
    {{
        float _aperture_r = LS_APERTURE_R * fstop01 * dof_factor * (1.0 - dof_remove);
        if (_aperture_r > 0.0) {{
            // dofx, dofy are [0,1] random values from Karma; map to [-1,1]
            float _dofx = dofx * 2.0 - 1.0;
            float _dofy = dofy * 2.0 - 1.0;
            if (_dofx != 0.0 || _dofy != 0.0) {{
                vector focus_p = ls_rayPlaneIntersect(ray_p, ray_d,
                    set(0.0, 0.0, 1.0), set(0.0, 0.0, focus_dist_val));
                ray_p += set(_dofx * _aperture_r, _dofy * _aperture_r, 0.0);
                ray_d = normalize(focus_p - ray_p);
            }}
        }}
    }}

    if (bokeh_swirliness != 0.0) {{
        vector focus_p = ls_rayPlaneIntersect(ray_p, ray_d,
            set(0.0, 0.0, 1.0), set(0.0, 0.0, focus_dist_val));
        vector straight_line = normalize(focus_p) * focus_dist_val * 2.0;
        vector bokeh_point = ls_rayPlaneIntersect(ray_p, ray_d,
            set(0.0, 0.0, 1.0), straight_line);
        float bokeh_l = length(bokeh_point * set(1.0, 1.0, 0.0));
        float val = length(straight_line * set(1.0, 1.0, 0.0)) / max(bokeh_l, 0.0001);
        vector swirliness_p = set(bokeh_point[0] * val, bokeh_point[1] * val, bokeh_point[2]);
        swirliness_p = lerp(bokeh_point, swirliness_p, bokeh_swirliness);
        ray_d = normalize(swirliness_p - focus_p);
        ray_p = swirliness_p - (length(swirliness_p) * ray_d);
    }}

    if (distortion_amount != 0.0) {{
        float d_amount = pow(length(set(ray_d[0], ray_d[1], 0.0)), distortion_exponent) * distortion_amount;
        ray_d = lerp(ray_d, set(0.0, 0.0, -1.0), d_amount);
        ray_d = normalize(ray_d);
    }}
"""


def _final_output():
    return """
    // Final output (legacy CVEX: positive Z forward, matching asadlens/drostelens)
    P = ray_p * global_scale;
    I = ray_d;
    tint = _T;
"""


# -----------------------------------------------------------------------
# Combined (multi-lens) shader generator
# -----------------------------------------------------------------------

def _build_ca_colors_array(ca_samples, min_wl, max_wl):
    """Build the chromatic aberration wavelength color array VEX literal.

    Returns a string like "{r,g,b}, {r,g,b}, ..." for embedding in VEX source.
    """
    avg = [0.0, 0.0, 0.0]
    for i in range(ca_samples):
        value = i / (ca_samples - 1)
        c = wavelength_to_rgb(lerp(min_wl, max_wl, value))
        avg[0] += c[0]
        avg[1] += c[1]
        avg[2] += c[2]

    avg = [a / ca_samples for a in avg]
    avg_m = [1.0 - a for a in avg]

    wl_colors = []
    for i in range(ca_samples):
        value = i / (ca_samples - 1)
        c = wavelength_to_rgb(lerp(min_wl, max_wl, value))
        wl_colors.append((c[0] + avg_m[0], c[1] + avg_m[1], c[2] + avg_m[2]))

    orig_r = sum(c[0] for c in wl_colors)
    orig_g = sum(c[1] for c in wl_colors)
    orig_b = sum(c[2] for c in wl_colors)

    clamped = [(max(0, c[0]), max(0, c[1]), max(0, c[2])) for c in wl_colors]
    clamp_r = sum(c[0] for c in clamped)
    clamp_g = sum(c[1] for c in clamped)
    clamp_b = sum(c[2] for c in clamped)

    sr = orig_r / clamp_r if clamp_r > 0 else 0.0
    sg = orig_g / clamp_g if clamp_g > 0 else 0.0
    sb = orig_b / clamp_b if clamp_b > 0 else 0.0

    final_colors = [(c[0] * sr, c[1] * sg, c[2] * sb) for c in clamped]

    return ", ".join(
        f"{{{c[0]:.6f}, {c[1]:.6f}, {c[2]:.6f}}}"
        for c in final_colors
    )


def generate_combined_header(lens_filepaths, output_filepath=None,
                              ca_samples=40, min_wl=410.0, max_wl=680.0,
                              lut_points=50):
    """Generate the combined lens shader header file (lentilkarma.h).

    Contains all heavy shader code: core.h include, per-lens LUT functions,
    per-lens trace functions, and the main implementation function.
    This file lives on disk in the VEX include path, NOT in the HDA.

    Args:
        lens_filepaths: List of paths to .txt lens data files
        output_filepath: Path to write the .h file (optional)
        ca_samples: Number of chromatic aberration wavelength samples
        min_wl: Minimum wavelength in nm for CA
        max_wl: Maximum wavelength in nm for CA
        lut_points: Number of focus LUT sample points per lens

    Returns:
        str: The generated header source code
    """
    # ---- Parse all lenses ------------------------------------------------
    parsed = []
    for fp in lens_filepaths:
        lens = get_lens_data(fp)
        name = os.path.basename(fp).replace(".txt", "")
        has_anamorphic = any(tt in (1, 2) for tt in lens["t"][:lens["lenses"]])
        has_asphere = len(lens["asphere_data"]) > 0
        parsed.append({
            'name': name,
            'data': lens,
            'has_anamorphic': has_anamorphic,
            'has_asphere': has_asphere,
        })

    n = len(parsed)
    ca_colors_arr = _build_ca_colors_array(ca_samples, min_wl, max_wl)

    L = []  # output lines

    # ---- Include guard and header ----------------------------------------
    L.append('#ifndef LENTILKARMA_H')
    L.append('#define LENTILKARMA_H')
    L.append('')
    L.append(f'// LentilKarma Combined Lens Header — Auto-generated')
    L.append(f'// Contains {n} lenses')
    L.append(f'// DO NOT EDIT — regenerate from lens data files')
    L.append('')
    L.append('#include "lentilkarma_core.h"')
    L.append('')

    # ---- Per-lens focus LUT functions ------------------------------------
    L.append('// Per-lens focus LUT functions (isolated stack frames)')
    for i, p in enumerate(parsed):
        lens = p['data']
        focus_dists, sensor_positions = generate_focus_lut(lens, n_points=lut_points)
        L.append(f'float _lens_lut_{i}(float fd) {{')
        if len(focus_dists) > 0:
            fd_arr = ", ".join(f"{v:.8f}" for v in focus_dists)
            sp_arr = ", ".join(f"{v:.8f}" for v in sensor_positions)
            L.append(f'    float _k[] = {{ {fd_arr} }};')
            L.append(f'    float _v[] = {{ {sp_arr} }};')
            L.append(f'    return ls_lookup_table(fd, _k, _v);')
        else:
            sp_fallback = lens["lens_length"]
            L.append(f'    return {sp_fallback};')
        L.append('}')
        L.append('')

    # ---- Per-lens trace functions ----------------------------------------
    L.append('// Per-lens trace functions (isolated stack frames)')
    for i, p in enumerate(parsed):
        lens = p['data']
        trace_code = _trace_lens_elements(lens, p['has_anamorphic'], p['has_asphere'])
        L.append(f'void _lens_trace_{i}(vector ray_p; vector ray_d; vector _T; vector surface_n) {{')
        for line in trace_code.split('\n'):
            stripped = line.lstrip()
            if stripped.startswith('// ====='):
                continue
            if not stripped:
                continue
            L.append('    ' + stripped)
        L.append('}')
        L.append('')

    # ---- Main implementation function ------------------------------------
    L.append('// Main implementation function (SideFX header pattern)')
    L.append('void lentilkarma_impl(')
    L.append('    const float x; const float y; const float Time;')
    L.append('    const float dofx; const float dofy; const float aspect;')
    L.append('    vector P; vector I; vector tint;')
    L.append('    const int lens_select;')
    L.append('    const float lens_fstop; const float lens_focus_dist;')
    L.append('    const float chromatic_aberration; const float exposure;')
    L.append('    const int aperture_ray_guiding; const int aperture_auto_exposure;')
    L.append('    const float tilt_shift_angle_x; const float tilt_shift_angle_y;')
    L.append('    const float tilt_shift_offset_x; const float tilt_shift_offset_y;')
    L.append('    const float dof_factor; const float dof_remove;')
    L.append('    const int flip; const float global_scale;')
    L.append('    const float distortion_amount; const float distortion_exponent;')
    L.append('    const float bokeh_swirliness;')
    L.append('    const float sensor_scale;')
    L.append('    const float focal_length; const float horizontal_aperture;')
    L.append(')')
    L.append('{')

    L.append('')

    # ---- Pixel setup (shared) — legacy CVEX convention --------------------
    L.append('    // Legacy CVEX: x,y are NDC [-1, 1] provided by Karma.')
    L.append('    // Karma handles pixel sampling/jitter internally.')
    L.append('    // Convert to [0,1] for sensor mapping.')
    L.append('    float px = (x + 1.0) / 2.0;')
    L.append('    float py = (y + 1.0) / 2.0;')
    L.append('')

    # ---- Per-lens constants + LUT call (single switch) -------------------
    L.append('    // Lens-specific constants + focus LUT (single switch)')
    L.append('    float _f_number = 0;')
    L.append('    float _sensor_size_native = 0;')
    L.append('    float _aperture_r = 0;')
    L.append('    float _sensor_pos_near = 0;')
    L.append('    float _sensor_pos_start = 0;')
    L.append('    float _sensor_pos_far = 0;')
    L.append('    float _edge_angle_near = 0;')
    L.append('    float _edge_angle = 0;')
    L.append('    float _edge_angle_500m = 0;')
    L.append('')

    # Camera params depend on _f_number, so compute focus_dist_val first
    # (it doesn't depend on lens constants)
    L.append('    float focus_dist_val = lens_focus_dist;')
    L.append('    if (focus_dist_val <= 0.0) focus_dist_val = 1.0;  // Default 1m')
    L.append('    focus_dist_val *= 1.0 / global_scale;')
    L.append('    float _sensor_position = 0;')
    L.append('')

    for i, p in enumerate(parsed):
        lens = p['data']
        rg = lens['ray_guiding']
        kw = 'if' if i == 0 else '} else if'
        L.append(f'    {kw} (lens_select == {i}) {{ // {p["name"]}')
        L.append(f'        _f_number = {lens["f_number"]};')
        L.append(f'        _sensor_size_native = {lens["default_sensor_size"]};')
        L.append(f'        _aperture_r = {lens["aperture_r"]};')
        L.append(f'        _sensor_pos_near = {lens["f_s_pos_near"] * lens["unit_scale"]};')
        L.append(f'        _sensor_pos_start = {lens["f_s_pos_start"] * lens["unit_scale"]};')
        L.append(f'        _sensor_pos_far = {lens["f_s_pos_end"] * lens["unit_scale"]};')
        L.append(f'        _edge_angle_near = {rg["ray_edge_angle_near"]};')
        L.append(f'        _edge_angle = {rg["ray_edge_angle"]};')
        L.append(f'        _edge_angle_500m = {rg["ray_edge_angle_500m"]};')
        L.append(f'        _sensor_position = _lens_lut_{i}(focus_dist_val);')
    L.append('    }')
    L.append('')

    # ---- Camera params (shared, uses _f_number) --------------------------
    L.append('    // Camera parameters')
    L.append('    float fstop_val = lens_fstop;')
    L.append('    if (fstop_val <= 0.0) fstop_val = _f_number;')
    L.append('    fstop_val = max(fstop_val, _f_number);')
    L.append('    float fstop01 = min(sqrt(pow(_f_number, 2.0) / pow(fstop_val, 2.0)), 1.0);')
    L.append('    float _sensor_size = _sensor_size_native * sensor_scale;')
    L.append('')

    # ---- Sensor setup (shared) -------------------------------------------
    L.append('    // Sensor position setup')
    L.append('    float flip_sign = flip ? 1.0 : -1.0;')
    L.append('    float s_px = (0.5 - px) * _sensor_size * flip_sign;')
    L.append('    float s_py = (0.5 - py) * _sensor_size / aspect * flip_sign;')
    L.append('')

    # ---- Ray setup (shared) ----------------------------------------------
    L.append('    vector ray_p = set(s_px, s_py, -_sensor_position);')
    L.append('    vector ray_d = set(0.0, 0.0, 1.0);')
    L.append('    vector _T = set(1.0, 1.0, 1.0);')
    L.append('    vector surface_n = set(0.0, 0.0, 1.0);')
    L.append('    vector sensor_pos = ray_p;')
    L.append('')

    # ---- Tilt-shift (shared) ---------------------------------------------
    L.append('    // Tilt-shift')
    L.append('    ray_p[0] += tilt_shift_offset_x * 0.001;')
    L.append('    ray_p[1] += tilt_shift_offset_y * 0.001;')
    L.append('    if (tilt_shift_angle_x != 0.0 || tilt_shift_angle_y != 0.0) {')
    L.append('        vector _ray_p = set(ray_p[0], ray_p[1], 0.0);')
    L.append('        _ray_p = qrotate(quaternion(tilt_shift_angle_x, set(1.0, 0.0, 0.0)), _ray_p);')
    L.append('        _ray_p = qrotate(quaternion(tilt_shift_angle_y, set(0.0, 1.0, 0.0)), _ray_p);')
    L.append('        ray_p = set(_ray_p[0], _ray_p[1], _ray_p[2] + ray_p[2]);')
    L.append('    }')
    L.append('')

    # ---- Ray guiding (shared, uses local vars) ---------------------------
    L.append('    // Edge angle correction')
    L.append('    float ray_angle = ls_ray_guiding_val(ray_p[2],')
    L.append('        _sensor_pos_near, _sensor_pos_start, _sensor_pos_far,')
    L.append('        _edge_angle_near, _edge_angle, _edge_angle_500m);')
    L.append('    vector _pos = ray_p * set(1.0, 1.0, 0.0);')
    L.append('    float _pos_l = length(_pos);')
    L.append('    if (_pos_l > 0.00001) {')
    L.append('        ray_angle *= -5.5 * _pos_l;')
    L.append('        vector _pos_n = normalize(_pos);')
    L.append('        vector _cross = cross(ray_d, _pos_n);')
    L.append('        ray_d = qrotate(quaternion(radians(ray_angle), _cross), ray_d);')
    L.append('    }')
    L.append('')

    # ---- Chromatic aberration (shared) -----------------------------------
    L.append(f'    // Chromatic aberration ({ca_samples} wavelength samples, {min_wl}-{max_wl}nm)')
    L.append('    if (chromatic_aberration != 0.0) {')
    L.append('        // Hash-based random from pixel position and DOF sample (legacy CVEX)')
    L.append('        float ca_noise = rand(x * 7919.0 + y * 104729.0 + dofx * 32749.0 + float(0xBF31C7E2));')
    L.append(f'        int ca_sample = int(floor(ca_noise * {ca_samples}));')
    L.append(f'        ca_sample = clamp(ca_sample, 0, {ca_samples - 1});')
    L.append(f'        vector wl_colors[] = {{ {ca_colors_arr} }};')
    L.append('        _T *= wl_colors[ca_sample];')
    L.append('    }')
    L.append('')

    # ---- Per-lens trace dispatch -----------------------------------------
    L.append('    // ===== TRACE THROUGH LENS ELEMENTS =====')

    for i, p in enumerate(parsed):
        kw = 'if' if i == 0 else '} else if'
        L.append(f'    {kw} (lens_select == {i}) {{ // {p["name"]}')
        L.append(f'        _lens_trace_{i}(ray_p, ray_d, _T, surface_n);')
    L.append('    }')
    L.append('')

    # ---- Post-trace effects (shared, uses local vars) --------------------
    L.append('    // Post-trace effects')
    L.append('    _T *= pow(2, exposure);')
    L.append('')
    L.append('    if (aperture_auto_exposure == 1) {')
    L.append('        _T *= 1.0 / pow(fstop01, 2.0);')
    L.append('    }')
    L.append('')
    L.append('    // Thin-lens DOF using Karma-provided dofx/dofy samples (legacy CVEX)')
    L.append('    {')
    L.append('        float _ap_r = _aperture_r * fstop01 * dof_factor * (1.0 - dof_remove);')
    L.append('        if (_ap_r > 0.0) {')
    L.append('            // dofx, dofy are [0,1] random values from Karma; map to [-1,1]')
    L.append('            float _dofx = dofx * 2.0 - 1.0;')
    L.append('            float _dofy = dofy * 2.0 - 1.0;')
    L.append('            if (_dofx != 0.0 || _dofy != 0.0) {')
    L.append('                vector focus_p = ls_rayPlaneIntersect(ray_p, ray_d,')
    L.append('                    set(0.0, 0.0, 1.0), set(0.0, 0.0, focus_dist_val));')
    L.append('                ray_p += set(_dofx * _ap_r, _dofy * _ap_r, 0.0);')
    L.append('                ray_d = normalize(focus_p - ray_p);')
    L.append('            }')
    L.append('        }')
    L.append('    }')
    L.append('')
    L.append('    if (bokeh_swirliness != 0.0) {')
    L.append('        vector focus_p = ls_rayPlaneIntersect(ray_p, ray_d,')
    L.append('            set(0.0, 0.0, 1.0), set(0.0, 0.0, focus_dist_val));')
    L.append('        vector straight_line = normalize(focus_p) * focus_dist_val * 2.0;')
    L.append('        vector bokeh_point = ls_rayPlaneIntersect(ray_p, ray_d,')
    L.append('            set(0.0, 0.0, 1.0), straight_line);')
    L.append('        float bokeh_l = length(bokeh_point * set(1.0, 1.0, 0.0));')
    L.append('        float val = length(straight_line * set(1.0, 1.0, 0.0)) / max(bokeh_l, 0.0001);')
    L.append('        vector swirliness_p = set(bokeh_point[0] * val, bokeh_point[1] * val, bokeh_point[2]);')
    L.append('        swirliness_p = lerp(bokeh_point, swirliness_p, bokeh_swirliness);')
    L.append('        ray_d = normalize(swirliness_p - focus_p);')
    L.append('        ray_p = swirliness_p - (length(swirliness_p) * ray_d);')
    L.append('    }')
    L.append('')
    L.append('    if (distortion_amount != 0.0) {')
    L.append('        float d_amount = pow(length(set(ray_d[0], ray_d[1], 0.0)), distortion_exponent) * distortion_amount;')
    L.append('        ray_d = lerp(ray_d, set(0.0, 0.0, -1.0), d_amount);')
    L.append('        ray_d = normalize(ray_d);')
    L.append('    }')
    L.append('')

    # ---- Final output (shared) -------------------------------------------
    L.append('    // Final output (legacy CVEX: positive Z forward, matching asadlens/drostelens)')
    L.append('    P = ray_p * global_scale;')
    L.append('    I = ray_d;')
    L.append('    tint = _T;')
    L.append('}')
    L.append('')
    L.append('#endif // LENTILKARMA_H')

    source = '\n'.join(L)

    if output_filepath:
        with open(output_filepath, 'w') as f:
            f.write(source)

    return source


def generate_combined_vex_shader(lens_filepaths, output_filepath=None,
                                 ca_samples=40, min_wl=410.0, max_wl=680.0,
                                 lut_points=50):
    """Generate a tiny VEX wrapper that includes the combined header.

    The wrapper contains only pragmas and a cvex function that calls
    lentilkarma_impl() from the header. This keeps the HDA's
    CVexVflCode section small (~2KB) to avoid truncation.

    The header file must be generated separately via generate_combined_header()
    and placed in the VEX include path.

    Args:
        lens_filepaths: List of paths to .txt lens data files
        output_filepath: Path to write the .vfl file (optional)
        ca_samples: Number of chromatic aberration wavelength samples
        min_wl: Minimum wavelength in nm for CA
        max_wl: Maximum wavelength in nm for CA
        lut_points: Number of focus LUT sample points per lens (default 50)

    Returns:
        str: The generated VEX wrapper source code
    """
    # Only need lens names for pragma choices (no heavy parsing)
    names = []
    for fp in lens_filepaths:
        name = os.path.basename(fp).replace(".txt", "")
        names.append(name)

    n = len(names)

    L = []  # output lines

    # ---- Header ----------------------------------------------------------
    L.append(f"// LentilKarma Combined Lens Shader — Auto-generated")
    L.append(f"// Contains {n} lenses (implementation in lentilkarma.h)")
    L.append(f"// Target: Houdini 20.5+ Karma CPU")
    L.append(f"// DO NOT EDIT — regenerate from lens data files")
    L.append("")

    # ---- Pragmas ---------------------------------------------------------
    L.append('#pragma opname      lentilkarma')
    L.append('#pragma oplabel     "LentilKarma Lens Shader"')
    L.append('')
    L.append('#pragma hint x invisible')
    L.append('#pragma hint y invisible')
    L.append('#pragma hint Time invisible')
    L.append('#pragma hint dofx invisible')
    L.append('#pragma hint dofy invisible')
    L.append('#pragma hint aspect invisible')
    L.append('#pragma hint P invisible')
    L.append('#pragma hint I invisible')
    L.append('#pragma hint tint invisible')
    L.append('')

    # Lens select dropdown menu
    for i, name in enumerate(names):
        display = name.replace('"', '\\"')
        L.append(f'#pragma choice lens_select "{i}" "{display}"')
    L.append('#pragma label lens_select "Lens"')
    L.append('')

    # Other parameter labels & ranges
    L.append('#pragma label lens_fstop "F-Stop"')
    L.append('#pragma label lens_focus_dist "Focus Distance"')
    L.append('#pragma label chromatic_aberration "Chromatic Aberration"')
    L.append('#pragma label exposure "Exposure"')
    L.append('#pragma label aperture_ray_guiding "Ray Guiding"')
    L.append('#pragma label aperture_auto_exposure "Auto Exposure"')
    L.append('#pragma label tilt_shift_angle_x "Tilt X"')
    L.append('#pragma label tilt_shift_angle_y "Tilt Y"')
    L.append('#pragma label tilt_shift_offset_x "Shift X"')
    L.append('#pragma label tilt_shift_offset_y "Shift Y"')
    L.append('#pragma label dof_factor "DOF Factor"')
    L.append('#pragma label dof_remove "DOF Remove"')
    L.append('#pragma label flip "Flip Image"')
    L.append('#pragma label global_scale "Global Scale"')
    L.append('#pragma label distortion_amount "Distortion Amount"')
    L.append('#pragma label distortion_exponent "Distortion Exponent"')
    L.append('#pragma label bokeh_swirliness "Bokeh Swirliness"')
    L.append('#pragma label sensor_scale "Sensor Scale"')
    L.append('')
    L.append('#pragma range lens_fstop 0 32')
    L.append('#pragma range lens_focus_dist 0 100')
    L.append('#pragma range chromatic_aberration 0 1')
    L.append('#pragma range exposure -5 5')
    L.append('#pragma range dof_factor 0 2')
    L.append('#pragma range dof_remove 0 1')
    L.append('#pragma range global_scale 0.01 10')
    L.append('#pragma range distortion_amount -1 1')
    L.append('#pragma range bokeh_swirliness 0 1')
    L.append('#pragma range sensor_scale 0.1 4')
    L.append('')
    L.append('#pragma label focal_length "Focal Length"')
    L.append('#pragma label horizontal_aperture "Horizontal Aperture"')
    L.append('')

    # ---- Include header (all heavy code is here) -------------------------
    L.append('#include "lentilkarma.h"')
    L.append('')

    # ---- Thin cvex wrapper -----------------------------------------------
    L.append('cvex lentilkarma(')
    L.append('    // Legacy CVEX inputs (provided by Karma to compiled VOPs)')
    L.append('    float x = 0; float y = 0; float Time = 0;')
    L.append('    float dofx = 0; float dofy = 0; float aspect = 1;')
    L.append('    // Outputs')
    L.append('    export vector P = 0; export vector I = 0;')
    L.append('    export vector tint = 1;')
    L.append('    // User parameters')
    L.append('    int lens_select = 0;')
    L.append('    float lens_fstop = 0.0; float lens_focus_dist = 0.0;')
    L.append('    float chromatic_aberration = 0.0; float exposure = 0.0;')
    L.append('    int aperture_ray_guiding = 1; int aperture_auto_exposure = 1;')
    L.append('    float tilt_shift_angle_x = 0.0; float tilt_shift_angle_y = 0.0;')
    L.append('    float tilt_shift_offset_x = 0.0; float tilt_shift_offset_y = 0.0;')
    L.append('    float dof_factor = 1.0; float dof_remove = 0.0;')
    L.append('    int flip = 1; float global_scale = 1.0;')
    L.append('    float distortion_amount = 0.0; float distortion_exponent = 2.0;')
    L.append('    float bokeh_swirliness = 0.0;')
    L.append('    float sensor_scale = 1.0;')
    L.append('    // Camera passthrough (for OpenGL viewport settings)')
    L.append('    float focal_length = 0.0; float horizontal_aperture = 0.0;')
    L.append(')')
    L.append('{')
    L.append('    lentilkarma_impl(')
    L.append('        x, y, Time, dofx, dofy, aspect,')
    L.append('        P, I, tint,')
    L.append('        lens_select,')
    L.append('        lens_fstop, lens_focus_dist,')
    L.append('        chromatic_aberration, exposure,')
    L.append('        aperture_ray_guiding, aperture_auto_exposure,')
    L.append('        tilt_shift_angle_x, tilt_shift_angle_y,')
    L.append('        tilt_shift_offset_x, tilt_shift_offset_y,')
    L.append('        dof_factor, dof_remove,')
    L.append('        flip, global_scale,')
    L.append('        distortion_amount, distortion_exponent,')
    L.append('        bokeh_swirliness,')
    L.append('        sensor_scale,')
    L.append('        focal_length, horizontal_aperture')
    L.append('    );')
    L.append('}')

    source = '\n'.join(L)

    if output_filepath:
        with open(output_filepath, 'w') as f:
            f.write(source)

    return source


# CLI entry point
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python lentilkarma_codegen.py <lens_file.txt> [output.vfl]")
        sys.exit(1)

    lens_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    source = generate_vex_shader(lens_file, output_file)

    if output_file:
        print(f"Generated VEX shader: {output_file}")
    else:
        print(source)
