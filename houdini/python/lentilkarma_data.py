"""
LentilKarma Data Parser for Houdini
Standalone Python module — no Blender dependencies.

Parses lens prescription .txt files and returns structured data
for VEX code generation.
"""

import os
import math

# Constants matching LentilKarma Blender addon
MAX_LENSES = 30
MAX_ASPHERE_SURFACES = 15
MAX_ASPHERE_CONIC_CONSTANTS = 15


def lerp(a, b, t):
    return (1.0 - t) * a + t * b


def add_leading_zero(i):
    return str(i).zfill(2)


def parse_lens_file(filepath):
    """Parse a LentilKarma .txt lens file into a key-value dictionary.

    Args:
        filepath: Path to the .txt lens file

    Returns:
        dict: Key-value pairs from the lens file
    """
    data = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            content = line.split(" = ")
            if len(content) == 2:
                key = content[0].rstrip()
                val = content[1].strip().rstrip('\n')
                if key and val:
                    data[key] = val
    return data


def get_lens_data(filepath, zoom_factor=0.0, rack_focus_factor=0.0, aperture_factor=1.0):
    """Parse a lens file and return structured lens data.

    This is the Houdini equivalent of LentilKarma's get_lens_data() function,
    operating purely from file data (no Blender properties).

    Args:
        filepath: Path to the .txt lens file
        zoom_factor: Zoom position (0-1) for zoom lenses
        rack_focus_factor: Rack focus position (0-1)
        aperture_factor: Aperture scale factor (1.0 = design aperture)

    Returns:
        dict with all lens optical data needed for VEX code generation
    """
    data = parse_lens_file(filepath)

    # Unit scale (mm to meters typically)
    unit_scale = float(data.get("unit scale", 0.001))

    # Surface radii, thicknesses, diameters
    r = []
    d = []
    dia = []
    for x in range(1, (MAX_LENSES * 2) + 1):
        r.append(float(data.get("r" + str(x), 0.0)) * unit_scale)
        d.append(float(data.get("d" + str(x), 0.0)) * unit_scale)

        diav = float(data.get("dia" + str(x), 0.0)) * unit_scale
        if diav == 0.0:
            diav = 100000.0
        dia.append(diav)

    # Per-group data: IOR, element type, rotation, Abbe number
    ior = []
    t = []  # element type: 0=spherical, 1=cylindrical_x, 2=cylindrical_y
    rot = []
    V = []  # Abbe number
    for x in range(1, MAX_LENSES + 1):
        # IOR
        get_ior = float(data.get("ior" + str(x), 0.0))
        ior.append(get_ior if get_ior != 0.0 else 1.0)

        # Element type
        get_t = int(data.get("t" + str(x), 0))
        t.append(get_t)

        # Rotation (for anamorphic elements)
        if get_t == 0:
            rot.append(0.0)
        else:
            rot.append(float(data.get("rot" + str(x), 0.0)) * unit_scale)

        # Abbe number (for chromatic dispersion)
        V.append(float(data.get("V" + str(x), 0.0)))

    # Count surfaces and total lens length
    lenses = 0
    lens_length = 0.0
    for x in range(len(r)):
        lens_length += d[x]
        if r[x] != 0.0:
            lenses += 1
        else:
            break
    lenses = int(lenses / 2)

    # Rack focus
    rack_focus_idx = int(data.get("rack focus idx", 0))
    if rack_focus_idx > 0:
        rack_focus = rack_focus_factor * 0.001  # user value in mm
        lens_length += rack_focus
        d_idx = (rack_focus_idx * 2) - 1
        d[d_idx] += rack_focus

    # Rack focus groups (up to 5)
    rack_focus_data = []
    for i in range(1, 6):
        prefix = "rack focus" + add_leading_zero(i)
        idx = int(data.get(prefix + " idx", 0))
        rmin = float(data.get(prefix + " min", 0.0)) * unit_scale
        rmax = float(data.get(prefix + " max", 0.0)) * unit_scale
        rack_focus_data.append({"idx": idx, "min": rmin, "max": rmax})

        if idx > 0:
            amount = lerp(rmin, rmax, rack_focus_factor)
            d_i = (idx * 2) - 1
            d[d_i] += amount
            lens_length += amount

    # Zoom groups (up to 6)
    zoom_data = []
    for i in range(1, 7):
        prefix = "zoom" + add_leading_zero(i)
        idx = int(data.get(prefix + " idx", 0))
        zmin = float(data.get(prefix + " min", 0.0)) * unit_scale
        zmax = float(data.get(prefix + " max", 0.0)) * unit_scale
        zoom_data.append({"idx": idx, "min": zmin, "max": zmax})

        if idx > 0:
            amount = lerp(zmin, zmax, zoom_factor)
            d_i = (idx * 2) - 1
            d[d_i] += amount
            lens_length += amount

    # Aperture
    aperture_idx = int(data.get("aperture idx", 0))
    aperture_r = float(data.get("aperture r", 0.0)) * unit_scale * aperture_factor
    aperture_d = float(data.get("aperture d", 0.0)) * unit_scale

    # Add aperture distance to spacing
    if aperture_idx != 0:
        d[(aperture_idx * 2) - 1] += aperture_d
        lens_length += aperture_d

    # Absolute aperture position from rear
    aperture_d_abs = aperture_d + lens_length
    for i in range(aperture_idx * 2):
        aperture_d_abs -= d[i]

    # Focus calibration samples
    focus_sample_h = [
        float(data.get("focus sample h", 0.0)),
        float(data.get("focus sample d min", 0.0)),
        float(data.get("focus sample h to max", 0.0)),
        float(data.get("focus sample d max", 0.0)),
    ]

    # Additional focus samples (multi-point calibration)
    focus_samples = []
    for i in range(1, 5):
        prefix = "focus sample h " + add_leading_zero(i)
        h = float(data.get(prefix, 0.0))
        h_to_max = float(data.get(prefix + " to max", 0.0))
        focus_samples.append({"h": h, "h_to_max": h_to_max})

    # Sensor offset
    sensor_offset = [
        float(data.get("sensor offset", 0.0)),
        float(data.get("sensor offset d min", 0.0)),
        float(data.get("sensor offset to max", 0.0)),
        float(data.get("sensor offset d max", 0.0)),
    ]

    # Aspherical surface data
    asphere_data = []
    for i in range(1, MAX_ASPHERE_SURFACES + 1):
        idx_key = "asphere surface idx " + add_leading_zero(i)
        surface_idx = int(data.get(idx_key, 0))
        if surface_idx > 0:
            k = float(data.get("K " + add_leading_zero(i), 0.0))
            coefficients = []
            for j in range(1, MAX_ASPHERE_CONIC_CONSTANTS + 1):
                exp_val = float(data.get("C" + str(j) + " exponent " + add_leading_zero(i), 0.0))
                coeff = float(data.get("C" + str(j) + " " + add_leading_zero(i), 0.0))
                coefficients.append(coeff * math.pow(10, exp_val))
            asphere_data.append({
                "surface_idx": surface_idx,
                "k": k,
                "coefficients": coefficients,
            })

    # IOR lens group correction
    # Handles cemented groups where adjacent surfaces share a radius
    ior_lens_grp_correction = []
    is_prev_lens_grp = False
    for i in range(0, lenses * 2):
        d1 = d[i]
        r1 = r[i]
        r2 = r[i + 1] if i + 1 < len(r) else 0.0

        if abs(r2 - r1) < 0.0001 and d1 == 0.0:
            ior_lens_grp_correction.append({"ior": 1.0, "is_group": True})
            is_prev_lens_grp = True
        else:
            if is_prev_lens_grp:
                grp_idx = int(i / 2)
                prev_idx = grp_idx - 1
                if prev_idx >= 0 and ior[prev_idx] != 0.0:
                    ior_lens_grp_correction.append({
                        "ior": ior[grp_idx] / ior[prev_idx],
                        "is_group": True
                    })
                else:
                    ior_lens_grp_correction.append({"ior": ior[grp_idx], "is_group": False})
            else:
                ior_lens_grp_correction.append({"ior": ior[int(i / 2)], "is_group": False})
            is_prev_lens_grp = False

    # Default sensor size
    default_sensor_size = float(data.get("default sensor size", 100.0))
    if default_sensor_size > 1.0:
        default_sensor_size *= 0.001  # mm to meters

    # Ray guiding calibration data
    ray_guiding = {
        "ray_spread": float(data.get("ray spread", 0.0)),
        "ray_spread_500m": float(data.get("ray spread 500m", 0.0)),
        "ray_spread_near": float(data.get("ray spread < 1m", 0.0)),
        "ray_edge_angle": float(data.get("ray edge angle", 0.0)),
        "ray_edge_angle_500m": float(data.get("ray edge angle 500m", 0.0)),
        "ray_edge_angle_near": float(data.get("ray edge angle < 1m", 0.0)),
        "ray_guiding_spread": float(data.get("ray guiding spread", 0.0)),
        "ramp_coverage": float(data.get("ray guiding guide coverage", 0.0)),
        "ramp_v1": float(data.get("ray guiding guide rampv1", 0.0)),
        "ramp_v2": float(data.get("ray guiding guide rampv2", 0.0)),
        "ramp_v3": float(data.get("ray guiding guide rampv3", 0.0)),
        "ramp_v4": float(data.get("ray guiding guide rampv4", 0.0)),
        "ramp_v5": float(data.get("ray guiding guide rampv5", 0.0)),
        "focus_shift_500m": float(data.get("ray guiding focus shift 500m", 0.0)),
        "focus_shift_near": float(data.get("ray guiding focus shift < 1m", 0.0)),
    }

    # Focus/sensor position calibration
    f_s_pos_near = float(data.get("f s pos near", 0.0))
    f_s_pos_near_m = float(data.get("f s pos near m", 0.0))
    f_s_pos_start = float(data.get("f s pos start", 0.0))
    f_s_pos_end = float(data.get("f s pos end", 0.0))

    # Other metadata
    f_number = float(data.get("f number", 2.8))
    image_scale_ref = float(data.get("image scale ref", 0.0))

    # Lens info
    lens_info = data.get("lens info", "")
    lens_link = data.get("lens link", "")
    lens_patent = data.get("lens patent", "")
    lens_year = data.get("lens year", "")

    return {
        "lenses": lenses,
        "lens_length": lens_length,
        "r": r,
        "d": d,
        "ior": ior,
        "t": t,
        "dia": dia,
        "rot": rot,
        "V": V,
        "rack_focus_idx": rack_focus_idx,
        "aperture_idx": aperture_idx,
        "aperture_r": aperture_r,
        "aperture_d": aperture_d,
        "aperture_d_abs": aperture_d_abs,
        "rack_focus_data": rack_focus_data,
        "zoom_data": zoom_data,
        "focus_sample_h": focus_sample_h,
        "focus_samples": focus_samples,
        "sensor_offset": sensor_offset,
        "asphere_data": asphere_data,
        "ior_lens_grp_correction": ior_lens_grp_correction,
        "default_sensor_size": default_sensor_size,
        "unit_scale": unit_scale,
        "ray_guiding": ray_guiding,
        "f_s_pos_near": f_s_pos_near,
        "f_s_pos_near_m": f_s_pos_near_m,
        "f_s_pos_start": f_s_pos_start,
        "f_s_pos_end": f_s_pos_end,
        "f_number": f_number,
        "image_scale_ref": image_scale_ref,
        "lens_info": lens_info,
        "lens_link": lens_link,
        "lens_patent": lens_patent,
        "lens_year": lens_year,
        "raw_data": data,
    }


