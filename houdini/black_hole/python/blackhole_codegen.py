"""
Black Hole CVEX Lens Shader — VFL Code Generator

Generates a Karma-compatible CVEX lens shader that implements gravitational
lensing via Euler-integrated ray marching around a Schwarzschild black hole.

The physics is extracted from Matt Ebb's gravitational lensing VOP network
(CC-BY 3.0), rebuilt as a flat VFL shader for Karma's CVEX lens interface.

Portable features (pure VEX math):
  - Gravitational ray march with adaptive step size
  - Schwarzschild event horizon (d < 0.5 * mass -> black)
  - Derivative tracking (dPds/dPdt) for environment map texture filtering
  - Environment map sampling with VEX environment()
  - Star field rendering via point cloud + motion blur

Non-portable features (Mantra-only, NOT included):
  - Accretion disc ray tracing (rayhittest / trace)
  - Surface shading (pbrlighting / computelighting)
  - AOV exports (direct, indirect, diffuse, specular, etc.)
"""

import os


def generate_vfl_shader(output_filepath=None):
    """Generate the black hole CVEX lens shader VFL source.

    Args:
        output_filepath: Path to write the .vfl file (optional)

    Returns:
        str: The generated VFL source code
    """
    lines = []
    lines.append(_header())
    lines.append(_pragmas())
    lines.append(_function_signature())
    lines.append(_camera_ray_setup())
    lines.append(_ray_march_loop())
    lines.append(_environment_sampling())
    lines.append(_star_rendering())
    lines.append(_final_output())
    lines.append("}")  # close cvex function

    source = "\n".join(lines)

    if output_filepath:
        os.makedirs(os.path.dirname(output_filepath), exist_ok=True)
        with open(output_filepath, 'w') as f:
            f.write(source)

    return source


def _header():
    return """// Black Hole CVEX Lens Shader — Auto-generated
// Gravitational lensing via Schwarzschild ray marching
// Target: Houdini 20.5+ Karma CPU
//
// Based on gravitational lensing by Matt Ebb (CC-BY 3.0)
// https://mattebb.com
//
// Galaxy environment maps: ESO/S. Brunier (CC-BY 4.0)
// https://www.eso.org/public/images/eso0932a/
//
// DO NOT EDIT — regenerate via blackhole_codegen.py
"""


def _pragmas():
    return """#pragma opname      blackhole_lens
#pragma oplabel     "Black Hole Lens"
#pragma opmininputs 0
#pragma opmaxinputs 0

// Hidden CVEX context inputs (auto-bound by Karma)
#pragma hint x invisible
#pragma hint y invisible
#pragma hint Time invisible
#pragma hint dofx invisible
#pragma hint dofy invisible
#pragma hint aspect invisible
#pragma hint P invisible
#pragma hint I invisible
#pragma hint tint invisible

// Singularity position (typically linked to a null object)
#pragma hint  singularity_pos hidden

// Black hole parameters
#pragma label mass "Black Hole Mass"
#pragma range mass 0.001 1.0
#pragma label maxsteps "Max Steps"
#pragma range maxsteps 1 500
#pragma label stepsize "Step Size"
#pragma range stepsize 0.01 10.0

// Environment map
#pragma label env_map "Environment Map"
#pragma hint  env_map file
#pragma label env_map_mask "Environment Mask"
#pragma hint  env_map_mask file
#pragma label env_intensity "Env Intensity"
#pragma range env_intensity 0.0 10.0
#pragma label env_blur "Env Blur"
#pragma range env_blur 0.0 1.0

// Star rendering
#pragma label star_file "Star Point Cloud"
#pragma hint  star_file file
#pragma label star_intensity "Star Intensity"
#pragma range star_intensity 0.0 50.0
#pragma label star_size "Star Size"
#pragma range star_size 0.0001 0.01
#pragma label star_blur "Motion Blur Amount"
#pragma range star_blur 0.0 1.0

// Camera position (world space — for world-to-camera-space transform)
#pragma label camera_pos "Camera Position (World)"

// Camera overrides
#pragma label focal_length "Focal Length"
#pragma label horizontal_aperture "Horizontal Aperture"
"""


def _function_signature():
    return """
#include "math.h"

cvex blackhole_lens(
    // CVEX lens shader standard I/O (provided by Karma)
    float x = 0;
    float y = 0;
    float Time = 0;
    float dofx = 0;
    float dofy = 0;
    float aspect = 1;
    export vector P = {0, 0, 0};
    export vector I = {0, 0, 0};
    export vector tint = {1, 1, 1};

    // Black hole parameters (world space)
    vector singularity_pos = {0, 0, 0};
    vector camera_pos = {0, 0, 10};
    float mass = 0.04;
    int maxsteps = 200;
    float stepsize = 1.0;

    // Environment map
    string env_map = "";
    string env_map_mask = "";
    float env_intensity = 1.0;
    float env_blur = 0.0;

    // Star rendering
    string star_file = "";
    float star_intensity = 10.0;
    float star_size = 0.002;
    float star_blur = 0.5;

    // Camera params (passthrough for viewport)
    float focal_length = 50.0;
    float horizontal_aperture = 41.4214;
)
{"""


