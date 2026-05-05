// LentilKarma Core Optical Functions for VEX/CVEX
// Ported from LentilKarma 3.2.0 Blender OSL camera shader
// Target: Houdini 20.5 Karma CPU CVEX lens shader
//
// These functions implement physically-based ray tracing through
// multi-element optical systems using real lens patent data.

#ifndef LENTILKARMA_CORE_H
#define LENTILKARMA_CORE_H

#define LS_PI 3.14159265358979323846

// ============================================================================
// Utility Functions
// ============================================================================

// Remap value from one range to another (unclamped)
float ls_fit(float value; float oldmin; float oldmax; float newmin; float newmax)
{
    float a = value - oldmin;
    float b = newmax - newmin;
    float c = oldmax - oldmin;
    if (a == 0.0 || b == 0.0 || c == 0.0)
        return newmin;
    return newmin + a * b / c;
}

// Remap value from one range to another (unclamped, no zero-guard)
float ls_efit(float value; float oldmin; float oldmax; float newmin; float newmax)
{
    float t = (value - oldmin) / (oldmax - oldmin);
    return newmin + t * (newmax - newmin);
}

// Remap value from one range to another (clamped to output range)
float ls_fit_clamp(float value; float oldmin; float oldmax; float newmin; float newmax)
{
    if (oldmin == oldmax) return newmin;
    float result = newmin + ((value - oldmin) * (newmax - newmin) / (oldmax - oldmin));
    return max(newmin, min(result, newmax));
}

// Clamped linear interpolation
float ls_lerp_clamp(float a; float b; float t)
{
    float _t = clamp(t, 0.0, 1.0);
    return (1.0 - _t) * a + _t * b;
}

// Sample a point on a disk with given half-angle spread
// N.x and N.y are uniform random numbers in [0,1]
vector ls_sample_disk(float angle; vector N)
{
    float radius = tan(angle);
    float r = sqrt(N.x) * radius;
    float theta = 2.0 * LS_PI * N.y;
    float x = r * cos(theta);
    float y = r * sin(theta);
    return set(x, y, 0.0);
}

// Interpolate ray guiding value based on sensor position
// Interpolates between near/mid/far values based on where the sensor is
float ls_ray_guiding_val(float sensor_pos; float pos01; float pos02; float pos03;
                         float val01; float val02; float val03)
{
    if (-sensor_pos > pos02 && pos01 > 0.0)
        return ls_efit(-sensor_pos, pos01, pos02, val01, val02);
    else
    {
        if (val03 > 0.0)
            return ls_efit(-sensor_pos, pos02, pos03, val02, val03);
        else
            return val02;
    }
}


// ============================================================================
// Core Optical Functions
// ============================================================================

// Ray-plane intersection
// Returns the hit point on the plane, or (0,0,0) if ray is parallel
vector ls_rayPlaneIntersect(vector ray_origin; vector ray_direction;
                            vector plane_normal; vector plane_point)
{
    float denominator = dot(ray_direction, plane_normal);
    if (abs(denominator) > 0.0001)
    {
        float t = dot(plane_point - ray_origin, plane_normal) / denominator;
        return ray_origin + t * ray_direction;
    }
    return set(0.0, 0.0, 0.0);
}


// Ray-sphere intersection
// Modifies p0 (ray origin) to the hit point, computes surface normal.
// p1 is the ray direction (not modified).
// center is the accumulated distance along the optical axis (surface vertex position).
// radius is the signed radius of curvature.
// The sphere center is computed as (0, 0, center - radius).
// T is the throughput vector — set to (0,0,0) on miss.
// hit_idx: 0 = near hit, 1 = far hit
// inside: 1 = ray is inside the sphere (flips normal)
void ls_lineSphereIntersect(vector p0; vector p1; float center; float radius;
                            vector surface_n; vector T; int hit_idx; int inside)
{
    vector _center = set(0.0, 0.0, center - radius);

    float discriminant = 4.0 * dot(p1, p1);
    discriminant *= dot(p0 - _center, p0 - _center) - radius * radius;
    discriminant = (4.0 * dot(p0 - _center, p1) * dot(p0 - _center, p1)) - discriminant;

    if (discriminant < 0.0) { T = set(0.0, 0.0, 0.0); return; }

    float t = -2.0 * dot(p0 - _center, p1);

    if (hit_idx == 0) t -= sqrt(discriminant);
    if (hit_idx == 1) t += sqrt(discriminant);

    t /= (dot(p1, p1) * 2.0);
    p0 += t * p1;

    surface_n = normalize(p0 - _center);

    if (hit_idx == 1) surface_n = -surface_n;
    if (inside == 1) surface_n = -surface_n;
}