def list_available_lenses(lenses_dir):
    """List all available lens files in a directory.

    Args:
        lenses_dir: Path to directory containing .txt lens files

    Returns:
        list of (filename, display_name) tuples sorted by name
    """
    lenses = []
    if os.path.exists(lenses_dir):
        for f in os.listdir(lenses_dir):
            if f.endswith(".txt"):
                display_name = f[:-4]  # Remove .txt extension
                lenses.append((f, display_name))
    lenses.sort(key=lambda x: x[1])
    return lenses


# ============================================================================
# 2D Ray Tracer for Focus Calibration
# Computes sensor position from focus distance by tracing a ray through the
# lens system. This runs at code-generation time, NOT in the shader.
# Uses plain Python math (no numpy required).
# ============================================================================

def _v3(a, b, c):
    return [a, b, c]

def _v3_dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def _v3_length(v):
    return math.sqrt(_v3_dot(v, v))

def _v3_normalize(v):
    l = _v3_length(v)
    if l < 1e-12:
        return [0.0, 0.0, 0.0]
    return [v[0]/l, v[1]/l, v[2]/l]

def _v3_sub(a, b):
    return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]

def _v3_add(a, b):
    return [a[0]+b[0], a[1]+b[1], a[2]+b[2]]

def _v3_scale(v, s):
    return [v[0]*s, v[1]*s, v[2]*s]