def _camera_ray_setup():
    return """
    // ---------------------------------------------------------------
    // 1. Camera ray setup: NDC -> camera-space ray
    //    Same convention as kma_physicallens / lentilkarma CVEX shaders.
    //    x, y are [-1, 1] NDC from Karma. We build a perspective ray.
    // ---------------------------------------------------------------
    float vert_aperture = horizontal_aperture * 9.0 / 16.0;
    float aspect_ratio = horizontal_aperture / vert_aperture;
    float fov_x = 2.0 * atan(horizontal_aperture / (2.0 * focal_length));
    float half_tan = tan(fov_x * 0.5);

    // Camera-space ray origin and direction
    vector cam_P = {0, 0, 0};
    vector cam_I = normalize(set(
        half_tan * x,
        half_tan * y / aspect_ratio,
        -1.0
    ));

    // ---------------------------------------------------------------
    // Transform singularity from WORLD space to CAMERA space.
    // CVEX lens shaders operate in camera space (camera at origin,
    // looking down -Z). The user provides singularity_pos and
    // camera_pos in world space. We subtract to get the offset.
    //
    // NOTE: This handles translation only, not camera rotation.
    // For a camera looking down -Z world (default), this is exact.
    // For rotated cameras, link camera_pos to the camera's translate
    // or set it manually.
    // ---------------------------------------------------------------
    vector sing_cs = singularity_pos - camera_pos;

    // In CVEX lens context, P and I are in camera space.
    // The ray starts at the camera origin and points into the scene.
    vector p = cam_P;
    vector ray_dir = cam_I;

    // Derivative tracking for texture filtering (dPds/dPdt).
    float pixel_offset = 2.0 / 1920.0;  // ~1 pixel in NDC at 1920px width

    vector p_s = cam_P;
    vector p_t = cam_P;
    vector i_s = normalize(set(
        half_tan * (x + pixel_offset),
        half_tan * y / aspect_ratio,
        -1.0
    ));
    vector i_t = normalize(set(
        half_tan * x,
        half_tan * (y + pixel_offset) / aspect_ratio,
        -1.0
    ));
"""


def _ray_march_loop():
    return """
    // ---------------------------------------------------------------
    // 2. Gravitational lensing ray march
    //    Euler integration of photon trajectory in Schwarzschild metric.
    //    Force = mass / d^2 toward singularity (Newtonian approx).
    //    Adaptive step size: dt = min(1, 0.01 * d^2 / mass) * stepsize
    // ---------------------------------------------------------------
    float rs = 0.5 * mass;                      // Schwarzschild radius
    float ds = distance(p, sing_cs);    // Initial distance to BH
    float dt_step = 1.0;
    float maxdist = ds * 5.0;                   // Escape distance

    int escaped = 0;
    int absorbed = 0;

    for (int st = 0; st < maxsteps; st++) {
        // Gravitational force toward singularity
        vector dp = sing_cs - p;
        float d = length(dp);
        vector force = normalize(dp) * mass / (d * d);

        // Derivative forces (for dPds / dPdt tracking)
        vector dp_s = sing_cs - p_s;
        float d_s = length(dp_s);
        vector force_s = normalize(dp_s) * (mass / (d_s * d_s));

        vector dp_t = sing_cs - p_t;
        float d_t = length(dp_t);
        vector force_t = normalize(dp_t) * (mass / (d_t * d_t));

        // Adaptive step size: smaller near the singularity
        dt_step = min(1.0, 0.01 * ((d * d) / mass));
        dt_step *= stepsize;

        // Event horizon check
        if (d < rs) {
            absorbed = 1;
            tint = {0, 0, 0};
            break;
        }

        // Escape check: ray has moved far enough from the black hole
        if (distance(p, cam_P) > maxdist) {
            escaped = 1;
            break;
        }

        // Euler integration step
        ray_dir += force * dt_step;
        ray_dir = normalize(ray_dir);
        p += ray_dir * dt_step;

        // Derivative ray integration (parallel tracking)
        i_s += force_s * dt_step;
        i_s = normalize(i_s);
        p_s += i_s * dt_step;

        i_t += force_t * dt_step;
        i_t = normalize(i_t);
        p_t += i_t * dt_step;
    }

    // If we ran out of steps without escaping or being absorbed,
    // treat as escaped (ray bent but passed through)
    if (!escaped && !absorbed) {
        escaped = 1;
    }
"""