// Ray-cylinder intersection (for anamorphic lens elements)
// Modifies origin to the hit point, computes surface normal.
// cylinderAxis is typically (0,1,0) for horizontal anamorphic.
void ls_lineCylinderIntersect(vector origin; vector direction;
                              float cylinderCenter; vector cylinderAxis;
                              float cylinderRadius; vector surface_n;
                              vector T; int hit_idx; int inside)
{
    vector ray = direction;

    vector val1 = dot(ray, cylinderAxis) * cylinderAxis;
    vector val2 = dot(origin - set(0.0, 0.0, cylinderCenter - cylinderRadius), cylinderAxis) * cylinderAxis;
    vector val3 = origin - set(0.0, 0.0, cylinderCenter - cylinderRadius) - val2;

    float a = dot(ray - val1, ray - val1);
    float b = 2.0 * dot(ray - val1, val3);
    float c = dot(val3, val3) - cylinderRadius * cylinderRadius;

    float discriminant = b * b - 4.0 * a * c;

    if (discriminant < 0.0) { T = set(0.0, 0.0, 0.0); return; }

    if (hit_idx == 1) origin = origin + ((-b + sqrt(discriminant)) / (2.0 * a)) * ray;
    if (hit_idx == 0) origin = origin + ((-b - sqrt(discriminant)) / (2.0 * a)) * ray;

    vector cylinderToPoint = origin - set(0.0, 0.0, cylinderCenter - cylinderRadius);
    surface_n = normalize(cylinderToPoint - dot(cylinderToPoint, cylinderAxis) * cylinderAxis);

    if (hit_idx == 1) surface_n = -surface_n;
    if (inside == 1) surface_n = -surface_n;
}


// Aspherical surface sag equation
// Standard even asphere: z = r^2/(R*(1+sqrt(1-(1+k)*r^2/R^2))) + sum(Ci * r^(2i+4))
// coefficients[] contains the polynomial correction terms
// c_idx_start/c_idx_end index into the coefficients array
float ls_asphereEquation(vector _pos; float radius; float k;
                         float coefficients[]; int c_idx_start; int c_idx_end)
{
    float r2 = (_pos[0] * _pos[0]) + (_pos[1] * _pos[1]);

    float base = r2 / (radius * (1.0 + sqrt(1.0 - ((1.0 + k) * r2 / (radius * radius)))));

    float correction = 0.0;
    for (int i = c_idx_start; i < c_idx_end; i++)
    {
        correction += -coefficients[i] * pow(r2, (i - c_idx_start) + 2);
    }

    return base + correction - _pos[2];
}

// Simplified version using full array (no sub-indexing)
float ls_asphereEquationFull(vector _pos; float radius; float k; float coefficients[])
{
    float r2 = (_pos[0] * _pos[0]) + (_pos[1] * _pos[1]);
    float base = r2 / (radius * (1.0 + sqrt(1.0 - ((1.0 + k) * r2 / (radius * radius)))));

    float correction = 0.0;
    int n = len(coefficients);
    for (int i = 0; i < n; i++)
    {
        correction += -coefficients[i] * pow(r2, i + 2);
    }

    return base + correction - _pos[2];
}