def _v3_neg(v):
    return [-v[0], -v[1], -v[2]]

def _ray_plane_intersect(ray_origin, ray_direction, plane_normal, plane_point):
    denom = _v3_dot(ray_direction, plane_normal)
    if abs(denom) < 0.0001:
        return [0.0, 0.0, 0.0]
    t = _v3_dot(_v3_sub(plane_point, ray_origin), plane_normal) / denom
    return _v3_add(ray_origin, _v3_scale(ray_direction, t))

def _line_sphere_intersect(p0, p1, center, radius, hit_idx, inside):
    """Ray-sphere intersection in 3D (matching Blender's lineSphereIntersect).
    center is a 3D point. Returns (hit, new_p0, surface_n)."""
    d = p1
    f = _v3_sub(p0, center)

    a = _v3_dot(d, d)
    b = 2.0 * _v3_dot(f, d)
    c = _v3_dot(f, f) - radius * radius

    discriminant = b * b - 4.0 * a * c
    if discriminant < 0:
        return (0, p0, [0.0, 0.0, 0.0])

    sq = math.sqrt(discriminant)
    t1 = (-b - sq) / (2.0 * a)
    t2 = (-b + sq) / (2.0 * a)

    t = t1 if hit_idx == 0 else t2
    new_p0 = _v3_add(p0, _v3_scale(d, t))

    surface_n = _v3_normalize(_v3_sub(new_p0, center))
    if hit_idx == 1:
        surface_n = _v3_neg(surface_n)
    if inside == 1:
        surface_n = _v3_neg(surface_n)

    return (1, new_p0, surface_n)