def _environment_sampling():
    return """
    // ---------------------------------------------------------------
    // 3. Environment map sampling (escaped rays only)
    //    Uses VEX environment() with 4-corner area sampling matching
    //    the original shader. The four direction vectors define a
    //    quadrilateral on the environment sphere for filtered lookup.
    //    Original: environment(map, dir, dir_ds, dir_dsdt, dir_dsdt)
    // ---------------------------------------------------------------
    vector env_color = {0, 0, 0};

    if (escaped && env_map != "") {
        // Compute the 4 corners of the warped pixel footprint
        // dir = primary ray, i_s = S-offset ray, i_t = T-offset ray
        vector dIds = i_s - ray_dir;       // direction delta in S
        vector dIdt = i_t - ray_dir;       // direction delta in T
        vector dir_dsdt = ray_dir + dIds + dIdt;  // diagonal corner

        if (env_blur > 0.0) {
            // Expand the pixel footprint for user-controlled blur
            float blur_scale = 1.0 + env_blur * 10.0;
            vector expanded_ds = ray_dir + dIds * blur_scale;
            vector expanded_dt = ray_dir + dIdt * blur_scale;
            dir_dsdt = ray_dir + dIds * blur_scale + dIdt * blur_scale;
            env_color = environment(env_map,
                ray_dir, expanded_ds, dir_dsdt, expanded_dt);
        } else {
            // 4-corner area sampling (matches original exactly)
            env_color = environment(env_map,
                ray_dir, i_s, dir_dsdt, i_t);
        }
        env_color *= env_intensity;

        // Apply environment mask (if provided)
        if (env_map_mask != "") {
            vector mask_color;
            if (env_blur > 0.0) {
                float blur_scale = 1.0 + env_blur * 10.0;
                vector expanded_ds = ray_dir + dIds * blur_scale;
                vector expanded_dt = ray_dir + dIdt * blur_scale;
                dir_dsdt = ray_dir + dIds * blur_scale + dIdt * blur_scale;
                mask_color = environment(env_map_mask,
                    ray_dir, expanded_ds, dir_dsdt, expanded_dt);
            } else {
                mask_color = environment(env_map_mask,
                    ray_dir, i_s, dir_dsdt, i_t);
            }
            // Mask is grayscale — invert (original: mask = 1 - alpha)
            float mask_val = 1.0 - mask_color.x;
            env_color *= mask_val;
        }
    }
"""