// Trace ray through an aspherical lens element using Newton-Raphson
// Modifies rayOrigin to the hit point, computes surface normal.
// Uses the indexed asphere equation for baked coefficient arrays.
void ls_traceAsphericalElement(vector rayOrigin; vector rayDirection;
                               float lensCenter; float radius; float k;
                               float coefficients[]; int c_idx_start; int c_idx_end;
                               vector surface_n; vector _T;
                               int hit_idx; int inside; float unit_scale)
{
    // Scale conversion
    rayOrigin = rayOrigin * (1.0 / unit_scale);
    vector _lensCenter = set(0.0, 0.0, lensCenter) * (1.0 / unit_scale);
    float _radius = -radius * (1.0 / unit_scale); // flipped

    vector _rayDirection = rayDirection;

    float tolerance = 0.0001;
    float epsilon = 0.0005;
    int maxSteps = 4;

    // Translate ray to the lens coordinate system
    vector localRayOrigin = rayOrigin - _lensCenter;

    // Newton-Raphson root finding
    vector hitPoint = set(0.0, 0.0, 0.0);
    int hit = 0;
    float t = 0.0;

    int stop = 0;
    for (int i = 0; i < maxSteps && stop == 0; i++)
    {
        vector currentPos = localRayOrigin + (t * _rayDirection);
        float f = ls_asphereEquation(currentPos, _radius, k, coefficients, c_idx_start, c_idx_end);

        if (abs(f) < tolerance)
        {
            hitPoint = currentPos;
            hit = 1;
            stop = 1;
        }
        else
        {
            // Numerical gradient for Newton's step
            vector grad = set(
                ls_asphereEquation(currentPos + set(epsilon, 0, 0), _radius, k, coefficients, c_idx_start, c_idx_end) - f,
                ls_asphereEquation(currentPos + set(0, epsilon, 0), _radius, k, coefficients, c_idx_start, c_idx_end) - f,
                ls_asphereEquation(currentPos + set(0, 0, epsilon), _radius, k, coefficients, c_idx_start, c_idx_end) - f
            ) / epsilon;
            t -= f / dot(grad, _rayDirection);
        }
    }

    if (hit == 0)
    {
        _T = 0;
        surface_n = set(0.0, 1.0, 0.0);
        rayOrigin = set(100.0, 0.0, 0.0);
        return;
    }

    // Calculate normal at the hit point via numerical gradient
    float solvedEq = ls_asphereEquation(hitPoint, _radius, k, coefficients, c_idx_start, c_idx_end);

    vector _normal = normalize(set(
        ls_asphereEquation(hitPoint + set(epsilon, 0, 0), _radius, k, coefficients, c_idx_start, c_idx_end) - solvedEq,
        ls_asphereEquation(hitPoint + set(0, epsilon, 0), _radius, k, coefficients, c_idx_start, c_idx_end) - solvedEq,
        ls_asphereEquation(hitPoint + set(0, 0, epsilon), _radius, k, coefficients, c_idx_start, c_idx_end) - solvedEq
    ));

    // Surface hit point in world space
    vector hitp = hitPoint + _lensCenter;

    if (inside == 1) _normal = -_normal;
    surface_n = _normal;

    // Scale conversion back
    hitp = hitp * unit_scale;
    rayOrigin = hitp;
}


// Simplified version using full coefficient array
void ls_traceAsphericalElementFull(vector rayOrigin; vector rayDirection;
                                   float lensCenter; float radius; float k;
                                   float coefficients[];
                                   vector surface_n; vector _T;
                                   int hit_idx; int inside; float unit_scale)
{
    rayOrigin = rayOrigin * (1.0 / unit_scale);
    vector _lensCenter = set(0.0, 0.0, lensCenter) * (1.0 / unit_scale);
    float _radius = -radius * (1.0 / unit_scale);

    vector _rayDirection = rayDirection;
    float tolerance = 0.0001;
    float epsilon = 0.0005;
    int maxSteps = 4;

    vector localRayOrigin = rayOrigin - _lensCenter;
    vector hitPoint = set(0.0, 0.0, 0.0);
    int hit = 0;
    float t = 0.0;

    int stop = 0;
    for (int i = 0; i < maxSteps && stop == 0; i++)
    {
        vector currentPos = localRayOrigin + (t * _rayDirection);
        float f = ls_asphereEquationFull(currentPos, _radius, k, coefficients);

        if (abs(f) < tolerance)
        {
            hitPoint = currentPos;
            hit = 1;
            stop = 1;
        }
        else
        {
            vector grad = set(
                ls_asphereEquationFull(currentPos + set(epsilon, 0, 0), _radius, k, coefficients) - f,
                ls_asphereEquationFull(currentPos + set(0, epsilon, 0), _radius, k, coefficients) - f,
                ls_asphereEquationFull(currentPos + set(0, 0, epsilon), _radius, k, coefficients) - f
            ) / epsilon;
            t -= f / dot(grad, _rayDirection);
        }
    }

    if (hit == 0)
    {
        _T = 0;
        surface_n = set(0.0, 1.0, 0.0);
        rayOrigin = set(100.0, 0.0, 0.0);
        return;
    }

    float solvedEq = ls_asphereEquationFull(hitPoint, _radius, k, coefficients);
    vector _normal = normalize(set(
        ls_asphereEquationFull(hitPoint + set(epsilon, 0, 0), _radius, k, coefficients) - solvedEq,
        ls_asphereEquationFull(hitPoint + set(0, epsilon, 0), _radius, k, coefficients) - solvedEq,
        ls_asphereEquationFull(hitPoint + set(0, 0, epsilon), _radius, k, coefficients) - solvedEq
    ));

    vector hitp = hitPoint + _lensCenter;
    if (inside == 1) _normal = -_normal;
    surface_n = _normal;
    hitp = hitp * unit_scale;
    rayOrigin = hitp;
}