def _refract_vec(incident, normal, eta, inside):
    """Snell's law vector refraction. Returns refracted direction or None on TIR."""
    _eta = eta if eta != 0.0 else 1.0
    n = normal[:]
    if inside:
        n = _v3_neg(n)
    else:
        _eta = 1.0 / _eta

    cos_i = _v3_dot(n, incident)
    k = 1.0 - _eta * _eta * (1.0 - cos_i * cos_i)
    if k < 0.0:
        return None  # TIR
    scale = _eta * cos_i + math.sqrt(k)
    return _v3_sub(_v3_scale(incident, _eta), _v3_scale(n, scale))

def _lens_trace_forward(lens_data):
    """Forward trace through lens elements (object -> image direction).
    Used internally by calc_sensor_pos. Returns function that traces a ray.

    The coordinate system matches Blender's Python tracer:
    - x-axis is the optical axis
    - Lens starts at x = -lens_length
    - Light travels from negative x to positive x

    Critical: distance accumulation (_d) happens AFTER each surface trace,
    matching the original Blender code exactly.
    """
    lenses = lens_data["lenses"]
    r = lens_data["r"]
    d = lens_data["d"]
    ior_list = lens_data["ior"]
    dia = lens_data["dia"]
    lens_length = lens_data["lens_length"]
    unit_scale = lens_data["unit_scale"]

    def trace(ray_p, ray_n):
        """Trace ray forward. Returns (hit, final_p, final_n)."""
        _d = -lens_length / unit_scale  # Work in lens units (mm)
        _ray_p = [ray_p[0], ray_p[1], ray_p[2]]
        _ray_n = [ray_n[0], ray_n[1], ray_n[2]]

        for lens_idx in range(lenses):
            r1 = r[lens_idx * 2] / unit_scale
            r2 = r[(lens_idx * 2) + 1] / unit_scale

            d1 = d[lens_idx * 2] / unit_scale
            d2 = d[(lens_idx * 2) + 1] / unit_scale

            dia1 = dia[lens_idx * 2] / unit_scale
            dia2 = dia[(lens_idx * 2) + 1] / unit_scale

            if dia1 >= 100000.0:
                dia1 = dia2
            if dia2 >= 100000.0:
                dia2 = dia1

            ior = ior_list[lens_idx]
            if ior == 0:
                break
            if r1 == 0 or r2 == 0:
                break

            # Surface 1: trace_backwards=0, inside=0
            # hit_idx: 0 if r > 0 (near hit), 1 if r < 0 (far hit)
            hit_idx = 1 if r1 < 0 else 0

            # Sphere center BEFORE adding d1 (original code order)
            lens_center = _v3(_d + r1, 0.0, 0.0)
            hit, _ray_p, surface_n = _line_sphere_intersect(
                _ray_p, _ray_n, lens_center, r1, hit_idx, 0  # inside=0 for surface 1
            )

            if not hit:
                return (0, _ray_p, _ray_n)

            # Diameter check
            if math.sqrt(_ray_p[1]**2 + _ray_p[2]**2) > dia1 / 2:
                return (0, _ray_p, _ray_n)

            # Refract at surface 1 (inside=0 — entering glass)
            new_dir = _refract_vec(_ray_n, surface_n, ior, 0)
            if new_dir is None:
                return (0, _ray_p, _ray_n)
            _ray_n = new_dir

            # Accumulate d1 AFTER surface 1
            _d += d1

            # Surface 2: trace_backwards=0, inside=1
            hit_idx2 = 1 if r2 < 0 else 0

            lens_center2 = _v3(_d + r2, 0.0, 0.0)
            hit, _ray_p, surface_n = _line_sphere_intersect(
                _ray_p, _ray_n, lens_center2, r2, hit_idx2, 1  # inside=1 for surface 2
            )

            if not hit:
                return (0, _ray_p, _ray_n)

            # Diameter check
            if math.sqrt(_ray_p[1]**2 + _ray_p[2]**2) > dia2 / 2:
                return (0, _ray_p, _ray_n)

            # Refract at surface 2 (inside=1 — exiting glass)
            new_dir = _refract_vec(_ray_n, surface_n, ior, 1)
            if new_dir is None:
                return (0, _ray_p, _ray_n)
            _ray_n = new_dir

            # Accumulate d2 AFTER surface 2
            _d += d2

            # Check if ray is going sideways
            if abs(_ray_n[0]) < 0.001:
                return (0, _ray_p, _ray_n)

        return (1, _ray_p, _ray_n)

    return trace