def _star_rendering():
    return """
    // ---------------------------------------------------------------
    // 4. Star field rendering (escaped rays only)
    //    Matches the original Matt Ebb algorithm:
    //    1. Convert warped ray directions to polar coordinates
    //    2. Build pixel footprint polygon from derivative rays
    //    3. Compute convex hull (Jarvis march / gift wrapping)
    //    4. Use pcfind to find candidate stars in polar space
    //    5. Point-in-polygon test for each star
    //    6. Scale luminance by area ratio (pixel_area / footprint_area)
    //
    //    Stars are stored in the point cloud in polar coordinates
    //    with Cd (color) attributes. Use a SOP to convert star
    //    positions to polar: set(atan2(P.x, P.z), acos(P.y/length(P)), 0)
    // ---------------------------------------------------------------
    vector star_color = {0, 0, 0};

    if (escaped && star_file != "") {
        // --- Convert directions to polar coordinates ---
        // topolar: (theta=azimuth, phi=elevation, 0)
        vector dir_n = normalize(ray_dir);
        vector polar_dir = set(atan2(dir_n.x, dir_n.z),
                               acos(clamp(dir_n.y, -1.0, 1.0)), 0.0);

        vector ds_n = normalize(i_s);
        vector polar_ds = set(atan2(ds_n.x, ds_n.z),
                              acos(clamp(ds_n.y, -1.0, 1.0)), 0.0);

        vector dt_n = normalize(i_t);
        vector polar_dt = set(atan2(dt_n.x, dt_n.z),
                              acos(clamp(dt_n.y, -1.0, 1.0)), 0.0);

        // Compute polar offsets (derivative footprint corners)
        vector dIds_polar = polar_ds - polar_dir;
        vector dIdt_polar = polar_dt - polar_dir;

        // Build 4 corners of the pixel footprint in polar space
        // (Without motion blur, 4 corners; with motion blur, the
        //  original uses 8 corners from shutter open + close.
        //  In CVEX lens context, Karma handles motion blur via
        //  multi-sample integration, so we use 4 corners.)
        vector footprint[];
        resize(footprint, 4);
        footprint[0] = polar_dir;
        footprint[1] = polar_dir + dIds_polar;
        footprint[2] = polar_dir + dIds_polar + dIdt_polar;
        footprint[3] = polar_dir + dIdt_polar;

        // --- Compute centroid and search radius ---
        vector centroid = (footprint[0] + footprint[1] +
                           footprint[2] + footprint[3]) * 0.25;
        float searchradius = 0.0;
        for (int fi = 0; fi < 4; fi++) {
            searchradius = max(searchradius,
                               distance(footprint[fi], centroid));
        }
        // Pad search radius to catch stars near the edge
        searchradius *= 1.5;

        // --- Find candidate stars ---
        int pts[] = pcfind(star_file, "P", centroid, searchradius, 32);

        if (len(pts) > 0) {
            // --- Convex hull (Jarvis march / gift wrapping) ---
            // For 4 points this is simple but handles degenerate cases
            // where the warped footprint may be non-convex.
            vector hull[];

            // Find leftmost point
            int left_idx = 0;
            for (int fi = 1; fi < 4; fi++) {
                if (footprint[fi].x < footprint[left_idx].x)
                    left_idx = fi;
            }
            int hull_p = left_idx;
            int hull_count = 0;
            do {
                append(hull, footprint[hull_p]);
                int hull_q = (hull_p + 1) % 4;
                for (int fi = 0; fi < 4; fi++) {
                    // Cross product test: is fi to the right of p->q?
                    float cross_val =
                        (footprint[hull_q].x - footprint[hull_p].x) *
                        (footprint[fi].y - footprint[hull_p].y) -
                        (footprint[hull_q].y - footprint[hull_p].y) *
                        (footprint[fi].x - footprint[hull_p].x);
                    if (cross_val > 1e-15)
                        hull_q = fi;
                }
                hull_p = hull_q;
                hull_count++;
                if (hull_count > 8) break;  // safety limit
            } while (hull_p != left_idx);

            // --- Compute footprint area (shoelace formula) ---
            float left_sum = 0.0, right_sum = 0.0;
            int hull_len = len(hull);
            for (int hi = 0; hi < hull_len; hi++) {
                int hj = (hi + 1) % hull_len;
                left_sum += hull[hi].x * hull[hj].y;
                right_sum += hull[hj].x * hull[hi].y;
            }
            float full_area = 0.5 * abs(left_sum - right_sum);

            // Constant pixel area (matching original)
            float pixel_area = 0.00002;
            float area_scale = pixel_area / max(full_area, 1e-15);

            // --- Test each star against the convex hull ---
            for (int pi = 0; pi < len(pts); pi++) {
                int pt = pts[pi];
                vector star_pt = point(star_file, "P", pt);
                vector star_cd = point(star_file, "Cd", pt);

                // Point-in-convex-polygon test
                int inside = 1;
                for (int hj = 0; hj < hull_len; hj++) {
                    vector src_p = hull[hj];
                    vector next_p = hull[(hj + 1) % hull_len];
                    // Right-side test (same as original)
                    float side = (next_p.x - src_p.x) * (star_pt.y - src_p.y) -
                                 (next_p.y - src_p.y) * (star_pt.x - src_p.x);
                    if (side > 1e-15) {
                        inside = 0;
                        break;
                    }
                }

                if (inside) {
                    star_color += star_cd * area_scale * star_intensity;
                }
            }
        }
    }
"""


def _final_output():
    return """
    // ---------------------------------------------------------------
    // 5. Final output
    //    P = warped ray origin (camera space)
    //    I = warped ray direction (camera space)
    //    tint = color modulation (black for absorbed rays, env+stars for escaped)
    // ---------------------------------------------------------------
    if (absorbed) {
        // Ray fell into event horizon — pure black
        P = cam_P;
        I = cam_I;
        tint = {0, 0, 0};
    } else {
        // Ray escaped — output warped ray with color
        // P stays at camera origin (lens shader convention);
        // I is the warped direction after gravitational bending.
        P = cam_P;
        I = ray_dir;

        // Combine environment and stars into tint
        vector combined = env_color + star_color;
        // If no environment map is loaded, pass through white tint
        // so the regular scene renders through the warped ray
        if (env_map == "" && star_file == "") {
            tint = {1, 1, 1};
        } else {
            tint = combined;
        }
    }
"""


# CLI entry point
if __name__ == "__main__":
    import sys

    output_file = sys.argv[1] if len(sys.argv) > 1 else None
    source = generate_vfl_shader(output_file)

    if output_file:
        print(f"Generated black hole VFL shader: {output_file}")
    else:
        print(source)