// Snell's law vector refraction
// Modifies incident ray direction in-place.
// T is set to (0,0,0) on total internal reflection (TIR).
// _eta is the refractive index of the medium the ray is entering.
// inside: 0 = entering glass (eta inverted), 1 = exiting glass
void ls_refract(vector incident; vector _Normal; float _eta; vector T; int inside)
{
    float eta = _eta;
    if (eta == 0.0)
        eta = 1.0;

    vector Normal = _Normal;
    if (inside == 1)
        Normal = -Normal;
    else
        eta = 1.0 / eta;

    float k = 1.0 - eta * eta * (1.0 - dot(Normal, incident) * dot(Normal, incident));

    if (k < 0.0)
    {
        // Total internal reflection — kill ray
        T = set(0.0, 0.0, 0.0);
    }
    else
    {
        incident = eta * incident - (eta * dot(Normal, incident) + sqrt(k)) * Normal;
    }
}


// ============================================================================
// Wavelength to RGB conversion
// CIE 1931 approximation for visible spectrum (380-780nm)
// ============================================================================

// Convert wavelength in nanometers to approximate RGB color
// Based on Dan Bruton's algorithm
vector ls_wavelength_to_rgb(float wavelength)
{
    float r = 0.0, g = 0.0, b = 0.0;

    if (wavelength >= 380.0 && wavelength < 440.0)
    {
        r = -(wavelength - 440.0) / (440.0 - 380.0);
        g = 0.0;
        b = 1.0;
    }
    else if (wavelength >= 440.0 && wavelength < 490.0)
    {
        r = 0.0;
        g = (wavelength - 440.0) / (490.0 - 440.0);
        b = 1.0;
    }
    else if (wavelength >= 490.0 && wavelength < 510.0)
    {
        r = 0.0;
        g = 1.0;
        b = -(wavelength - 510.0) / (510.0 - 490.0);
    }
    else if (wavelength >= 510.0 && wavelength < 580.0)
    {
        r = (wavelength - 510.0) / (580.0 - 510.0);
        g = 1.0;
        b = 0.0;
    }
    else if (wavelength >= 580.0 && wavelength < 645.0)
    {
        r = 1.0;
        g = -(wavelength - 645.0) / (645.0 - 580.0);
        b = 0.0;
    }
    else if (wavelength >= 645.0 && wavelength <= 780.0)
    {
        r = 1.0;
        g = 0.0;
        b = 0.0;
    }

    // Intensity falloff at the edges of visible spectrum
    float factor = 0.0;
    if (wavelength >= 380.0 && wavelength < 420.0)
        factor = 0.3 + 0.7 * (wavelength - 380.0) / (420.0 - 380.0);
    else if (wavelength >= 420.0 && wavelength <= 700.0)
        factor = 1.0;
    else if (wavelength > 700.0 && wavelength <= 780.0)
        factor = 0.3 + 0.7 * (780.0 - wavelength) / (780.0 - 700.0);

    r *= factor;
    g *= factor;
    b *= factor;

    return set(r, g, b);
}

// Cauchy dispersion: compute IOR for a given wavelength
// A and B are Cauchy coefficients derived from Abbe number
// wavelength is in nanometers
float ls_cauchy_ior(float A; float B; float wavelength_nm)
{
    float wl_um = wavelength_nm * 0.001; // nm to micrometers
    return A + B / (wl_um * wl_um);
}


// ============================================================================
// Focus Lookup Table
// ============================================================================

// Linear interpolation lookup table for focus distance → sensor position.
// keys[] and values[] must be the same length and sorted by ascending key.
// Returns interpolated value for the given key, clamped to table bounds.
float ls_lookup_table(float key; float keys[]; float values[])
{
    int n = len(keys);
    if (n == 0) return 0.0;
    if (key <= keys[0]) return values[0];
    if (key >= keys[n - 1]) return values[n - 1];

    // Binary search for the interval
    int lo = 0, hi = n - 1;
    while (lo < hi - 1)
    {
        int mid = (lo + hi) / 2;
        if (keys[mid] <= key)
            lo = mid;
        else
            hi = mid;
    }

    float t = (key - keys[lo]) / (keys[hi] - keys[lo]);
    return values[lo] + t * (values[hi] - values[lo]);
}

#endif // LENTILKARMA_CORE_H