def calc_sensor_pos_from_focus(lens_data, reference_distance, focus_sample_h_override=None):
    """Compute sensor position for a given focus distance by ray tracing.

    Traces a ray from the focus distance through the lens system and finds
    where it converges on the optical axis.

    Args:
        lens_data: Parsed lens data dict from get_lens_data()
        reference_distance: Focus distance in meters
        focus_sample_h_override: Override for ray height sampling factor

    Returns:
        float: Sensor position in meters (0.0 if trace fails)
    """
    unit_scale = lens_data["unit_scale"]
    lens_length = lens_data["lens_length"] / unit_scale  # In lens units

    # Ray height on first lens surface
    diameter = lens_data["dia"][0] / unit_scale * 0.5
    focus_sample_h = lens_data["focus_sample_h"][0]
    if focus_sample_h == 0.0:
        focus_sample_h = 100.0

    if focus_sample_h_override is not None and focus_sample_h_override != 0.0:
        focus_sample_h = focus_sample_h_override

    ray_h = diameter / focus_sample_h

    # Reference distance in lens units
    ref_dist = reference_distance / unit_scale

    # Set up ray from focus point aimed at lens entry
    ray_lens_p = _v3(-lens_length, ray_h, 0.0)
    ray_p = _v3(-ref_dist, 0.0, 0.0)

    ray_n = _v3_sub(ray_lens_p, ray_p)
    ray_n = _v3_normalize(ray_n)

    # Move ray_p one unit back from lens entry
    ray_p = _v3_sub(ray_lens_p, ray_n)

    # Forward trace
    trace_fn = _lens_trace_forward(lens_data)
    hit, final_p, final_n = trace_fn(ray_p, ray_n)

    if not hit:
        return 0.0

    # Find where the output ray crosses the optical axis (y=0 plane)
    axis_point = _ray_plane_intersect(
        final_p, final_n,
        _v3(0.0, 1.0, 0.0),  # plane normal (perpendicular to optical axis)
        _v3(0.0, 0.0, 0.0)   # plane point (origin)
    )

    return axis_point[0] * unit_scale  # Back to meters


def exponential_scale(n_points=100, min_value=0.0, max_value=1000.0, exp_factor=5.0):
    """Generate exponentially spaced values (matching LentilKarma's scale).

    Denser at the beginning (near focus), sparser at far distances.
    """
    values = []
    for i in range(n_points):
        x = i / (n_points - 1)
        y = (math.exp(x * exp_factor) - 1) / (math.exp(exp_factor) - 1)
        value = y * max_value
        if min_value != 0.0:
            value = lerp(min_value, max_value, y)
        values.append(value)
    return values


def generate_focus_lut(lens_data, n_points=200, max_distance=500.0):
    """Generate a focus distance → sensor position lookup table.

    Traces rays through the lens for exponentially-spaced focus distances
    and returns parallel arrays for VEX baking.

    Args:
        lens_data: Parsed lens data dict
        n_points: Number of LUT samples (default 200)
        max_distance: Maximum focus distance in meters

    Returns:
        tuple: (focus_distances, sensor_positions) — parallel float lists
    """
    lens_length_m = lens_data["lens_length"]

    # Exponentially spaced distances (dense near, sparse far)
    focus_distances = exponential_scale(
        n_points=n_points,
        min_value=lens_length_m,
        max_value=max_distance,
        exp_factor=10.0
    )

    focus_sample_h = lens_data["focus_sample_h"][0]
    if focus_sample_h == 0.0:
        focus_sample_h = 1.3  # Reasonable default

    sensor_positions = []
    for dist in focus_distances:
        sp = -calc_sensor_pos_from_focus(lens_data, dist, focus_sample_h)
        sensor_positions.append(sp)

    # Remove entries where trace failed (sensor_pos == 0.0)
    clean_dists = []
    clean_positions = []
    for i in range(len(focus_distances)):
        if sensor_positions[i] != 0.0:
            clean_dists.append(focus_distances[i])
            clean_positions.append(sensor_positions[i])

    return (clean_dists, clean_positions)


def abbe_to_cauchy(ior, V):
    """Convert IOR and Abbe number to Cauchy dispersion coefficients.

    The Cauchy equation: n(lambda) = A + B/lambda^2
    where lambda is in micrometers.

    Args:
        ior: Refractive index at d-line (587.56nm)
        V: Abbe number

    Returns:
        tuple: (A, B) Cauchy coefficients
    """
    if V == 0.0:
        return (ior, 0.0)

    # Wavelengths in micrometers
    lambda_d = 0.58756  # d-line (sodium)
    lambda_F = 0.48613  # F-line (hydrogen)
    lambda_C = 0.65627  # C-line (hydrogen)

    # From Abbe number definition: V = (n_d - 1) / (n_F - n_C)
    # And Cauchy: n = A + B/lambda^2
    # B = (n_d - 1) / (V * (1/lambda_F^2 - 1/lambda_C^2))
    # A = n_d - B/lambda_d^2

    B = (ior - 1.0) / (V * (1.0 / (lambda_F ** 2) - 1.0 / (lambda_C ** 2)))
    A = ior - B / (lambda_d ** 2)

    return (A, B)


def wavelength_to_rgb(wavelength):
    """Convert wavelength in nm to approximate RGB.

    Based on Dan Bruton's algorithm, matching the Blender version.
    """
    r = g = b = 0.0

    if 380.0 <= wavelength < 440.0:
        r = -(wavelength - 440.0) / (440.0 - 380.0)
        b = 1.0
    elif 440.0 <= wavelength < 490.0:
        g = (wavelength - 440.0) / (490.0 - 440.0)
        b = 1.0
    elif 490.0 <= wavelength < 510.0:
        g = 1.0
        b = -(wavelength - 510.0) / (510.0 - 490.0)
    elif 510.0 <= wavelength < 580.0:
        r = (wavelength - 510.0) / (580.0 - 510.0)
        g = 1.0
    elif 580.0 <= wavelength < 645.0:
        r = 1.0
        g = -(wavelength - 645.0) / (645.0 - 580.0)
    elif 645.0 <= wavelength <= 780.0:
        r = 1.0

    # Intensity falloff at edges
    if 380.0 <= wavelength < 420.0:
        factor = 0.3 + 0.7 * (wavelength - 380.0) / (420.0 - 380.0)
    elif 420.0 <= wavelength <= 700.0:
        factor = 1.0
    elif 700.0 < wavelength <= 780.0:
        factor = 0.3 + 0.7 * (780.0 - wavelength) / (780.0 - 700.0)
    else:
        factor = 0.0

    return (r * factor, g * factor, b * factor)


# Quick self-test when run directly
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        # Default test file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        filepath = os.path.join(script_dir, "..", "..", "LentilKarma_Data", "lenses",
                                "100mm f1.4 W Merte 1928 Baltar.txt")

    if os.path.exists(filepath):
        lens = get_lens_data(filepath)
        print(f"Lens: {os.path.basename(filepath)}")
        print(f"  Elements: {lens['lenses']}")
        print(f"  Lens length: {lens['lens_length'] * 1000:.2f}mm")
        print(f"  F-number: f/{lens['f_number']}")
        print(f"  Aperture idx: {lens['aperture_idx']}")
        print(f"  Aperture radius: {lens['aperture_r'] * 1000:.2f}mm")
        print(f"  Sensor size: {lens['default_sensor_size'] * 1000:.2f}mm")
        print(f"  Unit scale: {lens['unit_scale']}")
        print(f"  Aspheric surfaces: {len(lens['asphere_data'])}")
        print(f"  Surfaces (r != 0):")
        for i in range(lens['lenses'] * 2):
            if lens['r'][i] != 0.0:
                print(f"    r{i+1}={lens['r'][i]*1000:.3f}mm  d{i+1}={lens['d'][i]*1000:.3f}mm  dia{i+1}={lens['dia'][i]*1000:.1f}mm")
        print(f"  IOR per group:")
        for i in range(lens['lenses']):
            print(f"    ior{i+1}={lens['ior'][i]:.5f}  V{i+1}={lens['V'][i]:.1f}")
        print(f"  Ray guiding:")
        rg = lens['ray_guiding']
        print(f"    spread={rg['ray_spread']:.4f}  edge_angle={rg['ray_edge_angle']:.1f}")
    else:
        print(f"File not found: {filepath}")
