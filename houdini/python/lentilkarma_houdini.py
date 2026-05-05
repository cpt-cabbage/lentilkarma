"""
LentilKarma Houdini Integration
User-facing API for generating CVEX lens shaders and applying them to
Karma cameras in LOPs.

Usage from Houdini Python shell:
    import lentilkarma_houdini
    lentilkarma_houdini.apply_lens("/path/to/lens.txt", node=hou.node("/obj/cam1"))

Usage from shelf tool:
    import lentilkarma_houdini
    lentilkarma_houdini.show_lens_browser()
"""

import os
import re
import time
import traceback
import subprocess
import hou

from lentilkarma_data import list_available_lenses, get_lens_data
from lentilkarma_codegen import generate_vex_shader


def _lens_opname(lens_name):
    """Derive the VEX operator name from a lens name (matching codegen)."""
    return "lentilkarma_" + re.sub(r'[^a-zA-Z0-9]', '_', lens_name).strip('_').lower()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_SOURCE = "LentilKarma"
_log_file = None


def _get_log_path():
    """Return the path to the LentilKarma log file."""
    # Try user pref dir first
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR", "")
    if pref_dir:
        log_dir = os.path.join(pref_dir, "logs")
    else:
        log_dir = os.path.join(os.path.expanduser("~"), "houdini20.5", "logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "lentilkarma.log")


def _open_log():
    """Open the log file for appending."""
    global _log_file
    if _log_file is None:
        path = _get_log_path()
        _log_file = open(path, "a", encoding="utf-8")
        _log_file.write(f"\n{'='*72}\n")
        _log_file.write(f"LentilKarma session started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        _log_file.write(f"{'='*72}\n")
        _log_file.flush()
    return _log_file


def _log(message, severity=None):
    """Log a message to both hou.logging and the disk log file.

    Args:
        message: Log message string
        severity: hou.severityType value (default: Message)
    """
    if severity is None:
        severity = hou.severityType.Message

    tag = "INFO"
    if severity == hou.severityType.Warning:
        tag = "WARN"
    elif severity == hou.severityType.Error:
        tag = "ERROR"

    timestamp = time.strftime("%H:%M:%S")
    formatted = f"[{timestamp}] [{tag}] {message}"

    # Disk log
    try:
        f = _open_log()
        f.write(formatted + "\n")
        f.flush()
    except Exception:
        pass

    # hou.logging
    try:
        entry = hou.logging.LogEntry(
            message=message,
            severity=severity,
        )
        hou.logging.log(entry, source_name=_LOG_SOURCE)
    except Exception:
        pass

    # Also print so it shows in the Python shell
    print(f"[{_LOG_SOURCE}] {formatted}")


def _log_info(message):
    _log(message, hou.severityType.Message)


def _log_warn(message):
    _log(message, hou.severityType.Warning)


def _log_error(message):
    _log(message, hou.severityType.Error)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def get_lenses_dir():
    """Return the path to the LentilKarma lens data directory."""
    # Check LENTILKARMA env var first
    lentilkarma_root = hou.getenv("LENTILKARMA", "")
    _log_info(f"LENTILKARMA env var = '{lentilkarma_root}'")

    if lentilkarma_root:
        lenses_dir = os.path.join(lentilkarma_root, "LentilKarma_Data", "lenses")
        _log_info(f"Checking lenses dir: {lenses_dir}")
        if os.path.exists(lenses_dir):
            _log_info(f"Found lenses dir: {lenses_dir}")
            return lenses_dir
        else:
            _log_warn(f"Lenses dir does not exist: {lenses_dir}")

    # Fall back to relative path from this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    lenses_dir = os.path.join(script_dir, "..", "..", "LentilKarma_Data", "lenses")
    lenses_dir = os.path.normpath(lenses_dir)
    _log_info(f"Trying fallback lenses dir: {lenses_dir}")
    if os.path.exists(lenses_dir):
        _log_info(f"Found lenses dir (fallback): {lenses_dir}")
        return lenses_dir

    _log_error("Could not find LentilKarma lens data directory")
    return None


def get_output_dir():
    """Return the directory for generated VEX shaders."""
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR", "")
    if pref_dir:
        out = os.path.join(pref_dir, "vex", "lentilkarma")
    else:
        out = os.path.join(os.path.expanduser("~"), "houdini20.5", "vex", "lentilkarma")

    os.makedirs(out, exist_ok=True)
    _log_info(f"Output dir: {out}")
    return out


# ---------------------------------------------------------------------------
# Shader generation
# ---------------------------------------------------------------------------

def generate_lens_shader(lens_filepath, output_dir=None):
    """Generate a CVEX lens shader .vfl file from a lens data file.

    Args:
        lens_filepath: Path to the .txt lens data file
        output_dir: Directory to write the .vfl file (default: user pref dir)

    Returns:
        str: Path to the generated .vfl file
    """
    _log_info(f"Generating lens shader from: {lens_filepath}")

    if not os.path.exists(lens_filepath):
        _log_error(f"Lens file not found: {lens_filepath}")
        raise FileNotFoundError(f"Lens file not found: {lens_filepath}")

    if output_dir is None:
        output_dir = get_output_dir()

    lens_name = os.path.basename(lens_filepath).replace(".txt", "")
    safe_name = lens_name.replace(" ", "_").replace(".", "_")
    output_path = os.path.join(output_dir, f"lentilkarma_{safe_name}.vfl")
    _log_info(f"Output VFL path: {output_path}")

    t0 = time.time()
    try:
        source = generate_vex_shader(lens_filepath, output_path)
        dt = time.time() - t0
        line_count = source.count("\n") + 1
        _log_info(f"VFL generated: {line_count} lines in {dt:.2f}s")
    except Exception as e:
        _log_error(f"VFL generation failed: {e}")
        _log_error(traceback.format_exc())
        raise

    return output_path


def get_otls_dir():
    """Return the otls directory for HDA installation."""
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR", "")
    if pref_dir:
        out = os.path.join(pref_dir, "otls")
    else:
        out = os.path.join(os.path.expanduser("~"), "houdini20.5", "otls")
    os.makedirs(out, exist_ok=True)
    return out


def _get_vex_include_dir():
    """Return $HOUDINI_USER_PREF_DIR/vex/include/ (standard VEX include path)."""
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR", "")
    if pref_dir:
        d = os.path.join(pref_dir, "vex", "include")
    else:
        d = os.path.join(os.path.expanduser("~"), "houdini20.5", "vex", "include")
    os.makedirs(d, exist_ok=True)
    return d


def _fix_hda_vfl_source(hda_path, vfl_filepath, include_dir):
    """Fix the HDA's CVexVflCode section for large shaders.

    vcc -O vop -l truncates the stored VFL source for shaders exceeding
    the HDA section size limit (~500KB). Karma loads from CVexVflCode at
    render time, so truncation causes compilation failure.

    Fix: copy the full VFL and its includes to $HOUDINI_USER_PREF_DIR/vex/include/
    (which is in the standard VEX include search path), then replace
    CVexVflCode with a tiny stub that #include's the full VFL.
    """
    # Read original VFL to check size
    vfl_size = os.path.getsize(vfl_filepath)
    vfl_basename = os.path.basename(vfl_filepath)

    # Get HDA definitions
    definitions = hou.hda.definitionsInFile(hda_path)
    if not definitions:
        _log_warn(f"No HDA definitions found in {hda_path}, skipping source fix")
        return

    defn = definitions[0]
    sections = defn.sections()

    if "CVexVflCode" not in sections:
        _log_warn("CVexVflCode section not found in HDA, skipping source fix")
        return

    # Check if source is truncated
    existing_source = sections["CVexVflCode"].contents()

    # If the CVexVflCode contains a header include, this is the wrapper
    # pattern — vcc correctly stored only the outer code (#include).
    # The small size is intentional, NOT truncation.
    if '#include' in existing_source and '.h"' in existing_source:
        _log_info(f"CVexVflCode uses header/wrapper pattern "
                  f"({len(existing_source)} bytes), no fix needed")
        return

    if len(existing_source) >= vfl_size * 0.9:
        _log_info(f"HDA source looks complete ({len(existing_source)} bytes), no fix needed")
        return

    _log_info(f"HDA source truncated ({len(existing_source)} bytes vs "
              f"{vfl_size} bytes VFL). Applying include-stub fix...")

    # Copy VFL and core.h to the standard VEX include directory so
    # Houdini can find them at render-time recompilation
    vex_inc_dir = _get_vex_include_dir()

    import shutil
    dst_vfl = os.path.join(vex_inc_dir, vfl_basename)
    shutil.copy2(vfl_filepath, dst_vfl)
    _log_info(f"Copied VFL to VEX include dir: {dst_vfl}")

    # Copy lentilkarma_core.h so the VFL's #include finds it
    core_h = os.path.join(include_dir, "lentilkarma_core.h")
    if os.path.exists(core_h):
        dst_core = os.path.join(vex_inc_dir, "lentilkarma_core.h")
        shutil.copy2(core_h, dst_core)
        _log_info(f"Copied core.h to VEX include dir: {dst_core}")

    # Replace CVexVflCode with a tiny stub that includes the full VFL.
    # At render time Houdini's VEX compiler searches $HOUDINI_USER_PREF_DIR/vex/include/
    # automatically, so the #include resolves without any -I flag.
    stub = f'#include "{vfl_basename}"\n'
    defn.addSection("CVexVflCode", stub)

    # Reinstall so Houdini picks up the stub
    hou.hda.installFile(hda_path)
    _log_info(f"HDA CVexVflCode replaced with include stub ({len(stub)} bytes) and reinstalled")


def _dump_vop_sections(optype_name):
    """Dump all HDA sections for a VOP type (for debugging).

    Use this to introspect existing VOP HDAs like kma_physicallenscore to
    understand section formats (TypePropertiesOptions, ExtraFileOptions,
    CVexVflCode, etc.).

    Args:
        optype_name: VOP type name (e.g., "kma_physicallenscore")

    Usage:
        _dump_vop_sections("kma_physicallenscore")
    """
    try:
        nt = hou.nodeType(hou.vopNodeTypeCategory(), optype_name)
    except Exception:
        _log_error(f"VOP type not found: {optype_name}")
        return

    if nt is None:
        _log_error(f"VOP type not found: {optype_name}")
        return

    defn = nt.definition()
    if defn is None:
        _log_error(f"No HDA definition for: {optype_name}")
        return

    _log_info(f"=== Sections for {optype_name} ===")
    for name, section in sorted(defn.sections().items()):
        contents = section.contents()
        _log_info(f"--- {name} ({len(contents)} bytes) ---")
        # Print first 500 chars to console
        preview = contents[:500]
        print(f"--- {name} ({len(contents)} bytes) ---")
        print(preview)
        if len(contents) > 500:
            print(f"  ... ({len(contents) - 500} more bytes)")
        print()


# Hidden CVEX context parameters — vcc marks these invisible, they have
# NO VOP input connectors and auto-bind from the CVEX context.
_HIDDEN_CVEX_NAMES = frozenset({
    "x", "y", "Time", "dofx", "dofy", "aspect",
    "P", "I", "tint",
})

# Export outputs from the core VOP (P=ray origin, I=ray direction, tint=color)
_EXPORT_NAMES = ("P", "I", "tint")


def _discover_parmtype_map(parent_node):
    """Discover the parameter VOP's parmtype menu values at runtime.

    Creates a temporary parameter VOP to read its parmtype menu.
    Returns a dict mapping multiple key forms to menu item values:
      - Full label:  "float (float)" -> item_value
      - VEX type:    "float"         -> item_value  (from parentheses)
      - Prefix:      "integer"       -> item_value  (before parentheses)

    For ambiguous VEX types (e.g. "vector" appears in both "3 floats (vector)"
    and "vector (vector)"), the entry where prefix == inner wins.
    """
    try:
        sample = parent_node.createNode("parameter")
        items = sample.parm("parmtype").menuItems()
        labels = sample.parm("parmtype").menuLabels()
        sample.destroy()

        result = {}
        for label, item in zip(labels, items):
            ll = label.lower()
            # Full label -> item
            result[ll] = item
            # Extract type from parentheses: "Float (float)" -> "float"
            paren_start = ll.find("(")
            if paren_start >= 0:
                inner = ll[paren_start + 1:].rstrip(") ").strip()
                prefix = ll[:paren_start].strip()
                # Prefer the entry where prefix matches inner
                # (e.g. "vector (vector)" over "3 floats (vector)")
                if inner not in result or prefix == inner:
                    result[inner] = item
                if prefix not in result:
                    result[prefix] = item

        _log_info(f"Parmtype map sample: "
                  f"float={result.get('float', '?')}, "
                  f"int={result.get('int', '?')}, "
                  f"integer={result.get('integer', '?')}, "
                  f"vector={result.get('vector', '?')}, "
                  f"vector2={result.get('vector2', '?')}, "
                  f"toggle={result.get('toggle', '?')}")
        return result
    except Exception as e:
        _log_warn(f"Could not discover parmtype map: {e}")
        return {}


def _resolve_vop_parmtype(pt, parmtype_map):
    """Map a hou.ParmTemplate to the correct parameter VOP parmtype value."""
    pt_type = pt.type()
    if pt_type == hou.parmTemplateType.Int:
        key = "integer"
    elif pt_type == hou.parmTemplateType.Float:
        nc = pt.numComponents()
        if nc == 3:
            key = "vector"
        elif nc == 2:
            key = "vector2"
        elif nc == 4:
            key = "vector4"
        else:
            key = "float"
    elif pt_type == hou.parmTemplateType.String:
        key = "string"
    elif pt_type == hou.parmTemplateType.Toggle:
        key = "toggle"
    else:
        key = "float"

    if key in parmtype_map:
        return parmtype_map[key]
    # Fallback: try common string values
    fallback = {"integer": "int", "float": "float", "vector": "vector",
                "vector2": "vector2", "vector4": "vector4",
                "string": "string", "toggle": "toggle"}
    return fallback.get(key, "float")


def _find_ds_input_index(defn, parm_name):
    """Find a VOP input connector index by parsing the DialogScript.

    vcc only creates input connectors for visible (non-invisible) params.
    Returns the 0-based index, or -1 if not found.
    """
    ds_section = defn.sections().get("DialogScript")
    if not ds_section:
        return -1
    import re
    pattern = re.compile(r'^\s*input\s+\w+\s+(\w+)\s+"[^"]*"', re.MULTILINE)
    idx = 0
    for m in pattern.finditer(ds_section.contents()):
        if m.group(1) == parm_name:
            return idx
        idx += 1
    return -1


def _find_ds_output_index(defn, output_name):
    """Find a VOP output connector index by parsing the DialogScript.

    Returns the 0-based index, or -1 if not found.
    """
    ds_section = defn.sections().get("DialogScript")
    if not ds_section:
        return -1
    import re
    pattern = re.compile(r'^\s*output\s+\w+\s+(\w+)\s+"[^"]*"', re.MULTILINE)
    idx = 0
    for m in pattern.finditer(ds_section.contents()):
        if m.group(1) == output_name:
            return idx
        idx += 1
    return -1


def _escape_ds_parmtag(s):
    """Escape a string for use in a DialogScript parmtag double-quoted value."""
    s = s.replace('\\', '\\\\')
    s = s.replace('"', '\\"')
    s = s.replace('\n', '\\n')
    s = s.replace('\t', '\\t')
    return s


def _build_lens_info_ds_blocks(selected, lenses_dir):
    """Build DialogScript parm block text for lens info parameters.

    Generates parm blocks for focal_length, horizontal_aperture,
    warmup controls in DialogScript format.  These are inserted into
    the outer HDA's DialogScript so they persist in the .hda file.
    """
    focal_lengths = []
    sensor_sizes_mm = []
    for filename, display_name in selected:
        fp = os.path.join(lenses_dir, filename)
        try:
            lens = get_lens_data(fp)
            fl = _parse_focal_length(display_name, lens)
            ss = lens["default_sensor_size"] * 1000.0
        except Exception:
            fl = 50.0
            ss = 36.0
        focal_lengths.append(fl)
        sensor_sizes_mm.append(ss)

    warmup_cb = _escape_ds_parmtag(
        "import lentilkarma_houdini; "
        "lentilkarma_houdini._warmup_all_callback(kwargs)")
    cancel_cb = _escape_ds_parmtag(
        "import lentilkarma_houdini; "
        "lentilkarma_houdini._cancel_warmup_callback(kwargs)")

    lines = []
    # focal_length
    lines.append('    parm {')
    lines.append('\tname\tfocal_length')
    lines.append('\tlabel\t"Focal Length (mm)"')
    lines.append('\ttype\tfloat')
    lines.append(f'\tdefault {{ {focal_lengths[0]:.2f} }}')
    lines.append('\trange\t{ 0! 200 }')
    lines.append('\texport\tnone')
    lines.append('    }')
    # horizontal_aperture
    lines.append('    parm {')
    lines.append('\tname\thorizontal_aperture')
    lines.append('\tlabel\t"Horizontal Aperture (mm)"')
    lines.append('\ttype\tfloat')
    lines.append(f'\tdefault {{ {sensor_sizes_mm[0]:.2f} }}')
    lines.append('\trange\t{ 0! 100 }')
    lines.append('\texport\tnone')
    lines.append('    }')
    # warmup_delay
    lines.append('    parm {')
    lines.append('\tname\twarmup_delay')
    lines.append('\tlabel\t"Warmup Delay (s)"')
    lines.append('\ttype\tfloat')
    lines.append('\tdefault { 5.0 }')
    lines.append('\trange\t{ 1! 30 }')
    lines.append('\texport\tnone')
    lines.append('    }')
    # warmup_btn
    lines.append('    parm {')
    lines.append('\tname\twarmup_btn')
    lines.append('\tlabel\t"Warmup All Lenses"')
    lines.append('\ttype\tbutton')
    lines.append('\tdefault { "0" }')
    lines.append(f'\tparmtag {{ "script_callback" "{warmup_cb}" }}')
    lines.append('\tparmtag { "script_callback_language" "python" }')
    lines.append('    }')
    # cancel_btn
    lines.append('    parm {')
    lines.append('\tname\twarmup_cancel_btn')
    lines.append('\tlabel\t"Cancel Warmup"')
    lines.append('\ttype\tbutton')
    lines.append('\tdefault { "0" }')
    lines.append(f'\tparmtag {{ "script_callback" "{cancel_cb}" }}')
    lines.append('\tparmtag { "script_callback_language" "python" }')
    lines.append('    }')

    return '\n'.join(lines) + '\n'


def _remove_ds_parm_block(ds, parm_name):
    """Remove a parm block by name from DialogScript text.

    Finds ``parm { name <parm_name> ... }`` (including nested braces like
    ``default { 0 }`` or ``menu { ... }``) and removes the entire block.
    Also removes the corresponding ``input`` line if present.
    """
    # Remove input line for this parm (if any)
    ds = re.sub(
        r'^\s*input\s+\w+\s+' + re.escape(parm_name) + r'\s+"[^"]*"\s*\n',
        '', ds, flags=re.MULTILINE)

    # Find "parm {" block containing "name <parm_name>"
    pattern = re.compile(
        r'\s*parm\s*\{[^\n]*\n[^\}]*?\bname\s+' + re.escape(parm_name) + r'\b',
        re.MULTILINE)
    m = pattern.search(ds)
    if not m:
        return ds

    start = m.start()
    # Find the opening brace of this parm block
    brace_pos = ds.index('{', start)
    brace_count = 0
    i = brace_pos
    while i < len(ds):
        if ds[i] == '{':
            brace_count += 1
        elif ds[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end = i + 1
                if end < len(ds) and ds[end] == '\n':
                    end += 1
                return ds[:start] + ds[end:]
        i += 1

    return ds


def _adapt_core_ds_for_outer(core_defn, selected, lenses_dir):
    """Adapt the core HDA's DialogScript for use as the outer VOP subnet.

    Copies the core's vcc-generated DialogScript (which has proper menu items,
    ranges, hidden CVEX params, export declarations, and IO connectors) and
    modifies it for the outer HDA:
    - Changes name/script/label from lentilkarma_core to lentilkarma
    - Removes core's focal_length/horizontal_aperture parm blocks (replaced
      with our expression-driven versions)
    - Appends focal_length, horizontal_aperture, and warmup parm blocks

    This avoids setParmTemplateGroup() which corrupts TypePropertiesOptions
    on VOP subnet HDAs, causing Houdini to freeze at render time.
    """
    core_ds_section = core_defn.sections().get("DialogScript")
    if not core_ds_section:
        _log_error("Core has no DialogScript section")
        return ""

    ds = core_ds_section.contents()

    # Replace name, script, label
    ds = re.sub(r'(name\s+)"lentilkarma_core"', r'\1"lentilkarma"', ds)
    ds = re.sub(r'(script\s+)"lentilkarma_core"', r'\1"lentilkarma"', ds)
    ds = re.sub(
        r'(label\s+)"[^"]*"',
        r'\1"LentilKarma Lens Shader"', ds, count=1)

    # The core's DS has Context/shadertype/rendermask stripped (it's a VEX node).
    # The outer IS a shader, so add shadertype back after the label line.
    # Must match kma_physicallens exactly: shadertype=cvex, rendermask="VMantra OGL"
    if "shadertype" not in ds:
        ds = re.sub(
            r'(label\s+"[^"]*"\s*\n)',
            r'\1    rendermask\t"VMantra OGL"\n    shadertype\tcvex\n',
            ds, count=1)

    # Remove core's focal_length / horizontal_aperture parm blocks —
    # we replace them with our own expression-driven versions below.
    for pname in ("focal_length", "horizontal_aperture"):
        ds = _remove_ds_parm_block(ds, pname)

    # Build extra parm blocks for lens info
    extra_parms = _build_lens_info_ds_blocks(selected, lenses_dir)

    # Insert before the closing }
    close_idx = ds.rfind("}")
    if close_idx > 0:
        ds = ds[:close_idx] + extra_parms + ds[close_idx:]

    return ds


def _fix_core_hda_type(core_hda_path):
    """Fix the core HDA to be a VEX code node, not a shader.

    After vcc compilation, the core HDA has:
        Extra: subtype=material shadertype=vopmaterial vopnetmask='cvex'
    But the SideFX kma_physicallenscore pattern uses:
        Extra: vopnetmask='cvex'
    (no shader properties -- it's a code-generating VOP, not a material)

    Also ensures Force Code Generation is enabled via TypePropertiesOptions
    (copied from kma_physicallenscore when available, otherwise constructed).
    The DialogScript is also cleaned to remove shader-specific fields.
    """
    type_name = _find_installed_type("lentilkarma_core")
    if not type_name:
        _log_warn("Could not find core type to fix -- skipping")
        return

    nt = hou.nodeType(hou.vopNodeTypeCategory(), type_name)
    defn = nt.definition()

    # 1. Strip shader-specific lines from DialogScript BEFORE changing Extra.
    #    The vcc-generated DS starts with "# Context: CVex" which is ONLY
    #    valid for shader-type VOPs. Non-shader VOPs (code-generating VOPs
    #    with vopnetmask='cvex') do not understand this directive — their
    #    DS parser expects "{" immediately, causing:
    #       Error(1): Expecting open brace for script
    #    which makes the core report 0 params and breaks everything.
    #    We must also strip rendermask and shadertype for consistency.
    ds_section = defn.sections().get("DialogScript")
    if ds_section:
        ds = ds_section.contents()
        # Strip "# Context: CVex" directive (fatal for non-shader VOPs)
        ds = re.sub(r'^#\s*Context:.*\n?', '', ds, flags=re.MULTILINE)
        ds = re.sub(r'^\s*rendermask\s+.*\n?', '', ds, flags=re.MULTILINE)
        ds = re.sub(r'^\s*shadertype\s+.*\n?', '', ds, flags=re.MULTILINE)
        ds_section.setContents(ds)
        _log_info("Stripped Context/shadertype/rendermask from core DialogScript")

    # 2. Extra: Match kma_physicallenscore pattern.
    #    From diagnostics: "shadertype=<Not Applicable> visibleoutputs=8 vopnetmask='cvex'"
    #    visibleoutputs = number of output connectors shown on the VOP node.
    #    Our core exports P, I, tint (3 outputs).
    #    Count the actual output declarations in the DS to be accurate.
    n_outputs = 3  # P, I, tint
    if ds_section:
        n_outputs = len(re.findall(r'^\s*output\s+', ds_section.contents(),
                                   re.MULTILINE))
        if n_outputs == 0:
            n_outputs = 3  # fallback
    defn.setExtraInfo(
        f"shadertype=<Not Applicable> visibleoutputs={n_outputs} vopnetmask='cvex'"
    )
    _log_info(f"Core Extra set to match kma_physicallenscore pattern "
              f"(visibleoutputs={n_outputs})")

    # 3. Copy TypePropertiesOptions from kma_physicallenscore if available.
    #    This gets us the exact right format for a code-generating VOP.
    tpo_copied = False
    try:
        ref_nt = hou.nodeType(hou.vopNodeTypeCategory(),
                              "kma_physicallenscore")
        if ref_nt and ref_nt.definition():
            ref_tpo = ref_nt.definition().sections().get(
                "TypePropertiesOptions")
            if ref_tpo:
                tpo_content = ref_tpo.contents()
                tpo_section = defn.sections().get("TypePropertiesOptions")
                if tpo_section:
                    tpo_section.setContents(tpo_content)
                else:
                    defn.addSection("TypePropertiesOptions", tpo_content)
                tpo_copied = True
                _log_info("Copied TPO from kma_physicallenscore")
    except Exception as e:
        _log_warn(f"Could not copy TPO from kma_physicallenscore: {e}")

    # Fallback: construct a minimal TPO with proper syntax (semicolons!)
    if not tpo_copied:
        _log_info("Constructing minimal code-gen TPO (fallback)")
        tpo_content = (
            "CheckExternal := 1;\n"
            "ContentsType := 2;\n"
            "ForceCodeGeneration := 1;\n"
        )
        tpo_section = defn.sections().get("TypePropertiesOptions")
        if tpo_section:
            tpo_section.setContents(tpo_content)
        else:
            defn.addSection("TypePropertiesOptions", tpo_content)
        _log_info("Set minimal TPO with ForceCodeGeneration := 1;")

    # Regardless of source, ensure ForceCodeGeneration is present.
    # The kma_physicallenscore TPO might not have it explicitly — it may
    # be implied by ContentsType or other mechanisms. But explicit is safer.
    tpo_section = defn.sections().get("TypePropertiesOptions")
    if tpo_section:
        tpo_text = tpo_section.contents()
        modified = False
        if "ForceCodeGeneration" not in tpo_text:
            tpo_text = tpo_text.rstrip('\n') + "\nForceCodeGeneration := 1;\n"
            modified = True
            _log_info("Appended ForceCodeGeneration := 1; to core TPO")
        if "ContentsType" not in tpo_text:
            tpo_text = tpo_text.rstrip('\n') + "\nContentsType := 2;\n"
            modified = True
            _log_info("Appended ContentsType := 2; to core TPO")
        if modified:
            tpo_section.setContents(tpo_text)

    defn.save(core_hda_path)
    hou.hda.installFile(core_hda_path)
    _log_info("Core HDA type fixed and reinstalled")


def _copy_vex_builder_tpo(defn):
    """Copy TypePropertiesOptions from kma_physicallens to make our HDA
    a proper VEX Builder (allows adding VOP nodes inside, proper CVEX context).

    Falls back gracefully if kma_physicallens is not installed.
    """
    try:
        ref_nt = hou.nodeType(hou.vopNodeTypeCategory(), "kma_physicallens")
        if not ref_nt or not ref_nt.definition():
            _log_warn("kma_physicallens not found — cannot copy TPO")
            return False

        ref_tpo = ref_nt.definition().sections().get("TypePropertiesOptions")
        if not ref_tpo:
            _log_warn("kma_physicallens has no TypePropertiesOptions")
            return False

        our_tpo = defn.sections().get("TypePropertiesOptions")
        if our_tpo:
            our_tpo.setContents(ref_tpo.contents())
        else:
            defn.addSection("TypePropertiesOptions", ref_tpo.contents())

        _log_info("Copied TypePropertiesOptions from kma_physicallens")
        return True
    except Exception as e:
        _log_warn(f"Could not copy VEX Builder TPO: {e}")
        return False


def _add_bind_exports(hda_node, core_defn):
    """Add bind export VOPs for P, I, tint inside the outer HDA.

    Must be called AFTER the HDA has been set up as a proper CVEX shader
    (via TypePropertiesOptions and Extra).  The bind exports wire from
    the core's output connectors to declare the shader outputs.
    """
    hda_node.allowEditingOfContents()
    _log_info("Unlocked HDA for editing -- adding bind exports")

    core_node = None
    for child in hda_node.children():
        if "lentilkarma_core" in child.type().name():
            core_node = child
            break

    if not core_node:
        _log_warn("Could not find core node inside HDA for bind exports")
        return

    export_count = 0
    for export_name in _EXPORT_NAMES:
        try:
            bind_vop = hda_node.createNode("bind", f"export_{export_name}")
            bind_vop.parm("parmname").set(export_name)
            bind_vop.parm("exportparm").set(1)  # Export: Always

            # Wire core output -> bind input
            out_idx = _find_ds_output_index(core_defn, export_name)
            if out_idx >= 0:
                bind_vop.setInput(0, core_node, out_idx)
                export_count += 1
                _log_info(f"  bind export '{export_name}' wired "
                          f"from core output {out_idx}")
            else:
                _log_warn(f"  No output index for '{export_name}' on core")
        except Exception as e:
            _log_warn(f"  Could not create bind export "
                      f"for '{export_name}': {e}")

    hda_node.layoutChildren()
    _log_info(f"Added {export_count}/{len(_EXPORT_NAMES)} bind exports")


def _create_outer_hda(core_hda_path, outer_hda_path, selected, lenses_dir,
                      vfl_source=None):
    """Create the outer VOP subnet HDA wrapping the core.

    Follows the SideFX kma_physicallens / kma_physicallenscore nested pattern:

    kma_physicallens (outer — this function creates it):
      - Shader Type: cvex, Sub Type: material (Extra: shadertype=cvex subtype=material)
      - Inside: parameter VOPs for visible inputs, wired to core
      - FunctionName section with the shader function name
      - VflCode section with the VEX source (NOT CVexVflCode)

    kma_physicallenscore (inner — compiled by vcc separately):
      - VopNet Mask: cvex, Force Code Generation: on
      - NOT a shader — just a code-generating VOP

    The outer HDA uses the core's adapted DialogScript to avoid
    setParmTemplateGroup() (which corrupts TypePropertiesOptions).
    TypePropertiesOptions is copied from kma_physicallens to get
    the proper VEX Builder context.

    Args:
        core_hda_path: Path to the compiled core .hda file
        outer_hda_path: Path to write the outer .hda file
        selected: List of (filename, display_name) tuples for lens info
        lenses_dir: Path to the lenses data directory
        vfl_source: VFL source code to embed as VflCode section

    Returns:
        hou.Node: The outer HDA node instance, or None on failure
    """
    _log_info(f"Creating outer VOP subnet HDA: {outer_hda_path}")

    # 1. Ensure core HDA is installed
    hou.hda.installFile(core_hda_path)
    _log_info("Core HDA installed")

    core_type_name = _find_installed_type("lentilkarma_core")
    if not core_type_name:
        _log_error("Could not find installed type for lentilkarma_core")
        return None
    _log_info(f"Core type name: {core_type_name}")

    # 2. Create temp VOP subnet in /mat
    mat = hou.node("/mat")
    if mat is None:
        _log_error("No /mat network found")
        return None

    for old_name in ("__temp_lk_outer", "lentilkarma"):
        old_node = mat.node(old_name)
        if old_node:
            _log_info(f"Removing existing node: {old_node.path()}")
            old_node.destroy()

    subnet = mat.createNode("subnet", "__temp_lk_outer")
    _log_info(f"Created temp subnet: {subnet.path()}")

    # 3. Create core node inside the subnet
    try:
        core_node = subnet.createNode(core_type_name, "lentilkarma_core")
        core_node.moveToGoodPosition()
        _log_info(f"Created core node: {core_node.path()}")
    except Exception as e:
        _log_error(f"Failed to create core node: {e}")
        subnet.destroy()
        return None

    # 4. Get core parameter templates and identify visible params
    core_nt = hou.nodeType(hou.vopNodeTypeCategory(), core_type_name)
    core_defn = core_nt.definition()
    core_ptg = core_defn.parmTemplateGroup()

    visible_pts = [pt for pt in core_ptg.entries()
                   if pt.name() not in _HIDDEN_CVEX_NAMES]
    _log_info(f"Core has {len(core_ptg.entries())} total params, "
              f"{len(visible_pts)} visible")

    # 5. Discover parameter VOP's parmtype menu values at runtime
    parmtype_map = _discover_parmtype_map(subnet)
    _log_info(f"Discovered parmtype map keys: {list(parmtype_map.keys())}")

    # 6. Create parameter VOPs for each visible input and wire to core.
    wired_count = 0
    for pt in visible_pts:
        pname = pt.name()
        vop_type = _resolve_vop_parmtype(pt, parmtype_map)

        try:
            parm_vop = subnet.createNode("parameter", f"parm_{pname}")
            parm_vop.parm("parmname").set(pname)
            parm_vop.parm("parmlabel").set(pt.label())
            parm_vop.parm("parmtype").set(vop_type)
        except Exception as e:
            _log_warn(f"Could not create parameter VOP for '{pname}': {e}")
            continue

        # Wire parameter VOP output (0) -> core input by name
        try:
            core_node.setNamedInput(pname, parm_vop, 0)
            wired_count += 1
        except Exception:
            idx = _find_ds_input_index(core_defn, pname)
            if idx >= 0:
                try:
                    core_node.setInput(idx, parm_vop, 0)
                    wired_count += 1
                except Exception as e2:
                    _log_warn(f"Could not wire '{pname}' (idx={idx}): {e2}")
            else:
                _log_warn(f"No input connector found for '{pname}'")

    _log_info(f"Wired {wired_count}/{len(visible_pts)} parameter VOPs")

    # 7. Wire core outputs to subnet's suboutput node.
    #    This is CRITICAL: without output connections, the VOP compiler
    #    only traverses the parameter VOPs and never reaches the core.
    #    In kma_physicallens, the core outputs wire to the subnet's
    #    suboutput, so the VOP compiler traverses:
    #      suboutput → core → parameter VOPs → generates code
    #    Without this wiring, code() produces only parameter declarations
    #    and shaderString() returns empty.
    suboutput = subnet.node("suboutput1")
    if suboutput:
        output_wired = 0
        for export_name in _EXPORT_NAMES:
            out_idx = _find_ds_output_index(core_defn, export_name)
            if out_idx >= 0:
                try:
                    # suboutput input N corresponds to the Nth output connector
                    # of the subnet. Wire core output -> suboutput input.
                    suboutput.setInput(output_wired, core_node, out_idx)
                    output_wired += 1
                    _log_info(f"Wired core output '{export_name}' "
                              f"(idx={out_idx}) -> suboutput input {output_wired - 1}")
                except Exception as e:
                    _log_warn(f"Could not wire core output '{export_name}': {e}")
            else:
                _log_warn(f"No output index for '{export_name}' on core DS")
        _log_info(f"Wired {output_wired}/{len(_EXPORT_NAMES)} core outputs "
                  f"to subnet suboutput")
    else:
        _log_warn("No suboutput1 node found in subnet")

    subnet.layoutChildren()

    # 8. Convert subnet to HDA
    _log_info("Converting subnet to digital asset...")
    try:
        if os.path.exists(outer_hda_path):
            try:
                hou.hda.uninstallFile(outer_hda_path)
            except Exception:
                pass

        hda_node = subnet.createDigitalAsset(
            name="lentilkarma",
            hda_file_name=outer_hda_path,
            description="LentilKarma Lens Shader",
            min_num_inputs=0,
            max_num_inputs=0,
        )
        _log_info(f"Digital asset created: {hda_node.path()}")
    except Exception as e:
        _log_error(f"Failed to create digital asset: {e}")
        subnet.destroy()
        return None

    hda_node.setName("lentilkarma", unique_name=True)
    _log_info(f"Renamed node to: {hda_node.path()}")

    # 9. Replace the DialogScript with the core's DS (adapted for outer).
    defn = hda_node.type().definition()
    outer_ds = _adapt_core_ds_for_outer(core_defn, selected, lenses_dir)
    ds_section = defn.sections().get("DialogScript")
    if ds_section:
        ds_section.setContents(outer_ds)
    else:
        defn.addSection("DialogScript", outer_ds)
    _log_info("Wrote adapted DialogScript (from core)")

    # 10. Set Extra to match the vcc-compiled VOP pattern.
    #     The flat demo HDA (anaglyphlens) uses:
    #       Extra: subtype=material shadertype=vopmaterial vopnetmask='cvex'
    #     This tells Houdini it's a CVEX material VOP, and shaderString()
    #     reads the CVexVflCode section for the shader code.
    #     Note: kma_physicallens uses shadertype=cvex (VOP network compilation)
    #     but we can't replicate that (requires C++ code-generating VOPs).
    try:
        defn.setExtraInfo(
            "subtype=material shadertype=vopmaterial vopnetmask='cvex'"
        )
        _log_info("Set outer HDA extra info (matching vcc-compiled VOP pattern)")
    except Exception as e:
        _log_warn(f"Could not set extra info: {e}")

    # 11. Copy TypePropertiesOptions from kma_physicallens to get the proper
    #     VEX Builder context (allows VOP nodes inside, proper CVEX handling).
    tpo_ok = _copy_vex_builder_tpo(defn)
    if not tpo_ok:
        _log_error("CRITICAL: Could not copy TPO from kma_physicallens. "
                   "The outer HDA may not compile VOP network correctly.")

    # 12. Add VflCode section from the core's CVexVflCode (preprocessed VFL).
    #     kma_physicallens has 'VflCode' (107KB of preprocessed VFL with
    #     _Pragma directives, #line, all includes expanded) but NO 'CVexVflCode'.
    #     Our core's CVexVflCode (489KB) is in the SAME format — it's the
    #     preprocessed output from vcc with all code expanded.
    #     We rename the function from lentilkarma_core to lentilkarma and
    #     store it as VflCode in the outer HDA.
    #     Also remove any stale CVexVflCode that might interfere.
    cvex_section = defn.sections().get("CVexVflCode")
    if cvex_section:
        _log_info("Removing stale CVexVflCode from outer HDA")
        try:
            cvex_section.destroy()
        except Exception:
            try:
                defn.removeSection("CVexVflCode")
            except Exception:
                cvex_section.setContents("")

    # Read preprocessed VFL from the core's CVexVflCode section
    core_type_name2 = _find_installed_type("lentilkarma_core")
    core_cvex_vfl = None
    if core_type_name2:
        core_nt2 = hou.nodeType(hou.vopNodeTypeCategory(), core_type_name2)
        if core_nt2 and core_nt2.definition():
            core_cvex_sec = core_nt2.definition().sections().get("CVexVflCode")
            if core_cvex_sec:
                core_cvex_vfl = core_cvex_sec.contents()
                _log_info(f"Read core CVexVflCode: {len(core_cvex_vfl)} bytes")

    if core_cvex_vfl:
        # Rename function from lentilkarma_core to lentilkarma in
        # the preprocessed VFL (uses _Pragma, not #pragma)
        outer_vfl = core_cvex_vfl
        outer_vfl = outer_vfl.replace(
            '_Pragma("opname      lentilkarma_core")',
            '_Pragma("opname      lentilkarma")')
        outer_vfl = outer_vfl.replace(
            'cvex lentilkarma_core(',
            'cvex lentilkarma(')
        vfl_section = defn.sections().get("VflCode")
        if vfl_section:
            vfl_section.setContents(outer_vfl)
        else:
            defn.addSection("VflCode", outer_vfl)
        _log_info(f"Added VflCode section ({len(outer_vfl)} bytes) "
                  f"from core's preprocessed CVexVflCode")
    elif vfl_source:
        # Fallback: use raw VFL source (less likely to work)
        _log_warn("Core CVexVflCode not available, using raw VFL as fallback")
        outer_vfl = vfl_source.replace(
            'cvex lentilkarma_core(', 'cvex lentilkarma(')
        vfl_section = defn.sections().get("VflCode")
        if vfl_section:
            vfl_section.setContents(outer_vfl)
        else:
            defn.addSection("VflCode", outer_vfl)
    else:
        _log_warn("No VFL source available for VflCode section")

    # 12b. Add FunctionName section — this is how shaderString() knows the
    #      function name. kma_physicallens has this section; without it,
    #      shaderString() returns empty → "Missing shader name".
    fn_section = defn.sections().get("FunctionName")
    if fn_section:
        fn_section.setContents("lentilkarma")
    else:
        defn.addSection("FunctionName", "lentilkarma")
    _log_info("Added FunctionName section: 'lentilkarma'")

    # 13. Save and reinstall
    try:
        defn.save(outer_hda_path)
        _log_info(f"Saved outer HDA: {outer_hda_path}")
    except Exception as e:
        _log_error(f"Failed to save: {e}")
        return None

    hou.hda.installFile(outer_hda_path)
    _log_info("Outer HDA installed")

    # 14. Set focal_length / horizontal_aperture expressions on the node
    _set_lens_info_expressions(hda_node, selected, lenses_dir)

    return hda_node


def _set_lens_info_expressions(hda_node, selected, lenses_dir):
    """Set focal_length and horizontal_aperture expressions on the node.

    Since DialogScript doesn't natively support Python default expressions,
    we set them programmatically on the live node instance after the HDA
    is created and installed.

    Args:
        hda_node: The outer HDA hou.Node instance
        selected: List of (filename, display_name) tuples
        lenses_dir: Path to the lenses data directory
    """
    focal_lengths = []
    sensor_sizes_mm = []
    for filename, display_name in selected:
        fp = os.path.join(lenses_dir, filename)
        try:
            lens = get_lens_data(fp)
            fl = _parse_focal_length(display_name, lens)
            ss = lens["default_sensor_size"] * 1000.0
        except Exception:
            fl = 50.0
            ss = 36.0
        focal_lengths.append(fl)
        sensor_sizes_mm.append(ss)

    fl_tuple = "(" + ", ".join(f"{v:.2f}" for v in focal_lengths) + ")"
    ss_tuple = "(" + ", ".join(f"{v:.2f}" for v in sensor_sizes_mm) + ")"

    fl_expr = f'{fl_tuple}[hou.pwd().evalParm("lens_select")]'
    ha_expr = (f'{ss_tuple}[hou.pwd().evalParm("lens_select")]'
               f' * hou.pwd().evalParm("sensor_scale")')

    try:
        p = hda_node.parm("focal_length")
        if p:
            p.setExpression(fl_expr, hou.exprLanguage.Python)
            _log_info("Set focal_length expression")
    except Exception as e:
        _log_warn(f"Could not set focal_length expression: {e}")

    try:
        p = hda_node.parm("horizontal_aperture")
        if p:
            p.setExpression(ha_expr, hou.exprLanguage.Python)
            _log_info("Set horizontal_aperture expression")
    except Exception as e:
        _log_warn(f"Could not set horizontal_aperture expression: {e}")


def _warmup_all_callback(kwargs):
    """Button callback: cycle through all lenses to warm up Karma's shader cache.

    Called from the HDA's warmup_btn via:
        import lentilkarma_houdini; lentilkarma_houdini._warmup_all_callback(kwargs)
    """
    import threading
    import time
    import hdefereval

    node = kwargs['node']
    parm = node.parm('lens_select')
    delay = node.evalParm('warmup_delay')

    viewer = None
    for pt in hou.ui.curDesktop().paneTabs():
        if pt.type() == hou.paneTabType.SceneViewer:
            try:
                pt.currentHydraRenderer()
                viewer = pt
                break
            except Exception:
                pass

    if not viewer:
        hou.ui.displayMessage('No Solaris viewport found.',
                              title='LentilKarma')
        return
    if getattr(hou.session, '_ll_running', False):
        hou.ui.displayMessage('Warmup already running. Cancel first.',
                              title='LentilKarma')
        return

    try:
        num = len(parm.menuItems())
    except Exception:
        num = 84
    orig = parm.eval()
    rend = viewer.currentHydraRenderer()
    hou.session._ll_running = True
    hou.session._ll_cancel = False
    t0 = time.time()
    print('[LentilKarma] Warmup: %d lenses, %.0fs delay (~%.0fm est)'
          % (num, delay, num * delay / 60))
    hou.ui.setStatusMessage('LentilKarma warmup: 0/%d' % num)

    def _step(i):
        if getattr(hou.session, '_ll_cancel', False) or i >= num:
            def _restore():
                parm.set(orig)
                viewer.setHydraRenderer('GL')
                def _final():
                    viewer.setHydraRenderer(rend)
                    hou.session._ll_running = False
                    e = time.time() - t0
                    c = getattr(hou.session, '_ll_cancel', False)
                    if c:
                        msg = 'Cancelled (%d/%d, %.0fs)' % (i, num, e)
                    else:
                        msg = 'Complete! (%d lenses, %.0fs)' % (num, e)
                    hou.ui.setStatusMessage('LentilKarma warmup: ' + msg)
                    print('[LentilKarma] Warmup ' + msg)
                hdefereval.executeDeferred(_final)
            hdefereval.executeDeferred(_restore)
            return

        def _change():
            if getattr(hou.session, '_ll_cancel', False):
                _step(num)
                return
            parm.set(i)
            viewer.setHydraRenderer('GL')
            def _restart():
                if getattr(hou.session, '_ll_cancel', False):
                    _step(num)
                    return
                viewer.setHydraRenderer(rend)
                r = (num - i - 1) * delay
                hou.ui.setStatusMessage(
                    'LentilKarma warmup: %d/%d (~%.0fm remaining)'
                    % (i + 1, num, r / 60))
                print('[LentilKarma] Warmup: lens %d/%d' % (i + 1, num))
                t = threading.Timer(
                    delay,
                    lambda: hdefereval.executeDeferred(
                        lambda: _step(i + 1)))
                t.daemon = True
                t.start()
            hdefereval.executeDeferred(_restart)
        hdefereval.executeDeferred(_change)
    _step(0)


def _cancel_warmup_callback(kwargs):
    """Button callback: cancel an in-progress warmup cycle.

    Called from the HDA's warmup_cancel_btn via:
        import lentilkarma_houdini; lentilkarma_houdini._cancel_warmup_callback(kwargs)
    """
    if getattr(hou.session, '_ll_running', False):
        hou.session._ll_cancel = True
        hou.ui.setStatusMessage('LentilKarma warmup: cancelling...')
        print('[LentilKarma] Warmup cancellation requested')
    else:
        hou.ui.setStatusMessage('No warmup in progress.')


def compile_lens_shader(vfl_filepath, extra_include_dirs=None,
                        skip_source_fix=False):
    """Compile a VFL lens shader into an HDA (VOP asset) and standalone .vex.

    Uses vcc with -O vop -l to create a Houdini Digital Asset that
    can be instantiated as a VOP node and referenced by Karma cameras.
    Also compiles a standalone .vex file for use with info:sourceAsset
    in the USD lens material.

    Args:
        vfl_filepath: Path to the .vfl source file
        extra_include_dirs: Optional list of additional -I paths for vcc
        skip_source_fix: If True, skip _fix_hda_vfl_source (used by the
            header/wrapper pattern where the wrapper VFL is tiny and
            vcc correctly stores only the outer code in CVexVflCode)

    Returns:
        tuple: (hda_path, vex_path) — paths to the compiled .hda and .vex files
    """
    # Output HDA goes to otls dir so Houdini can find it
    basename = os.path.splitext(os.path.basename(vfl_filepath))[0]
    hda_path = os.path.join(get_otls_dir(), f"{basename}.hda")
    _log_info(f"Compiling VFL -> HDA: {vfl_filepath}")
    _log_info(f"HDA output: {hda_path}")

    # Include path for lentilkarma_core.h
    script_dir = os.path.dirname(os.path.abspath(__file__))
    include_dir = os.path.join(script_dir, "..", "vex")
    include_dir = os.path.normpath(include_dir)
    _log_info(f"VEX include dir: {include_dir}")

    # Check that lentilkarma_core.h exists
    core_h = os.path.join(include_dir, "lentilkarma_core.h")
    if not os.path.exists(core_h):
        _log_error(f"lentilkarma_core.h not found at: {core_h}")
        raise FileNotFoundError(f"lentilkarma_core.h not found at: {core_h}")

    # Build include directories list
    include_dirs = [include_dir]
    if extra_include_dirs:
        include_dirs.extend(extra_include_dirs)

    # Compile VFL to HDA with vcc -O vop -l
    cmd = ['vcc', '-O', 'vop']
    for d in include_dirs:
        cmd.extend(['-I', d])
    cmd.extend(['-l', hda_path, vfl_filepath])
    _log_info(f"Running: {' '.join(cmd)}")

    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    dt = time.time() - t0

    if result.stdout:
        _log_info(f"vcc stdout: {result.stdout}")
    if result.stderr:
        _log_error(f"vcc stderr:\n{result.stderr}")

    if result.returncode != 0:
        _log_error(f"vcc failed with exit code {result.returncode} after {dt:.2f}s")
        raise RuntimeError(f"vcc compilation failed (exit code {result.returncode}):\n{result.stderr}")

    if not os.path.exists(hda_path):
        _log_error(f"vcc produced no HDA file: {hda_path}")
        raise RuntimeError(f"vcc produced no HDA file: {hda_path}")

    hda_size = os.path.getsize(hda_path)
    _log_info(f"HDA compiled: {hda_path} ({hda_size} bytes, {dt:.2f}s)")

    # Install the HDA in the current Houdini session
    _log_info(f"Installing HDA: {hda_path}")
    hou.hda.installFile(hda_path)
    _log_info("HDA installed successfully")

    # Check if HDA source was truncated (only for monolithic VFL shaders).
    # With the header/wrapper pattern, vcc correctly stores only the outer
    # code (#include) in CVexVflCode — this is NOT truncation, so skip.
    if not skip_source_fix:
        _fix_hda_vfl_source(hda_path, vfl_filepath, include_dir)

    # Also compile standalone .vex for use with info:sourceAsset in the
    # USD lens material. This avoids the need for NDR registration that
    # info:id requires (only built-in Karma shaders are in the NDR).
    vex_path = os.path.join(get_output_dir(), f"{basename}.vex")
    vex_cmd = ['vcc']
    for d in include_dirs:
        vex_cmd.extend(['-I', d])
    vex_cmd.extend(['-o', vex_path, vfl_filepath])
    _log_info(f"Compiling standalone VEX: {' '.join(vex_cmd)}")

    t0 = time.time()
    vex_result = subprocess.run(vex_cmd, capture_output=True, text=True, timeout=120)
    vex_dt = time.time() - t0

    if vex_result.stdout:
        _log_info(f"vcc (vex) stdout: {vex_result.stdout}")
    if vex_result.stderr:
        _log_warn(f"vcc (vex) stderr:\n{vex_result.stderr}")

    if vex_result.returncode != 0 or not os.path.exists(vex_path):
        _log_warn(f"Standalone .vex compilation failed (non-fatal): "
                  f"exit code {vex_result.returncode}")
        vex_path = None
    else:
        vex_size = os.path.getsize(vex_path)
        _log_info(f"VEX compiled: {vex_path} ({vex_size} bytes, {vex_dt:.2f}s)")

    return hda_path, vex_path


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def _find_or_create_vop_node(optype_name):
    """Find an existing VOP node of the given type, or create one in /mat.

    CVEX lens shaders must live in /mat (not inside a materiallibrary LOP,
    which is for surface shaders only). The camera's 'Lens Shader VOP'
    parameter references the node path directly (e.g., /mat/lentilkarma).

    Returns:
        hou.Node: The VOP node instance
    """
    installed_type = _find_installed_type(optype_name)

    if not installed_type:
        _log_warn(f"Could not find installed node type for '{optype_name}'")
        _log_info("Available types with 'lentilkarma':")
        for cat_name, cat in hou.nodeTypeCategories().items():
            for type_name in cat.nodeTypes():
                if "lentilkarma" in type_name.lower():
                    _log_info(f"  {cat_name}/{type_name}")
        return None

    # Check if a node of this type already exists in /mat
    mat_net = hou.node("/mat")
    if mat_net:
        for child in mat_net.allSubChildren():
            if child.type().name() == installed_type:
                _log_info(f"Found existing node in /mat: {child.path()}")
                return child

    # Create the node in /mat context
    if mat_net is None:
        _log_error("No /mat network found")
        return None

    try:
        node = mat_net.createNode(installed_type, optype_name)
        _log_info(f"Created node in /mat: {node.path()}")
        return node
    except Exception as e:
        _log_error(f"Failed to create node in /mat: {e}")
        return None


# ---------------------------------------------------------------------------
# Karma NDR Registration — register shader in karmaShaderNodes.json
# ---------------------------------------------------------------------------

def _build_shader_ndr_entry(opname, is_combined=False):
    """Build a karmaShaderNodes.json entry for our lens shader.

    The entry format matches kma_physicallens: name, inputs[], outputs[].
    Uses legacy CVEX convention (x, y, Time, dofx, dofy, aspect).

    NOTE: NDR registration is NOT required for legacy CVEX lens shaders
    to work with Karma. This is kept as an optional utility.
    """
    inputs = []

    # Hidden renderer-provided inputs (legacy CVEX convention)
    for name, typ, default in [
        ("x", "float", 0), ("y", "float", 0), ("Time", "float", 0),
        ("dofx", "float", 0), ("dofy", "float", 0),
        ("aspect", "float", 1),
    ]:
        inputs.append({"name": name, "type": typ, "default": default})

    # Combined shader lens selector
    if is_combined:
        inputs.append({"name": "lens_select", "type": "int", "default": 0})

    # User parameters
    for name, typ, default in [
        ("lens_fstop", "float", 0), ("lens_focus_dist", "float", 0),
        ("chromatic_aberration", "float", 0), ("exposure", "float", 0),
        ("aperture_ray_guiding", "int", 1),
        ("aperture_auto_exposure", "int", 1),
        ("tilt_shift_angle_x", "float", 0), ("tilt_shift_angle_y", "float", 0),
        ("tilt_shift_offset_x", "float", 0), ("tilt_shift_offset_y", "float", 0),
        ("dof_factor", "float", 1), ("dof_remove", "float", 0),
        ("flip", "int", 1), ("global_scale", "float", 1),
        ("distortion_amount", "float", 0), ("distortion_exponent", "float", 2),
        ("bokeh_swirliness", "float", 0), ("sensor_scale", "float", 1),
    ]:
        inputs.append({"name": name, "type": typ, "default": default})

    outputs = [
        {"name": "P", "type": "float[3]", "default": [0, 0, 0]},
        {"name": "I", "type": "float[3]", "default": [0, 0, 0]},
        {"name": "tint", "type": "float[3]", "default": [1, 1, 1]},
    ]

    return {"name": opname, "inputs": inputs, "outputs": outputs}


def _register_shader_in_karma_ndr(opname, is_combined=False):
    """Register our lens shader in Karma's karmaShaderNodes.json.

    Karma's NDR discovery plugin (BRAY_SdrKarmaDiscovery) reads shader
    definitions from $HFS/houdini/karmaShaderNodes.json. Adding our shader
    there allows info:id to resolve, enabling the editmaterialproperties
    approach that prewarms shader compilation.

    NOTE: Houdini must be restarted after the first registration for the
    NDR to pick up the new entry (the Sdr is initialized once at startup).

    Args:
        opname: VEX operator name (must match info:id and #pragma opname)
        is_combined: If True, includes lens_select parameter

    Returns:
        bool: True if registration succeeded
    """
    import json

    # Find karmaShaderNodes.json
    hfs = hou.getenv("HFS", "")
    if not hfs:
        _log_error("$HFS not set — cannot register shader with Karma NDR")
        return False

    json_path = os.path.join(hfs, "houdini", "karmaShaderNodes.json")
    if not os.path.exists(json_path):
        _log_error(f"karmaShaderNodes.json not found: {json_path}")
        return False

    _log_info(f"Registering shader '{opname}' in Karma NDR: {json_path}")

    # Read existing entries
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            entries = json.load(f)
    except Exception as e:
        _log_error(f"Failed to read karmaShaderNodes.json: {e}")
        return False

    if not isinstance(entries, list):
        _log_error("karmaShaderNodes.json has unexpected format (expected array)")
        return False

    # Check if our shader is already registered
    existing_idx = None
    for i, entry in enumerate(entries):
        if entry.get("name") == opname:
            existing_idx = i
            break

    # Build our entry
    new_entry = _build_shader_ndr_entry(opname, is_combined)

    if existing_idx is not None:
        entries[existing_idx] = new_entry
        _log_info(f"Updated existing NDR entry at index {existing_idx}")
    else:
        entries.append(new_entry)
        _log_info(f"Added new NDR entry (total: {len(entries)})")

    # Write back
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(entries, f, indent=2)
        _log_info(f"Karma NDR updated: {json_path}")
        _log_info("NOTE: Restart Houdini for the NDR changes to take effect")
        return True
    except PermissionError:
        _log_error(f"Permission denied writing to {json_path}. "
                   f"Run Houdini as administrator or manually add the entry.")
        _log_info(f"Entry to add: {json.dumps(new_entry, indent=2)}")
        return False
    except Exception as e:
        _log_error(f"Failed to write karmaShaderNodes.json: {e}")
        return False


# ---------------------------------------------------------------------------
# USD Lens Material generation
# ---------------------------------------------------------------------------

def _generate_lens_material_usda(opname="lentilkarma", is_combined=False,
                                  lens_names=None, vex_path=None):
    """Generate a USDA file defining a Karma lens material for our shader.

    This mirrors the structure of SideFX's kma_camera_lens.usd so that Karma
    recognises our shader as a proper lens material. The Camera LOP's
    "Lens Material" parameter can then point to /materials/lentilkarma_material.

    NOTE: The info:id in the USDA requires the shader to be registered in
    Karma's NDR (karmaShaderNodes.json). Only built-in shaders like
    kma_physicallens are registered there. For custom VEX lens shaders,
    either register with the NDR or use the VOP fallback path on the camera.

    Args:
        opname: VEX operator name (info:id on the Shader prim)
        is_combined: If True, include lens_select parameter
        lens_names: List of (index, display_name) for lens_select menu
        vex_path: Path to the compiled .vex file (kept for future NDR use)

    Returns:
        str: Path to the generated .usda file
    """
    mat_name = "lentilkarma_material"
    mat_path = f"/materials/{mat_name}"
    shader_path = f"{mat_path}/{opname}"

    # --- Build dialogScript (Houdini parameter UI definition) ---
    ds_lines = []
    ds_lines.append('{')
    ds_lines.append('    name    usdmaterial')

    # Hidden legacy CVEX inputs (provided by Karma to compiled VOPs)
    hidden_float = [
        ("x", "NDC X", "0"),
        ("y", "NDC Y", "0"),
        ("Time", "Time", "0"),
        ("dofx", "DOF X", "0"),
        ("dofy", "DOF Y", "0"),
        ("aspect", "Aspect Ratio", "1"),
    ]

    for name, label, default in hidden_float:
        ds_lines.append(f'    parm {{')
        ds_lines.append(f'        name    \\"{name}\\"')
        ds_lines.append(f'        label   \\"{label}\\"')
        ds_lines.append(f'        type    float')
        ds_lines.append(f'        invisible')
        ds_lines.append(f'        default {{ \\"{default}\\" }}')
        ds_lines.append(f'        range   {{ 0 1 }}')
        ds_lines.append(f'        parmtag {{ \\"parmvop\\" \\"1\\" }}')
        ds_lines.append(f'        parmtag {{ \\"shaderparmcontexts\\" \\"cvex\\" }}')
        ds_lines.append(f'    }}')

    # Lens select dropdown (combined shader only)
    if is_combined and lens_names:
        ds_lines.append(f'    parm {{')
        ds_lines.append(f'        name    \\"lens_select\\"')
        ds_lines.append(f'        label   \\"Lens\\"')
        ds_lines.append(f'        type    integer')
        ds_lines.append(f'        default {{ \\"0\\" }}')
        ds_lines.append(f'        menu {{')
        for idx, display in lens_names:
            safe_display = display.replace('"', '\\\\\\"')
            ds_lines.append(f'            \\"{idx}\\"    \\"{safe_display}\\"')
        ds_lines.append(f'        }}')
        ds_lines.append(f'        range   {{ 0 {len(lens_names) - 1} }}')
        ds_lines.append(f'        parmtag {{ \\"parmvop\\" \\"1\\" }}')
        ds_lines.append(f'        parmtag {{ \\"shaderparmcontexts\\" \\"cvex\\" }}')
        ds_lines.append(f'    }}')

    # User-visible float parameters
    user_floats = [
        ("lens_fstop", "F-Stop", "0", "0 32"),
        ("lens_focus_dist", "Focus Distance", "0", "0 100"),
        ("chromatic_aberration", "Chromatic Aberration", "0", "0 1"),
        ("exposure", "Exposure", "0", "-5 5"),
        ("dof_factor", "DOF Factor", "1", "0 2"),
        ("dof_remove", "DOF Remove", "0", "0 1"),
        ("global_scale", "Global Scale", "1", "0.01 10"),
        ("distortion_amount", "Distortion Amount", "0", "-1 1"),
        ("distortion_exponent", "Distortion Exponent", "2", "0 10"),
        ("bokeh_swirliness", "Bokeh Swirliness", "0", "0 1"),
        ("sensor_scale", "Sensor Scale", "1", "0.1 4"),
        ("tilt_shift_angle_x", "Tilt X", "0", "-1 1"),
        ("tilt_shift_angle_y", "Tilt Y", "0", "-1 1"),
        ("tilt_shift_offset_x", "Shift X", "0", "-10 10"),
        ("tilt_shift_offset_y", "Shift Y", "0", "-10 10"),
    ]
    for name, label, default, rng in user_floats:
        ds_lines.append(f'    parm {{')
        ds_lines.append(f'        name    \\"{name}\\"')
        ds_lines.append(f'        label   \\"{label}\\"')
        ds_lines.append(f'        type    float')
        ds_lines.append(f'        default {{ \\"{default}\\" }}')
        ds_lines.append(f'        range   {{ {rng} }}')
        ds_lines.append(f'        parmtag {{ \\"parmvop\\" \\"1\\" }}')
        ds_lines.append(f'        parmtag {{ \\"shaderparmcontexts\\" \\"cvex\\" }}')
        ds_lines.append(f'    }}')

    # User-visible integer/toggle parameters
    user_ints = [
        ("aperture_ray_guiding", "Ray Guiding", "1"),
        ("aperture_auto_exposure", "Auto Exposure", "1"),
        ("flip", "Flip Image", "1"),
    ]
    for name, label, default in user_ints:
        ds_lines.append(f'    parm {{')
        ds_lines.append(f'        name    \\"{name}\\"')
        ds_lines.append(f'        label   \\"{label}\\"')
        ds_lines.append(f'        type    toggle')
        ds_lines.append(f'        default {{ \\"{default}\\" }}')
        ds_lines.append(f'        parmtag {{ \\"parmvop\\" \\"1\\" }}')
        ds_lines.append(f'        parmtag {{ \\"shaderparmcontexts\\" \\"cvex\\" }}')
        ds_lines.append(f'    }}')

    ds_lines.append('}')
    dialog_script = '\\n'.join(ds_lines)

    # --- Build USD inputs on the Material prim ---
    # All parameters are declared as inputs on the Material, then connected
    # to the child Shader prim (same pattern as kma_camera_lens.usd)
    mat_inputs = []
    shader_connections = []

    # Hidden legacy CVEX inputs
    for name, label, default in hidden_float:
        mat_inputs.append(f'        float inputs:{name} = {default} (')
        mat_inputs.append(f'            displayName = "{label}"')
        mat_inputs.append(f'        )')
        shader_connections.append(
            f'            float inputs:{name}.connect = <{mat_path}.inputs:{name}>')

    # lens_select (combined only)
    if is_combined:
        mat_inputs.append(f'        int inputs:lens_select = 0 (')
        mat_inputs.append(f'            displayName = "Lens"')
        mat_inputs.append(f'        )')
        shader_connections.append(
            f'            int inputs:lens_select.connect = <{mat_path}.inputs:lens_select>')

    # User float params
    for name, label, default, _ in user_floats:
        mat_inputs.append(f'        float inputs:{name} = {default} (')
        mat_inputs.append(f'            displayName = "{label}"')
        mat_inputs.append(f'        )')
        shader_connections.append(
            f'            float inputs:{name}.connect = <{mat_path}.inputs:{name}>')

    # User int params
    for name, label, default in user_ints:
        mat_inputs.append(f'        int inputs:{name} = {default} (')
        mat_inputs.append(f'            displayName = "{label}"')
        mat_inputs.append(f'        )')
        shader_connections.append(
            f'            int inputs:{name}.connect = <{mat_path}.inputs:{name}>')

    mat_inputs_str = '\n'.join(mat_inputs)
    shader_conn_str = '\n'.join(shader_connections)

    # --- Determine shader identification ---
    # Karma's lens shader system ONLY supports info:id (not info:sourceAsset).
    # The shader must be registered in Karma's NDR (karmaShaderNodes.json) for
    # info:id to resolve. If not registered, the material approach won't work
    # and the VOP fallback path should be used instead.
    shader_id_lines = f'            uniform token info:id = "{opname}"'
    _log_info(f"USDA shader: info:id = {opname}")

    # --- Assemble the full USDA ---
    usda = f'''#usda 1.0
(
    doc = "LentilKarma camera lens material"
    metersPerUnit = 1
    upAxis = "Y"
)

def Scope "materials"
{{
    def Material "{mat_name}" (
        customData = {{
            dictionary houdini = {{
                string dialogScript = """{dialog_script}"""
            }}
        }}
    )
    {{
{mat_inputs_str}
        token outputs:kma:surface.connect = <{shader_path}.outputs:surface>

        def Shader "{opname}"
        {{
{shader_id_lines}
{shader_conn_str}
            token outputs:surface
        }}
    }}
}}
'''

    # Write to output directory
    output_dir = get_output_dir()
    usda_path = os.path.join(output_dir, "lentilkarma_camera_lens.usda")
    with open(usda_path, 'w') as f:
        f.write(usda)

    _log_info(f"Generated lens material USDA: {usda_path}")
    return usda_path


# ---------------------------------------------------------------------------
# LOP Stage Setup — lens material and camera configuration
# ---------------------------------------------------------------------------

def _create_lens_material_lop(usda_path, camera_node=None, stage_net=None):
    """Create an Edit Material Properties LOP for the lens material.

    Follows the exact same pattern as SideFX's setupKarmaCameraLensMaterial():
    1. Creates an 'editmaterialproperties' LOP
    2. Configures it with reftype='reffile' pointing to our USDA
    3. Presses 'createparms' to auto-generate material parameters
    4. Inserts it above the camera node in the LOP chain
    5. Links the camera's Lens Material parameter via expression

    Args:
        usda_path: Path to the lentilkarma_camera_lens.usda file
        camera_node: Camera LOP node (auto-discovered if None)
        stage_net: LOP network node (default: /stage)

    Returns:
        hou.Node or None: The created/found Edit Material Properties LOP
    """
    if stage_net is None:
        stage_net = hou.node("/stage")
    if not stage_net:
        _log_error("No /stage network found")
        return None

    node_name = "lentilkarmamaterial1"

    # Check if it already exists
    existing = stage_net.node(node_name)
    if existing:
        # Update the reference file path
        try:
            existing.parm("reffilepath").set(usda_path)
            existing.parm("createparms").pressButton()
            _log_info(f"Updated existing lens material LOP: {existing.path()}")
        except Exception as e:
            _log_warn(f"Could not update existing node: {e}")
        return existing

    # Find camera node if not provided
    if camera_node is None:
        camera_node = _find_camera_lop(stage_net)

    try:
        import toolutils
    except ImportError:
        _log_warn("toolutils not available — creating node manually")
        toolutils = None

    try:
        # Create editmaterialproperties LOP (same node type SideFX uses)
        mtl_node = stage_net.createNode('editmaterialproperties', node_name)
        _log_info(f"Created lens material LOP: {mtl_node.path()}")

        # Insert above camera if we have one
        if camera_node:
            if toolutils:
                toolutils.insertNodeAbove(camera_node, mtl_node, 0)
            else:
                # Manual wiring fallback
                inputs = camera_node.inputs()
                if inputs and inputs[0] is not None:
                    mtl_node.setInput(0, inputs[0])
                    camera_node.setInput(0, mtl_node)
                else:
                    camera_node.setInput(0, mtl_node)

            if camera_node.inputs():
                mtl_node.moveToGoodPosition(move_unconnected=False)
            else:
                mtl_node.setPosition(
                    camera_node.position() + hou.Vector2((0.0, 1.0)))
        else:
            # No camera — wire into the chain before display node
            _wire_lop_into_chain(mtl_node, stage_net)

        # Configure the material node (same as createKarmaLensMaterial)
        mtl_node.parm('reftype').set('reffile')
        mtl_node.parm('primpattern').set('/materials/lentilkarma_material')
        mtl_node.parm('reffilepath').set(usda_path)

        # Set primpath relative to the camera (SideFX pattern)
        if camera_node:
            try:
                path_parm = 'primpath' if camera_node.evalParm('createprims') else 'primpattern'
            except hou.OperationFailed:
                path_parm = 'primpattern'
            mtl_node.parm('primpath').set(
                '`chs("../{}/{}")`/`$OS`'.format(camera_node.name(), path_parm))
        else:
            mtl_node.parm('primpath').set('/materials/lentilkarma_material')

        # Auto-generate material parameters from the USDA
        _log_info("Pressing createparms to generate material parameters...")
        mtl_node.parm('createparms').pressButton()

        mtl_node.setColor(hou.Color(0.3, 0.5, 0.8))

        stage_net.layoutChildren()
        _log_info(f"Lens material LOP configured: {mtl_node.path()}")
        return mtl_node

    except Exception as e:
        _log_error(f"Failed to create lens material LOP: {e}")
        _log_error(traceback.format_exc())
        return None


def _find_camera_lop(stage_net):
    """Find the first Camera LOP in the stage network."""
    for child in stage_net.children():
        if child.type().name() in ("camera", "cam"):
            return child
    # Check one level deep
    for child in stage_net.children():
        try:
            for sub in child.children():
                if sub.type().name() in ("camera", "cam"):
                    return sub
        except hou.OperationFailed:
            pass
    return None


def _wire_lop_into_chain(new_node, stage_net):
    """Wire a new LOP node into the existing chain before the display node."""
    display_node = None
    for child in stage_net.children():
        if child.isDisplayFlagSet():
            display_node = child
            break

    if not display_node or display_node == new_node:
        return

    inputs = display_node.inputs()
    if inputs and inputs[0] is not None:
        prev_node = inputs[0]
        new_node.setInput(0, prev_node)
        display_node.setInput(0, new_node)
        _log_info(f"Wired {new_node.name()} between "
                  f"{prev_node.name()} and {display_node.name()}")
    else:
        display_node.setInput(0, new_node)
        _log_info(f"Connected {display_node.name()} to {new_node.name()}")


def _try_configure_camera_material(mtl_node, camera_node=None, stage_net=None):
    """Link the camera's Lens Material parameter to the material node.

    Sets the camera's lens material parameter to an expression that
    references the material node's primpath — exactly as SideFX does.

    Returns True if successful.
    """
    if stage_net is None:
        stage_net = hou.node("/stage")
    if not stage_net:
        return False

    if camera_node is None:
        camera_node = _find_camera_lop(stage_net)
    if not camera_node:
        _log_info("No Camera LOP found for material config")
        return False

    _log_info(f"Configuring camera material: {camera_node.path()}")

    # The expression references the material node's primpath
    # (same pattern as SideFX: `chs("../karmalensmaterial1/primpath")`)
    mtl_expr = '`chs("../{}/primpath")`'.format(mtl_node.name())

    # Try known parameter names for the lens material binding
    # From the screenshot: the parm name is "karma:camera:material:binding"
    # which Houdini encodes as an xn__ name
    material_set = False
    binding_parm_name = None
    for parm in camera_node.parms():
        pname = parm.name().lower()
        label = parm.parmTemplate().label().lower()
        # Match by label "Lens Material" or by name containing material+binding
        # but skip the _control companion parameter
        if 'control' in pname:
            continue
        if ('lens material' in label or
            ('material' in pname and 'binding' in pname) or
            ('lens' in pname and 'material' in pname)):
            try:
                parm.set(mtl_expr)
                binding_parm_name = parm.name()
                _log_info(f"  Set lens material: {parm.name()} = {mtl_expr}")
                material_set = True
                break
            except Exception as e:
                _log_warn(f"  Failed to set {parm.name()}: {e}")

    # Set the companion _control parameter to "set" so the property is authored.
    # In LOPs, each USD property has a _control parameter that must be "set"
    # for the property to be written to the stage.
    if material_set and binding_parm_name:
        for parm in camera_node.parms():
            pname = parm.name().lower()
            if ('material' in pname and 'binding' in pname and 'control' in pname):
                try:
                    parm.set("set")
                    _log_info(f"  Set binding control: {parm.name()} = 'set'")
                except Exception:
                    # Try integer value (some controls use int enum)
                    try:
                        parm.set(1)
                        _log_info(f"  Set binding control: {parm.name()} = 1")
                    except Exception as e:
                        _log_warn(f"  Could not set binding control {parm.name()}: {e}")
                break

    # Also try to enable "Use Lens Shader" if we found the material parm
    if material_set:
        for parm in camera_node.parms():
            label = parm.parmTemplate().label().lower()
            if 'use lens shader' in label:
                try:
                    parm.set(1)
                    _log_info(f"  Enabled: {parm.name()} (Use Lens Shader)")
                except Exception:
                    pass
                break

    return material_set


# ---------------------------------------------------------------------------
# LOP Stage Setup — camera configuration for lens shaders
# ---------------------------------------------------------------------------

def _try_configure_camera(vop_path, stage_net):
    """Attempt to auto-configure the camera to use the lens shader.

    Searches for Camera LOPs and tries to set the Lens Shader VOP
    parameter. Returns True if at least one parameter was set.
    """
    # Find camera LOPs
    cameras = []
    for child in stage_net.children():
        if child.type().name() in ("camera", "cam"):
            cameras.append(child)
    # Also check one level deep (subnets)
    for child in stage_net.children():
        try:
            for sub in child.children():
                if sub.type().name() in ("camera", "cam"):
                    if sub not in cameras:
                        cameras.append(sub)
        except hou.OperationFailed:
            pass  # Leaf nodes don't support children()

    if not cameras:
        _log_info("No Camera LOP found in /stage")
        return False

    cam = cameras[0]
    _log_info(f"Found Camera LOP: {cam.path()}")

    # Discover and log all lens-related parameters
    lens_parms = {}
    for parm in cam.parms():
        name_lower = parm.name().lower()
        if any(kw in name_lower for kw in ['lens', 'shader', 'vop']):
            lens_parms[parm.name()] = parm
            _log_info(f"  Camera parm: {parm.name()} "
                      f"[{parm.parmTemplate().label()}] = {parm.eval()}")

    # Try to set "Use Lens Shader" toggle
    # The USD property is karma:camera:use_lensshader; the encoded Houdini
    # parm name varies by Houdini version.
    enable_set = False
    for name in ['xn__karmacamerause_lensshader_control',
                 'xn__karmacamerause_lensshader_kfbg',
                 'xn__karmarendereruselensshader_control',
                 'xn__karmalensshaderuselensshader_control',
                 'uselensshader']:
        p = cam.parm(name)
        if p is not None:
            try:
                p.set(1)
                _log_info(f"  Enabled lens shader: {name}")
                enable_set = True
                break
            except Exception:
                pass
    # Also try any discovered parm with "use" and "lens" in name
    if not enable_set:
        for name, p in lens_parms.items():
            if 'use' in name.lower() and 'lens' in name.lower():
                try:
                    p.set(1)
                    _log_info(f"  Enabled lens shader (discovered): {name}")
                    enable_set = True
                    break
                except Exception:
                    pass

    # Try to set "Lens Shader VOP" path
    # The USD property is karma:camera:lensshadervop; the hidden lensshader
    # property calls shaderString() on the VOP node at this path.
    # From RenderPropertiesKA.json the reference is xn__karmacameralensshadervop_4fbg.
    vop_set = False
    for name in ['xn__karmacameralensshadervop_4fbg',
                 'xn__karmacameralensshadervop_control',
                 'xn__karmarendererlensshadervop_control',
                 'xn__karmalensshaderlensshadervop_control',
                 'lensshadervop']:
        p = cam.parm(name)
        if p is not None:
            try:
                p.set(vop_path)
                _log_info(f"  Set Lens Shader VOP: {name} = {vop_path}")
                vop_set = True
                break
            except Exception:
                pass
    # Also try any discovered parm with "vop" in name
    if not vop_set:
        for name, p in lens_parms.items():
            if 'vop' in name.lower():
                try:
                    p.set(vop_path)
                    _log_info(f"  Set Lens Shader VOP (discovered): "
                              f"{name} = {vop_path}")
                    vop_set = True
                    break
                except Exception:
                    pass

    if not enable_set and not vop_set:
        _log_warn("Could not auto-configure camera lens shader parameters")
        _log_info("Run lentilkarma_houdini.discover_camera_parms() "
                  "to find parameter names")
    return enable_set or vop_set


def setup_lens_in_stage(vop_path=None, stage_net=None):
    """Configure the camera in /stage to use the lens shader (user-callable).

    Tries the modern lens material approach first (editmaterialproperties),
    then falls back to legacy VOP path if needed.

    Args:
        vop_path: Explicit VOP path (auto-discovered if None)
        stage_net: LOP network (default: /stage)

    Returns:
        dict with setup results
    """
    if stage_net is None:
        stage_net = hou.node("/stage")
    if not stage_net:
        _log_error("No /stage network found")
        return None

    material_ok = False
    camera_node = _find_camera_lop(stage_net)

    # Check if the lens material USDA exists and create LOP if needed
    output_dir = get_output_dir()
    usda_path = os.path.join(output_dir, "lentilkarma_camera_lens.usda")
    if os.path.exists(usda_path):
        mtl_lop = _create_lens_material_lop(
            usda_path, camera_node=camera_node, stage_net=stage_net)
        if mtl_lop:
            material_ok = _try_configure_camera_material(
                mtl_lop, camera_node=camera_node, stage_net=stage_net)

    # Fallback: legacy VOP path
    vop = _find_lentilkarma_vop(vop_path)
    vop_ok = False
    if not material_ok and vop:
        vop_ok = _try_configure_camera(vop.path(), stage_net)

    if not material_ok and not vop_ok:
        if not vop:
            _log_error("No lentilkarma VOP found in /mat. Compile shaders first.")
        else:
            _log_warn("Could not auto-configure camera. Use discover_camera_parms().")

    result = {
        'material_configured': material_ok,
        'vop': vop,
        'vop_path': vop.path() if vop else None,
        'camera_configured': material_ok or vop_ok,
    }
    _log_info(f"Stage setup complete: {result}")
    return result


def discover_camera_parms(camera_path=None):
    """Print all parameters on a Camera LOP for debugging lens setup.

    Use this to find the correct parameter names for lens shader
    configuration if auto-configuration fails.

    Usage:
        import lentilkarma_houdini
        lentilkarma_houdini.discover_camera_parms()
    """
    if camera_path:
        cam = hou.node(camera_path)
    else:
        stage = hou.node("/stage")
        cam = None
        if stage:
            for child in stage.children():
                if child.type().name() in ("camera", "cam"):
                    cam = child
                    break

    if not cam:
        print("No Camera LOP found. Pass camera_path='/stage/camera1'")
        return

    print(f"\nCamera: {cam.path()}")
    print(f"Type:   {cam.type().name()}")

    # Lens/shader/material parameters
    print(f"\n{'='*70}")
    print("Lens/Shader/Material/Karma parameters:")
    print(f"{'='*70}")
    found = False
    for parm in cam.parms():
        name_lower = parm.name().lower()
        if any(kw in name_lower for kw in ['lens', 'shader', 'material',
                                            'vop', 'karma', 'renderer']):
            template = parm.parmTemplate()
            try:
                val = parm.eval()
            except Exception:
                val = "<error>"
            print(f"  {parm.name()}")
            print(f"    Label: {template.label()}")
            print(f"    Type:  {template.type()}")
            print(f"    Value: {val}")
            found = True

    if not found:
        print("  (none found — showing all parameters)")
        print(f"\n{'='*70}")
        print("All parameters:")
        print(f"{'='*70}")
        for parm in cam.parms():
            try:
                val = parm.eval()
            except Exception:
                val = "<error>"
            print(f"  {parm.name():50s} = {val}")


def apply_lens_to_camera(lens_filepath, camera_path=None, stage=None):
    """Generate a lens shader and configure a Karma camera to use it.

    This is the main user-facing function. It:
    1. Generates the specialized VEX shader from lens data
    2. Compiles it into an HDA (VOP asset)
    3. Installs the HDA and creates a VOP node instance
    4. Optionally configures the camera to use the lens shader

    Args:
        lens_filepath: Path to the .txt lens data file
        camera_path: LOP camera prim path (e.g., "/cameras/camera1")
        stage: Optional LOP network node (uses selected if None)

    Returns:
        dict: Info about the generated shader and lens
    """
    _log_info(f"=== apply_lens_to_camera ===")
    _log_info(f"Lens file: {lens_filepath}")

    # Parse lens data
    _log_info("Parsing lens data...")
    t0 = time.time()
    try:
        lens_data = get_lens_data(lens_filepath)
    except Exception as e:
        _log_error(f"Failed to parse lens data: {e}")
        _log_error(traceback.format_exc())
        raise

    lens_name = os.path.basename(lens_filepath).replace(".txt", "")
    _log_info(f"Lens: {lens_name}")
    _log_info(f"  Elements: {lens_data['lenses']}")
    _log_info(f"  F-number: f/{lens_data['f_number']}")
    _log_info(f"  Lens length: {lens_data['lens_length']*1000:.2f}mm")
    _log_info(f"  Sensor size: {lens_data['default_sensor_size']*1000:.2f}mm")
    _log_info(f"  Aperture idx: {lens_data['aperture_idx']}")
    _log_info(f"  Asphere surfaces: {len(lens_data['asphere_data'])}")
    _log_info(f"  Parsed in {time.time()-t0:.2f}s")

    # Generate VFL
    vfl_path = generate_lens_shader(lens_filepath)

    # Compile to HDA and standalone .vex
    hda_path, vex_path = compile_lens_shader(vfl_path)

    # Create VOP node instance
    optype = _lens_opname(lens_name)  # matches #pragma opname in the shader
    vop_node = None
    try:
        vop_node = _find_or_create_vop_node(optype)
    except Exception as e:
        _log_warn(f"Could not create VOP node: {e}")

    # Generate lens material USDA and configure the camera
    # (uses editmaterialproperties LOP, same as SideFX)
    stage_setup = None
    material_configured = False
    stage_net = hou.node("/stage")
    camera_node = _find_camera_lop(stage_net) if stage_net else None

    try:
        usda_path = _generate_lens_material_usda(
            opname=optype, is_combined=False, vex_path=vex_path)
        if usda_path and stage_net:
            mtl_lop = _create_lens_material_lop(
                usda_path, camera_node=camera_node, stage_net=stage_net)
            if mtl_lop:
                material_configured = _try_configure_camera_material(
                    mtl_lop, camera_node=camera_node, stage_net=stage_net)
    except Exception as e:
        _log_warn(f"Lens material setup failed: {e}")

    # Fallback: legacy VOP path
    if not material_configured and stage_net and vop_node:
        try:
            stage_setup = _try_configure_camera(vop_node.path(), stage_net)
        except Exception as e:
            _log_warn(f"Camera auto-config failed: {e}")
            _log_warn(traceback.format_exc())

    result = {
        "lens_name": lens_name,
        "opname": optype,
        "vfl_path": vfl_path,
        "hda_path": hda_path,
        "vex_path": vex_path,
        "vop_node": vop_node.path() if vop_node else None,
        "elements": lens_data["lenses"],
        "f_number": lens_data["f_number"],
        "lens_length_mm": lens_data["lens_length"] * 1000,
        "stage_setup": stage_setup or material_configured,
    }

    _log_info(f"=== Done: {lens_name} ===")
    _log_info(f"  VFL: {vfl_path}")
    _log_info(f"  HDA: {hda_path}")
    if vex_path:
        _log_info(f"  VEX: {vex_path}")
    if vop_node:
        _log_info(f"  VOP node: {vop_node.path()}")

    return result


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

# Common parameters shared across all lens shaders
_COMMON_FLOAT_PARMS = [
    # (name, label, default, min, max)
    ("lens_fstop", "F-Stop", 0.0, 0.0, 32.0),
    ("lens_focus_dist", "Focus Distance", 0.0, 0.0, 100.0),
    ("sensor_scale", "Sensor Scale", 1.0, 0.1, 4.0),
    ("chromatic_aberration", "Chromatic Aberration", 0.0, 0.0, 1.0),
    ("exposure", "Exposure", 0.0, -5.0, 5.0),
    ("dof_factor", "DOF Factor", 1.0, 0.0, 2.0),
    ("dof_remove", "DOF Remove", 0.0, 0.0, 1.0),
    ("global_scale", "Global Scale", 1.0, 0.01, 10.0),
    ("distortion_amount", "Distortion Amount", 0.0, -1.0, 1.0),
    ("distortion_exponent", "Distortion Exponent", 2.0, 0.0, 10.0),
    ("bokeh_swirliness", "Bokeh Swirliness", 0.0, 0.0, 1.0),
    ("tilt_shift_angle_x", "Tilt X", 0.0, -1.0, 1.0),
    ("tilt_shift_angle_y", "Tilt Y", 0.0, -1.0, 1.0),
    ("tilt_shift_offset_x", "Shift X", 0.0, -10.0, 10.0),
    ("tilt_shift_offset_y", "Shift Y", 0.0, -10.0, 10.0),
]

_COMMON_INT_PARMS = [
    # (name, label, default)
    ("aperture_ray_guiding", "Ray Guiding", 1),
    ("aperture_auto_exposure", "Auto Exposure", 1),
    ("flip", "Flip Image", 1),
]


def _find_installed_type(opname):
    """Find the installed VOP type name for a given opname.

    Prefers exact match over substring match to avoid e.g. 'lentilkarma'
    matching 'lentilkarma_core' from a stale HDA.
    """
    # First pass: exact match (type name equals opname)
    for cat_name, cat in hou.nodeTypeCategories().items():
        for type_name in cat.nodeTypes():
            if type_name == opname:
                return type_name
    # Second pass: substring match (for namespaced types like Vop/lentilkarma)
    for cat_name, cat in hou.nodeTypeCategories().items():
        for type_name in cat.nodeTypes():
            if opname in type_name and type_name.endswith(opname):
                return type_name
    # Third pass: any substring match
    for cat_name, cat in hou.nodeTypeCategories().items():
        for type_name in cat.nodeTypes():
            if opname in type_name:
                return type_name
    return None


def _create_lens_selector(lens_entries):
    """Create a lens selector network in /mat.

    Creates:
    - A matnet_lenses subnet containing all lens VOP nodes
    - A controller null with enum and common params
    - active_lens_path string for camera to reference via chs()
    - Channel references linking all lens nodes to the controller

    Args:
        lens_entries: list of (display_name, opname) tuples
    """
    mat_net = hou.node("/mat")
    if mat_net is None:
        _log_error("No /mat network found")
        return

    _log_info("Creating lens selector in /mat...")

    # --- Create or reuse matnet_lenses subnet ---
    lenses_net = mat_net.node("matnet_lenses")
    if lenses_net is None:
        lenses_net = mat_net.createNode("subnet", "matnet_lenses")
        lenses_net.setColor(hou.Color(0.3, 0.5, 0.8))
    _log_info(f"  Lenses subnet: {lenses_net.path()}")

    # --- Create VOP nodes inside matnet_lenses ---
    lens_nodes = []  # (display_name, node)
    for display_name, opname in lens_entries:
        # Check if node already exists in the subnet
        existing = lenses_net.node(opname)
        if existing:
            lens_nodes.append((display_name, existing))
            _log_info(f"  Reusing existing node: {existing.path()}")
        else:
            try:
                installed_type = _find_installed_type(opname)
                if installed_type:
                    node = lenses_net.createNode(installed_type, opname)
                    lens_nodes.append((display_name, node))
                    _log_info(f"  Created node: {node.path()}")
                else:
                    _log_warn(f"  Could not find installed type for: {opname}")
            except Exception as e:
                _log_error(f"  Failed to create node for {display_name}: {e}")

    if not lens_nodes:
        _log_error("No lens nodes created, skipping selector setup")
        return

    # --- Create or reuse controller null in /mat ---
    ctrl = mat_net.node("lentilkarma_controller")
    if ctrl is None:
        ctrl = mat_net.createNode("null", "lentilkarma_controller")
        ctrl.setColor(hou.Color(1.0, 0.8, 0.2))
    _log_info(f"  Controller: {ctrl.path()}")

    # --- Build spare parameters on the controller ---
    ptg = ctrl.parmTemplateGroup()

    # Remove existing lentilkarma parms for clean re-runs
    for name in ["lens_select", "active_lens_path", "sep1"]:
        existing_pt = ptg.find(name)
        if existing_pt:
            ptg.remove(name)
    for name, _, _, _, _ in _COMMON_FLOAT_PARMS:
        existing_pt = ptg.find(name)
        if existing_pt:
            ptg.remove(name)
    for name, _, _ in _COMMON_INT_PARMS:
        existing_pt = ptg.find(name)
        if existing_pt:
            ptg.remove(name)

    # Enum for lens selection — tokens are the node names (opnames)
    menu_tokens = [node.name() for _, node in lens_nodes]
    menu_labels = [name for name, _ in lens_nodes]

    menu_parm = hou.MenuParmTemplate(
        "lens_select", "Active Lens",
        menu_items=menu_tokens,
        menu_labels=menu_labels,
        default_value=0
    )
    ptg.append(menu_parm)

    # Active lens path (computed string: /mat/matnet_lenses/<selected_token>)
    path_parm = hou.StringParmTemplate(
        "active_lens_path", "Active Lens Path", 1,
        default_value=("",),
    )
    ptg.append(path_parm)

    # Separator
    ptg.append(hou.SeparatorParmTemplate("sep1"))

    # Common float parameters
    for name, label, default, pmin, pmax in _COMMON_FLOAT_PARMS:
        fp = hou.FloatParmTemplate(
            name, label, 1,
            default_value=(default,),
            min=pmin, max=pmax,
            min_is_strict=False, max_is_strict=False,
        )
        ptg.append(fp)

    # Common int parameters as toggles
    for name, label, default in _COMMON_INT_PARMS:
        ip = hou.ToggleParmTemplate(
            name, label,
            default_value=bool(default)
        )
        ptg.append(ip)

    ctrl.setParmTemplateGroup(ptg)

    # Set expression for active_lens_path:
    # Concatenates the subnet path with the selected enum token
    subnet_path = lenses_net.path()
    ctrl.parm("active_lens_path").setExpression(
        f'"{subnet_path}/" + chs("lens_select")',
        hou.exprLanguage.Hscript
    )

    # --- Link all lens nodes' common params to the controller ---
    ctrl_path = ctrl.path()
    for _, node in lens_nodes:
        for name, _, _, _, _ in _COMMON_FLOAT_PARMS:
            try:
                p = node.parm(name)
                if p is not None:
                    p.setExpression(
                        f'ch("{ctrl_path}/{name}")',
                        hou.exprLanguage.Hscript
                    )
            except Exception:
                pass
        for name, _, _ in _COMMON_INT_PARMS:
            try:
                p = node.parm(name)
                if p is not None:
                    p.setExpression(
                        f'ch("{ctrl_path}/{name}")',
                        hou.exprLanguage.Hscript
                    )
            except Exception:
                pass

    # Layout nodes inside the subnet
    lenses_net.layoutChildren()
    mat_net.layoutChildren()

    _log_info(f"Lens selector complete: {len(lens_nodes)} lenses")
    _log_info(f"  Controller: {ctrl.path()}")
    _log_info(f"  Lenses in: {lenses_net.path()}")
    _log_info(f"  Use on camera: chs(\"{ctrl.path()}/active_lens_path\")")


def _parse_focal_length(display_name, lens_data):
    """Extract focal length (mm) from lens data or filename.

    Tries the 'lens focal length' field in the raw data first, then
    falls back to parsing the leading number from the display name.

    Returns:
        float: Focal length in mm, or 50.0 as fallback
    """
    # Try explicit field in lens data file
    raw = lens_data.get("raw_data", {})
    fl_str = raw.get("lens focal length", "")
    if fl_str:
        try:
            return float(fl_str)
        except ValueError:
            pass

    # Fall back to parsing from filename (e.g., "50mm f2.0 ..." -> 50.0)
    m = re.match(r'^(\d+(?:\.\d+)?)', display_name)
    if m:
        return float(m.group(1))

    return 50.0  # Safe default


def _embed_lens_info_in_hda(hda_path, lenses_dir, selected):
    """Embed lens info parameters and warmup button into the HDA definition.

    Modifies the HDA's type definition directly so that focal_length,
    horizontal_aperture, and warmup controls are baked into the .hda file
    and persist when loaded in other sessions or on other machines.
    """
    # Collect per-lens focal lengths and sensor sizes
    focal_lengths = []
    sensor_sizes_mm = []
    for filename, display_name in selected:
        fp = os.path.join(lenses_dir, filename)
        try:
            lens = get_lens_data(fp)
            fl = _parse_focal_length(display_name, lens)
            ss = lens["default_sensor_size"] * 1000.0  # meters -> mm
        except Exception as e:
            _log_warn(f"Could not parse lens info for {display_name}: {e}")
            fl = 50.0
            ss = 36.0
        focal_lengths.append(fl)
        sensor_sizes_mm.append(ss)

    _log_info(f"Lens info: {len(focal_lengths)} focal lengths, "
              f"range {min(focal_lengths):.1f}-{max(focal_lengths):.1f}mm")

    # Build Python expression tuples
    fl_tuple = "(" + ", ".join(f"{v:.2f}" for v in focal_lengths) + ")"
    ss_tuple = "(" + ", ".join(f"{v:.2f}" for v in sensor_sizes_mm) + ")"

    fl_expr = f'{fl_tuple}[hou.pwd().evalParm("lens_select")]'
    ha_expr = (f'{ss_tuple}[hou.pwd().evalParm("lens_select")]'
               f' * hou.pwd().evalParm("sensor_scale")')

    # Find the HDA definition
    definitions = hou.hda.definitionsInFile(hda_path)
    if not definitions:
        _log_error(f"No HDA definitions found in {hda_path}")
        return
    defn = definitions[0]
    _log_info(f"Modifying HDA definition: {defn.nodeTypeName()}")

    # Guard: VOP assets using the header/wrapper pattern must NOT have
    # their parm template group modified — setParmTemplateGroup() corrupts
    # the VOP-internal TypePropertiesOptions and ExtraFileOptions sections,
    # producing "Missing := token" / "Unexpected end of file" errors and
    # wiping the parameter UI.  The vcc-generated parameters from pragmas
    # (labels, ranges, menu choices) are already correct.
    sections = defn.sections()
    if "CVexVflCode" in sections:
        src = sections["CVexVflCode"].contents()
        if '#include' in src and '.h"' in src:
            _log_info("Header/wrapper pattern detected — skipping parm "
                      "template modification to preserve VOP bindings")
            return

    ptg = defn.parmTemplateGroup()

    # Remove existing folder if present (recompile case)
    folder_entry = ptg.find("lens_info_folder")
    if folder_entry:
        ptg.remove(folder_entry)

    # Remove VEX-generated top-level focal_length/horizontal_aperture params
    # (vcc creates plain float params from the function signature; we replace
    # them with expression-driven versions in the Lens Info folder below)
    for pname in ("focal_length", "horizontal_aperture"):
        existing = ptg.find(pname)
        if existing:
            ptg.remove(existing)

    # Create parameter templates with baked-in default expressions
    fl_template = hou.FloatParmTemplate(
        "focal_length", "Focal Length (mm)", 1,
        default_value=(focal_lengths[0],),
        default_expression=(fl_expr,),
        default_expression_language=(hou.scriptLanguage.Python,),
    )
    ha_template = hou.FloatParmTemplate(
        "horizontal_aperture", "Horizontal Aperture (mm)", 1,
        default_value=(sensor_sizes_mm[0],),
        default_expression=(ha_expr,),
        default_expression_language=(hou.scriptLanguage.Python,),
    )

    # Warmup button — fully self-contained, no external imports needed.
    # Uses hou.session for state so it works even without the LentilKarma
    # Python package installed (the HDA is fully portable).
    warmup_script = r"""
import threading, time, hdefereval
node = kwargs['node']
parm = node.parm('lens_select')
delay = node.evalParm('warmup_delay')
viewer = None
for pt in hou.ui.curDesktop().paneTabs():
    if pt.type() == hou.paneTabType.SceneViewer:
        try:
            pt.currentHydraRenderer()
            viewer = pt
            break
        except Exception:
            pass
if not viewer:
    hou.ui.displayMessage('No Solaris viewport found.', title='LentilKarma')
elif getattr(hou.session, '_ll_running', False):
    hou.ui.displayMessage('Warmup already running. Cancel first.', title='LentilKarma')
else:
    try:
        num = len(parm.menuItems())
    except Exception:
        num = 84
    orig = parm.eval()
    rend = viewer.currentHydraRenderer()
    hou.session._ll_running = True
    hou.session._ll_cancel = False
    t0 = time.time()
    print('[LentilKarma] Warmup: %d lenses, %.0fs delay (~%.0fm est)' % (num, delay, num * delay / 60))
    hou.ui.setStatusMessage('LentilKarma warmup: 0/%d' % num)
    def _step(i):
        if getattr(hou.session, '_ll_cancel', False) or i >= num:
            def _restore():
                parm.set(orig)
                viewer.setHydraRenderer('GL')
                def _final():
                    viewer.setHydraRenderer(rend)
                    hou.session._ll_running = False
                    e = time.time() - t0
                    c = getattr(hou.session, '_ll_cancel', False)
                    if c:
                        msg = 'Cancelled (%d/%d, %.0fs)' % (i, num, e)
                    else:
                        msg = 'Complete! (%d lenses, %.0fs)' % (num, e)
                    hou.ui.setStatusMessage('LentilKarma warmup: ' + msg)
                    print('[LentilKarma] Warmup ' + msg)
                hdefereval.executeDeferred(_final)
            hdefereval.executeDeferred(_restore)
            return
        def _change():
            if getattr(hou.session, '_ll_cancel', False):
                _step(num)
                return
            parm.set(i)
            viewer.setHydraRenderer('GL')
            def _restart():
                if getattr(hou.session, '_ll_cancel', False):
                    _step(num)
                    return
                viewer.setHydraRenderer(rend)
                r = (num - i - 1) * delay
                hou.ui.setStatusMessage('LentilKarma warmup: %d/%d (~%.0fm remaining)' % (i + 1, num, r / 60))
                print('[LentilKarma] Warmup: lens %d/%d' % (i + 1, num))
                t = threading.Timer(delay, lambda: hdefereval.executeDeferred(lambda: _step(i + 1)))
                t.daemon = True
                t.start()
            hdefereval.executeDeferred(_restart)
        hdefereval.executeDeferred(_change)
    _step(0)
"""
    warmup_btn = hou.ButtonParmTemplate(
        "warmup_btn", "Warmup All Lenses",
        script_callback=warmup_script.strip(),
        script_callback_language=hou.scriptLanguage.Python,
    )

    cancel_script = r"""
if getattr(hou.session, '_ll_running', False):
    hou.session._ll_cancel = True
    hou.ui.setStatusMessage('LentilKarma warmup: cancelling...')
    print('[LentilKarma] Warmup cancellation requested')
else:
    hou.ui.setStatusMessage('No warmup in progress.')
"""
    cancel_btn = hou.ButtonParmTemplate(
        "warmup_cancel_btn", "Cancel Warmup",
        script_callback=cancel_script.strip(),
        script_callback_language=hou.scriptLanguage.Python,
    )
    delay_template = hou.FloatParmTemplate(
        "warmup_delay", "Warmup Delay (s)", 1,
        default_value=(5.0,),
        min=1.0, max=30.0,
        help="Seconds between lens switches during warmup. Increase if "
             "Karma doesn't finish compiling before the next switch.",
    )

    # Add all parameters in a folder
    folder = hou.FolderParmTemplate(
        "lens_info_folder", "Lens Info",
        parm_templates=[fl_template, ha_template,
                        warmup_btn, cancel_btn, delay_template],
    )
    ptg.append(folder)

    # Save back to the HDA definition (persists on disk)
    defn.setParmTemplateGroup(ptg)
    _log_info(f"Embedded lens info + warmup controls in HDA: {hda_path}")


def _add_warmup_parms_to_hda(hda_path, selected, lenses_dir):
    """Add warmup button parms to a vcc-compiled HDA's DialogScript.

    Edits the DS section directly (appending parm blocks before the
    closing brace) rather than using setParmTemplateGroup() which
    corrupts TypePropertiesOptions on VOP HDAs.

    The vcc-generated DS already has all shader params from VFL pragmas.
    We add warmup/cancel buttons and a delay slider for convenience.
    """
    type_name = _find_installed_type("lentilkarma")
    if not type_name:
        _log_warn("Cannot add warmup parms: lentilkarma type not found")
        return

    nt = hou.nodeType(hou.vopNodeTypeCategory(), type_name)
    defn = nt.definition()
    ds_section = defn.sections().get("DialogScript")
    if not ds_section:
        _log_warn("No DialogScript section found in HDA")
        return

    ds = ds_section.contents()

    warmup_cb = _escape_ds_parmtag(
        "import lentilkarma_houdini; "
        "lentilkarma_houdini._warmup_all_callback(kwargs)")
    cancel_cb = _escape_ds_parmtag(
        "import lentilkarma_houdini; "
        "lentilkarma_houdini._cancel_warmup_callback(kwargs)")

    extra = []
    extra.append('    parm {')
    extra.append('\tname\twarmup_delay')
    extra.append('\tlabel\t"Warmup Delay (s)"')
    extra.append('\ttype\tfloat')
    extra.append('\tdefault { 5.0 }')
    extra.append('\trange\t{ 1! 30 }')
    extra.append('\texport\tnone')
    extra.append('    }')
    extra.append('    parm {')
    extra.append('\tname\twarmup_btn')
    extra.append('\tlabel\t"Warmup All Lenses"')
    extra.append('\ttype\tbutton')
    extra.append('\tdefault { "0" }')
    extra.append(f'\tparmtag {{ "script_callback" "{warmup_cb}" }}')
    extra.append('\tparmtag { "script_callback_language" "python" }')
    extra.append('    }')
    extra.append('    parm {')
    extra.append('\tname\twarmup_cancel_btn')
    extra.append('\tlabel\t"Cancel Warmup"')
    extra.append('\ttype\tbutton')
    extra.append('\tdefault { "0" }')
    extra.append(f'\tparmtag {{ "script_callback" "{cancel_cb}" }}')
    extra.append('\tparmtag { "script_callback_language" "python" }')
    extra.append('    }')

    extra_text = '\n'.join(extra) + '\n'

    # Insert before the final closing }
    close_idx = ds.rfind("}")
    if close_idx > 0:
        ds = ds[:close_idx] + extra_text + ds[close_idx:]
        ds_section.setContents(ds)
        defn.save(hda_path)
        hou.hda.installFile(hda_path)
        _log_info("Added warmup parms to HDA DialogScript")
    else:
        _log_warn("Could not find closing } in DialogScript")


def _run_shader_diagnostics(vop_node):
    """Run diagnostics on the compiled shader and log everything.

    Checks HDA sections, shaderString(), camera parameters, etc.
    Returns a summary string for the result dialog.
    """
    lines = []

    def _diag(msg):
        _log_info(f"[DIAG] {msg}")
        lines.append(msg)

    _diag("=== Shader Diagnostics ===")

    # 1. Check outer HDA sections
    if vop_node:
        _diag(f"VOP node: {vop_node.path()}")
        _diag(f"VOP type: {vop_node.type().name()}")
        nt = vop_node.type()
        defn = nt.definition()
        if defn:
            _diag(f"HDA file: {defn.libraryFilePath()}")
            _diag(f"Extra: {defn.extraInfo()}")
            for sec_name in sorted(defn.sections().keys()):
                sec = defn.sections()[sec_name]
                content = sec.contents()
                _diag(f"  Section '{sec_name}': {len(content)} bytes")
                if sec_name in ("CVexVflCode", "VflCode"):
                    preview = content[:300].replace('\n', '|')
                    _diag(f"    Preview: {preview}")
                elif sec_name == "FunctionName":
                    _diag(f"    FunctionName: '{content}'")
                elif sec_name == "TypePropertiesOptions":
                    preview = content[:300].replace('\n', '\\n')
                    _diag(f"    Preview: {preview}")
                elif sec_name == "DialogScript":
                    # Show first few lines (name, script, label, etc.)
                    ds_lines = content.split('\n')[:15]
                    for dl in ds_lines:
                        _diag(f"    DS: {dl}")

            # 2. Try shaderString()
            try:
                ss = vop_node.shaderString()
                _diag(f"shaderString(): '{ss[:200]}'" if ss else
                      "shaderString(): EMPTY (this causes 'Missing shader name')")
            except Exception as e:
                _diag(f"shaderString() ERROR: {e}")

            # 2b. Try code() — returns VEX code from VOP network compilation
            try:
                code = vop_node.code()
                if code:
                    _diag(f"code(): {len(code)} bytes")
                    _diag(f"  code preview: {code[:300].replace(chr(10), '|')}")
                else:
                    _diag("code(): EMPTY (VOP network did not compile)")
            except Exception as e:
                _diag(f"code() ERROR: {e}")

            # 2c. Check VOP errors/warnings
            try:
                errs = vop_node.errors()
                if errs:
                    _diag(f"VOP errors: {errs}")
                warns = vop_node.warnings()
                if warns:
                    _diag(f"VOP warnings: {warns}")
            except Exception:
                pass

            # 2c. List children of the VOP node
            try:
                children = vop_node.children()
                _diag(f"VOP children ({len(children)}):")
                for child in children[:20]:
                    _diag(f"  {child.name()} ({child.type().name()})")
            except Exception:
                pass
        else:
            _diag("NO HDA definition found!")
    else:
        _diag("No VOP node!")

    # 3. Note: flat VOP approach — no separate inner VOP.
    #    The VOP node IS the shader (no cvexbuilder wrapper).
    _diag("Architecture: flat VOP (no cvexbuilder wrapper)")

    # 4. Check camera parameters
    stage_net = hou.node("/stage")
    if stage_net:
        for child in stage_net.children():
            if child.type().name() in ("camera", "cam"):
                _diag(f"Camera LOP: {child.path()}")
                for parm in child.parms():
                    name_lower = parm.name().lower()
                    if any(kw in name_lower for kw in
                           ['lens', 'shader', 'vop', 'lensshader']):
                        try:
                            val = parm.eval()
                        except Exception:
                            val = "<error>"
                        _diag(f"  {parm.name()} = {val}")
                break
    else:
        _diag("No /stage network")

    # 5. Check kma_physicallens for reference
    try:
        ref_nt = hou.nodeType(hou.vopNodeTypeCategory(), "kma_physicallens")
        if ref_nt and ref_nt.definition():
            ref_defn = ref_nt.definition()
            _diag(f"Reference kma_physicallens Extra: {ref_defn.extraInfo()}")
            ref_tpo = ref_defn.sections().get("TypePropertiesOptions")
            if ref_tpo:
                _diag(f"Reference kma_physicallens TPO ({len(ref_tpo.contents())} bytes): "
                      f"{ref_tpo.contents().replace(chr(10), '|')}")
            ref_ds = ref_defn.sections().get("DialogScript")
            if ref_ds:
                ds_lines = ref_ds.contents().split('\n')[:20]
                _diag(f"Reference kma_physicallens DS (first 20 lines):")
                for dl in ds_lines:
                    _diag(f"  ref DS: {dl}")
            ref_cvex = ref_defn.sections().get("CVexVflCode")
            if ref_cvex:
                _diag(f"Reference kma_physicallens CVexVflCode: "
                      f"{len(ref_cvex.contents())} bytes")
            else:
                _diag("Reference kma_physicallens has NO CVexVflCode section")
            # VflCode section — might be how shaderString() resolves code
            ref_vfl = ref_defn.sections().get("VflCode")
            if ref_vfl:
                vfl_content = ref_vfl.contents()
                _diag(f"Reference kma_physicallens VflCode: "
                      f"{len(vfl_content)} bytes")
                preview = vfl_content[:500].replace('\n', '|')
                _diag(f"  VflCode preview: {preview}")
            # FunctionName section
            ref_fn = ref_defn.sections().get("FunctionName")
            if ref_fn:
                _diag(f"Reference kma_physicallens FunctionName: "
                      f"'{ref_fn.contents()}'")
            # shaderString() — create temp node to test
            try:
                ref_mat = hou.node("/mat")
                if ref_mat:
                    ref_node = ref_mat.createNode("kma_physicallens",
                                                  "__diag_ref_lens")
                    ref_ss = ref_node.shaderString()
                    _diag(f"Reference kma_physicallens shaderString(): "
                          f"'{ref_ss[:300]}'" if ref_ss else
                          "Reference kma_physicallens shaderString(): EMPTY")
                    ref_code = ref_node.code()
                    if ref_code:
                        _diag(f"Reference kma_physicallens code(): "
                              f"{len(ref_code)} bytes")
                        _diag(f"  code preview: "
                              f"{ref_code[:300].replace(chr(10), '|')}")
                    ref_node.destroy()
            except Exception as e:
                _diag(f"Could not test kma_physicallens shaderString: {e}")
            # ExtraFileOptions section
            ref_efo = ref_defn.sections().get("ExtraFileOptions")
            if ref_efo:
                efo_content = ref_efo.contents()
                efo_repr = repr(efo_content[:600])
                _diag(f"Reference kma_physicallens ExtraFileOptions "
                      f"({len(efo_content)} bytes): {efo_repr}")
            # List all sections
            _diag(f"Reference kma_physicallens sections: "
                  f"{sorted(ref_defn.sections().keys())}")
        else:
            _diag("kma_physicallens not installed")
    except Exception as e:
        _diag(f"Could not check kma_physicallens: {e}")

    # 6. Check kma_physicallenscore for reference
    try:
        ref_nt2 = hou.nodeType(hou.vopNodeTypeCategory(), "kma_physicallenscore")
        if ref_nt2 and ref_nt2.definition():
            ref_defn2 = ref_nt2.definition()
            _diag(f"Reference kma_physicallenscore Extra: {ref_defn2.extraInfo()}")
            ref_tpo2 = ref_defn2.sections().get("TypePropertiesOptions")
            if ref_tpo2:
                _diag(f"Reference kma_physicallenscore TPO ({len(ref_tpo2.contents())} bytes): "
                      f"{ref_tpo2.contents().replace(chr(10), '|')}")
            ref_cvex2 = ref_defn2.sections().get("CVexVflCode")
            if ref_cvex2:
                _diag(f"Reference kma_physicallenscore CVexVflCode: "
                      f"{len(ref_cvex2.contents())} bytes")
                _diag(f"  Preview: {ref_cvex2.contents()[:300].replace(chr(10), '|')}")
            # List all sections
            _diag(f"Reference kma_physicallenscore sections: "
                  f"{sorted(ref_defn2.sections().keys())}")
        else:
            _diag("kma_physicallenscore not installed")
    except Exception as e:
        _diag(f"Could not check kma_physicallenscore: {e}")

    _diag("=== End Diagnostics ===")
    return '\n'.join(lines)


def _patch_flat_vop_for_karma(hda_path, selected, lenses_dir):
    """Patch a vcc-compiled flat VOP HDA for use as a Karma lens shader.

    This is much simpler than wrapping in a cvexbuilder. The flat VOP
    compiled by vcc already has CVexVflCode with the full shader source
    including 'export vector P', 'export vector I', 'export vector tint'.

    The VOP compiler's cvexbuilder wrapper failed because it IMPORTS
    vcc-compiled VOPs (via 'import' statement) instead of INLINING them,
    which loses the export declarations. By using the flat VOP directly,
    we bypass this issue entirely.

    Patches applied:
    - Extra: shadertype=cvex subtype=material (vcc sets vopmaterial)
    - DialogScript: fix shadertype/rendermask, add lens info parms
    - CVexVflCode → VflCode copy (shaderString() uses ?VflCode)
    - FunctionName section (shader entry point)
    - TPO from kma_physicallens (proper VEX shader context)

    Args:
        hda_path: Path to the vcc-compiled .hda file
        selected: List of (filename, display_name) tuples for lens info
        lenses_dir: Path to the lenses data directory

    Returns:
        hou.Node: The VOP node in /mat, or None on failure
    """
    _log_info(f"Patching flat VOP for Karma: {hda_path}")

    # Ensure the HDA is installed
    hou.hda.installFile(hda_path)
    defn_list = hou.hda.definitionsInFile(hda_path)
    if not defn_list:
        _log_error(f"No definitions found in {hda_path}")
        return None
    defn = defn_list[0]

    # 1. Copy CVexVflCode → VflCode.
    #    shaderString() references ?VflCode for shader resolution.
    #    CVexVflCode is the vcc-stored source; VflCode is what renderers use.
    cvex_section = defn.sections().get("CVexVflCode")
    if cvex_section:
        vfl_code = cvex_section.contents()
        defn.addSection("VflCode", vfl_code)
        _log_info(f"Copied CVexVflCode ({len(vfl_code)} bytes) -> VflCode")
    else:
        _log_error("No CVexVflCode section in flat VOP HDA!")
        return None

    # 2. Set FunctionName (shader entry point).
    defn.addSection("FunctionName", "lentilkarma")
    _log_info("Set FunctionName = 'lentilkarma'")

    # 3. Fix Extra: shadertype=cvex subtype=material.
    #    vcc generates shadertype=vopmaterial (Mantra legacy).
    #    Karma requires shadertype=cvex.
    old_extra = defn.extraInfo()
    defn.setExtraInfo("shadertype=cvex subtype=material ")
    _log_info(f"Fixed Extra: {old_extra!r} -> 'shadertype=cvex subtype=material'")

    # 4. Fix DialogScript metadata and add lens info parms.
    ds_section = defn.sections().get("DialogScript")
    if ds_section:
        ds = ds_section.contents()

        # Fix shadertype: vopmaterial → cvex
        ds = re.sub(r'(\s+shadertype\s+)\S+', r'\1cvex', ds)
        # Fix rendermask: VMantra → "VMantra OGL" (enables Karma)
        ds = re.sub(r'(\s+rendermask\s+)\S+', r'\1"VMantra OGL"', ds)

        # Remove vcc's focal_length/horizontal_aperture parms
        # (we add expression-driven versions below)
        for pname in ("focal_length", "horizontal_aperture"):
            ds = _remove_ds_parm_block(ds, pname)

        # Append extra parms (focal_length, horizontal_aperture, warmup)
        extra_parms = _build_lens_info_ds_blocks(selected, lenses_dir)
        close_idx = ds.rfind("}")
        if close_idx > 0:
            ds = ds[:close_idx] + extra_parms + ds[close_idx:]

        ds_section.setContents(ds)
        _log_info(f"Updated DialogScript: {len(ds)} bytes")

    # 5. Copy TPO from kma_physicallens (proper VEX shader context).
    _copy_vex_builder_tpo(defn)

    # 6. Save and reinstall.
    defn.save(hda_path)
    hou.hda.installFile(hda_path)
    _log_info("Patched HDA saved and reinstalled")

    # 7. Clean up old nodes in /mat, then create/find the VOP node.
    mat = hou.node("/mat")
    if mat:
        for old_name in ("__temp_lk_builder", "__temp_lk_outer",
                         "lentilkarma", "lentilkarma_vop"):
            old_node = mat.node(old_name)
            if old_node:
                _log_info(f"Removing old node: {old_node.path()}")
                old_node.destroy()

    vop_node = _find_or_create_vop_node("lentilkarma")
    if not vop_node:
        _log_error("Could not create VOP node in /mat")
        return None
    _log_info(f"VOP node created: {vop_node.path()}")

    # 8. Set focal_length / horizontal_aperture expressions.
    _set_lens_info_expressions(vop_node, selected, lenses_dir)

    return vop_node


def _batch_compile_lenses(lenses_dir, selected):
    """Compile all selected lenses into a flat VOP HDA for Karma.

    Flow:
    1. Generates lentilkarma.h (heavy code: LUTs, trace, impl function)
    2. Generates lentilkarma.vfl (thin wrapper calling lentilkarma_impl)
    3. Copies header + core.h to VEX include path for render-time resolution
    4. Compiles VFL → lentilkarma.hda (flat VOP with CVexVflCode)
    5. Patches the flat VOP HDA for Karma (shadertype, VflCode, FunctionName)
    6. Configures camera to use the shader via VOP path

    The flat VOP's CVexVflCode contains the full shader with
    'export vector P', 'export vector I', 'export vector tint'.
    No wrapper needed — the flat VOP IS the shader.
    """
    total = len(selected)
    _log_info(f"=== Combined compile (flat VOP): {total} lenses ===")

    # Clean up stale nodes and HDAs from previous runs
    mat = hou.node("/mat")
    if mat:
        for old_name in ("__temp_lk_outer", "__temp_lk_builder",
                         "lentilkarma", "lentilkarma_core",
                         "lentilkarma_vop"):
            old_node = mat.node(old_name)
            if old_node:
                _log_info(f"Removing stale node: {old_node.path()}")
                old_node.destroy()

    otls_dir = get_otls_dir()
    for stale_name in ("lentilkarma_core.hda", "lentilkarma_vop.hda"):
        stale_path = os.path.join(otls_dir, stale_name)
        if os.path.exists(stale_path):
            try:
                hou.hda.uninstallFile(stale_path)
                _log_info(f"Uninstalled stale HDA: {stale_path}")
            except Exception:
                pass

    # Build list of filepaths
    filepaths = [os.path.join(lenses_dir, filename) for filename, _ in selected]

    output_dir = get_output_dir()
    header_path = os.path.join(output_dir, "lentilkarma.h")
    vfl_path = os.path.join(output_dir, "lentilkarma.vfl")

    # Step 1: Generate header file (all heavy code)
    _log_info("Generating combined header...")
    t0 = time.time()
    try:
        from lentilkarma_codegen import generate_combined_header, generate_combined_vex_shader
        header_source = generate_combined_header(filepaths, header_path)
        dt = time.time() - t0
        header_lines = header_source.count('\n') + 1
        header_size = len(header_source.encode('utf-8'))
        _log_info(f"Combined header generated: {header_lines} lines, "
                  f"{header_size / 1024:.1f}KB in {dt:.2f}s")
    except Exception as e:
        _log_error(f"Combined header generation failed: {e}")
        _log_error(traceback.format_exc())
        hou.ui.displayMessage(
            f"Error generating combined header:\n{str(e)}\n\n"
            f"Check log: {_get_log_path()}",
            title="LentilKarma Error",
            severity=hou.severityType.Error
        )
        return

    # Step 2: Generate wrapper VFL (opname=lentilkarma — the shader itself)
    _log_info("Generating wrapper VFL...")
    t0 = time.time()
    try:
        vfl_source = generate_combined_vex_shader(filepaths, vfl_path)
        dt = time.time() - t0
        line_count = vfl_source.count('\n') + 1
        vfl_size = len(vfl_source.encode('utf-8'))
        _log_info(f"Wrapper VFL generated: {line_count} lines, "
                  f"{vfl_size / 1024:.1f}KB in {dt:.2f}s")
    except Exception as e:
        _log_error(f"VFL generation failed: {e}")
        _log_error(traceback.format_exc())
        hou.ui.displayMessage(
            f"Error generating shader:\n{str(e)}\n\n"
            f"Check log: {_get_log_path()}",
            title="LentilKarma Error",
            severity=hou.severityType.Error
        )
        return

    # Step 3: Copy header + core.h to VEX include path for render-time resolution.
    import shutil
    vex_inc_dir = _get_vex_include_dir()

    shutil.copy2(header_path, os.path.join(vex_inc_dir, "lentilkarma.h"))
    _log_info(f"Copied header to VEX include: {vex_inc_dir}/lentilkarma.h")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    core_h_src = os.path.normpath(os.path.join(script_dir, "..", "vex", "lentilkarma_core.h"))
    if os.path.exists(core_h_src):
        shutil.copy2(core_h_src, os.path.join(vex_inc_dir, "lentilkarma_core.h"))
        _log_info(f"Copied core.h to VEX include: {vex_inc_dir}/lentilkarma_core.h")
    else:
        _log_warn(f"lentilkarma_core.h not found at: {core_h_src}")

    # Step 4: Compile VFL → flat VOP HDA (lentilkarma.hda)
    _log_info("Compiling VOP HDA with vcc...")
    vex_path = None
    try:
        hda_path, vex_path = compile_lens_shader(
            vfl_path, extra_include_dirs=[vex_inc_dir],
            skip_source_fix=True)
    except Exception as e:
        _log_error(f"HDA compilation failed: {e}")
        _log_error(traceback.format_exc())
        hou.ui.displayMessage(
            f"Error compiling shader:\n{str(e)}\n\n"
            f"Check log: {_get_log_path()}",
            title="LentilKarma Error",
            severity=hou.severityType.Error
        )
        return

    # Step 5: Patch the flat VOP HDA for Karma.
    #   - Fix Extra/DialogScript metadata (vopmaterial → cvex)
    #   - Copy CVexVflCode → VflCode (for shaderString() resolution)
    #   - Set FunctionName, TPO, add lens info parms
    _log_info("Patching flat VOP for Karma...")
    vop_node = None
    try:
        vop_node = _patch_flat_vop_for_karma(
            hda_path, selected, lenses_dir)
    except Exception as e:
        _log_error(f"Flat VOP patching failed: {e}")
        _log_error(traceback.format_exc())
        hou.ui.displayMessage(
            f"Error patching shader:\n{str(e)}\n\n"
            f"Check log: {_get_log_path()}",
            title="LentilKarma Error",
            severity=hou.severityType.Error
        )
        # Fall back to the unpatched flat VOP
        try:
            vop_node = _find_or_create_vop_node("lentilkarma")
        except Exception:
            pass

    # Step 6: Configure camera to use the lens shader via VOP path.
    stage_net = hou.node("/stage")
    camera_configured = False
    if stage_net and vop_node:
        try:
            camera_configured = _try_configure_camera(
                vop_node.path(), stage_net)
        except Exception as e:
            _log_warn(f"Camera auto-config failed: {e}")
            _log_warn(traceback.format_exc())

    _log_info(f"=== Combined compile complete: {total} lenses ===")

    # Run diagnostics and collect results
    diag = _run_shader_diagnostics(vop_node)

    # Show result
    msg = f"Combined lens shader compiled!\n\n"
    msg += f"Lenses: {total}\n"
    if vop_node:
        msg += f"VOP node: {vop_node.path()}\n"

    if camera_configured:
        msg += f"\nCamera configured (Lens Shader VOP).\n"
    else:
        msg += f"\nCamera setup:\n"
        msg += f"  Camera LOP > Karma tab > Use Lens Shader = ON\n"
        if vop_node:
            msg += f"  Camera LOP > Karma tab > Lens Shader VOP = "
            msg += f"{vop_node.path()}\n"

    if vop_node:
        msg += f"\nSelect lens from the 'Lens' dropdown on the VOP node.\n"
        msg += f"\nCamera reference parameters:\n"
        msg += f"  Focal Length: ch(\"{vop_node.path()}/focal_length\")\n"
        msg += f"  H Aperture:  ch(\"{vop_node.path()}/horizontal_aperture\")\n"

    if diag:
        msg += f"\n--- Diagnostics ---\n{diag}\n"

    msg += f"\nLog: {_get_log_path()}"

    hou.ui.displayMessage(msg, title="LentilKarma Combined Compile")


def _find_lentilkarma_vop(vop_path=None):
    """Find the lentilkarma VOP node in /mat.

    Args:
        vop_path: Explicit path (skips search if provided and valid)

    Returns:
        hou.Node or None
    """
    if vop_path:
        node = hou.node(vop_path)
        if node:
            return node

    # Check /mat
    mat = hou.node("/mat")
    if mat:
        for child in mat.allSubChildren():
            if "lentilkarma" in child.type().name().lower():
                return child

    return None


def switch_lens(index, vop_path=None):
    """Switch the active lens with a safe Karma restart workaround.

    Karma has a bug where changing a compiled VOP lens shader parameter
    while rendering causes it to hang in init. This works around it by
    switching the viewport renderer to GL, changing the parameter, then
    switching back to Karma — ensuring Karma fully stops before the
    parameter change.

    Args:
        index: Lens index (int) to switch to
        vop_path: Path to the VOP node (auto-discovered if None)

    Usage from Python shell:
        import lentilkarma_houdini
        lentilkarma_houdini.switch_lens(5)
    """
    vop = _find_lentilkarma_vop(vop_path)
    if not vop:
        _log_error(f"VOP node not found. Checked /stage and /mat.")
        return

    old_val = vop.parm("lens_select").eval()
    if old_val == index:
        return

    _log_info(f"Switching lens: {old_val} -> {index}")

    viewer = _get_solaris_viewer()

    if viewer:
        # Get current renderer name so we can switch back to it
        current_renderer = viewer.currentHydraRenderer()
        _log_info(f"Current renderer: {current_renderer}")

        # Switch to GL to fully stop Karma (releases all shader locks)
        _log_info("Switching to GL...")
        viewer.setHydraRenderer("GL")

        # Change the parameter while Karma is completely stopped
        vop.parm("lens_select").set(index)

        # Switch back to Karma — starts fresh with the new parameter
        _log_info(f"Switching back to {current_renderer}...")
        viewer.setHydraRenderer(current_renderer)
    else:
        _log_warn("No Solaris viewport found — setting parameter directly")
        vop.parm("lens_select").set(index)


# ---------------------------------------------------------------------------
# Auto-safe parameter change callback
# ---------------------------------------------------------------------------

_karma_restart_pending = False
_karma_renderer_name = None
_callback_installed_nodes = set()


def _safe_parm_change_callback(node, event_type, **kwargs):
    """Intercept parameter changes on the VOP node and cycle Karma.

    When a user changes ANY parameter on the compiled lens shader VOP,
    this immediately switches the viewport to GL (stopping Karma), then
    schedules a deferred restart. Multiple rapid parameter changes are
    batched — Karma only restarts once after all changes settle.
    """
    global _karma_restart_pending, _karma_renderer_name

    if event_type != hou.nodeEventType.ParmTupleChanged:
        return

    viewer = _get_solaris_viewer()
    if not viewer:
        return

    current = viewer.currentHydraRenderer()

    # If Karma is running, switch to GL immediately to prevent hang
    if not _karma_restart_pending and current != "GL":
        _karma_renderer_name = current
        _karma_restart_pending = True
        viewer.setHydraRenderer("GL")
        _log_info(f"Auto-safe: switched to GL (was {current})")

        # Schedule deferred Karma restart
        import hdefereval
        hdefereval.executeDeferred(_deferred_karma_restart)


def _deferred_karma_restart():
    """Restart Karma after parameter changes have settled."""
    global _karma_restart_pending, _karma_renderer_name

    if not _karma_restart_pending:
        return

    viewer = _get_solaris_viewer()
    if viewer and _karma_renderer_name:
        _log_info(f"Auto-safe: restarting {_karma_renderer_name}")
        viewer.setHydraRenderer(_karma_renderer_name)

    _karma_restart_pending = False
    _karma_renderer_name = None


def install_safe_parm_callback(vop_node):
    """Install the auto-safe parameter change callback on a VOP node.

    After installation, changing ANY parameter on the VOP node will
    automatically cycle the viewport renderer (GL → Karma) to prevent
    the Karma hang bug with compiled VOP lens shaders.

    Args:
        vop_node: hou.Node — the compiled lens shader VOP node
    """
    global _callback_installed_nodes

    node_path = vop_node.path()
    if node_path in _callback_installed_nodes:
        _log_info(f"Safe callback already installed on {node_path}")
        return

    vop_node.addEventCallback(
        (hou.nodeEventType.ParmTupleChanged,),
        _safe_parm_change_callback
    )
    _callback_installed_nodes.add(node_path)
    _log_info(f"Installed safe parameter callback on {node_path}")


def _get_solaris_viewer():
    """Find the active Solaris SceneViewer pane tab.

    Returns:
        hou.SceneViewer or None
    """
    desktop = hou.ui.curDesktop()
    for pane_tab in desktop.paneTabs():
        if pane_tab.type() == hou.paneTabType.SceneViewer:
            try:
                # Check if it's a Solaris viewer by testing for hydra renderer
                pane_tab.currentHydraRenderer()
                return pane_tab
            except Exception:
                continue
    return None


def show_lens_browser():
    """Show a dialog to browse and select a lens from the library."""
    _log_info("Opening lens browser...")

    lenses_dir = get_lenses_dir()
    if not lenses_dir:
        hou.ui.displayMessage(
            "LentilKarma lens data directory not found.\n"
            "Set the LENTILKARMA environment variable to the LentilKarma root directory.",
            title="LentilKarma"
        )
        return

    lenses = list_available_lenses(lenses_dir)
    _log_info(f"Found {len(lenses)} lens files in {lenses_dir}")

    if not lenses:
        hou.ui.displayMessage(
            f"No lens files found in:\n{lenses_dir}",
            title="LentilKarma"
        )
        return

    # Build selection list (multi-select enabled)
    names = [name for _, name in lenses]
    choice = hou.ui.selectFromList(
        names,
        title="LentilKarma - Select Lens",
        message="Choose one or more lenses to generate CVEX shaders:",
        num_visible_rows=min(len(names), 20),
        exclusive=False
    )

    if not choice:
        _log_info("User cancelled lens selection")
        return

    selected = [(lenses[i][0], lenses[i][1]) for i in choice]

    if len(selected) == 1:
        # Single lens — generate, compile, create node, show result
        filename, display_name = selected[0]
        filepath = os.path.join(lenses_dir, filename)
        _log_info(f"User selected: {display_name} ({filepath})")
        try:
            result = apply_lens_to_camera(filepath)

            log_path = _get_log_path()
            vop_msg = ""
            if result.get('vop_node'):
                if result.get('stage_setup'):
                    vop_msg = (
                        f"VOP node: {result['vop_node']}\n\n"
                        f"Camera auto-configured to use lens shader.\n"
                    )
                else:
                    vop_msg = (
                        f"VOP node: {result['vop_node']}\n\n"
                        f"To complete setup:\n"
                        f"1. Select your Camera LOP\n"
                        f"2. In Karma tab, enable 'Use Lens Shader'\n"
                        f"3. Set 'Lens Shader VOP' to: {result['vop_node']}\n"
                        f"\nTip: lentilkarma_houdini.discover_camera_parms()\n"
                    )
            else:
                vop_msg = (
                    f"HDA installed: {result['hda_path']}\n\n"
                    f"Run: lentilkarma_houdini.setup_lens_in_stage()\n"
                )
            hou.ui.displayMessage(
                f"Lens shader generated successfully!\n\n"
                f"Lens: {result['lens_name']}\n"
                f"Elements: {result['elements']}\n"
                f"F-number: f/{result['f_number']}\n\n"
                f"{vop_msg}\n"
                f"Log: {log_path}",
                title="LentilKarma"
            )
        except Exception as e:
            _log_error(f"Shader generation failed: {e}")
            _log_error(traceback.format_exc())
            hou.ui.displayMessage(
                f"Error generating lens shader:\n{str(e)}\n\n"
                f"Check log: {_get_log_path()}",
                title="LentilKarma Error",
                severity=hou.severityType.Error
            )
    else:
        # Batch mode — compile into single combined shader with lens dropdown
        _batch_compile_lenses(lenses_dir, selected)


def create_lentilkarma_lop_node(parent_node=None):
    """Create a LentilKarma camera LOP and configure it for lens shaders.

    Creates a Camera LOP and attempts to set its Lens Shader VOP
    parameter to the lentilkarma VOP in /mat (if compiled).

    Args:
        parent_node: LOP network node (default: /stage)

    Returns:
        dict: Created node references
    """
    _log_info("Creating LentilKarma LOP setup...")

    if parent_node is None:
        parent_node = hou.node("/stage")
        if parent_node is None:
            _log_error("No /stage node found")
            raise RuntimeError("No /stage node found. Create a LOP network first.")

    # Create camera LOP
    cam = parent_node.node("lentilkarma_camera")
    if cam is None:
        cam = parent_node.createNode("camera", "lentilkarma_camera")
        cam.setColor(hou.Color(0.3, 0.5, 0.8))
    _log_info(f"Camera: {cam.path()}")

    # Try to configure camera with existing VOP
    vop = _find_lentilkarma_vop()
    if vop:
        _try_configure_camera(vop.path(), parent_node)

    parent_node.layoutChildren()
    _log_info("LOP setup complete")

    return {
        'camera': cam,
        'vop': vop,
    }


def get_log_path():
    """Return the log file path (for user reference)."""
    return _get_log_path()


# ---------------------------------------------------------------------------
# Shader warmup — pre-compile all lens_select variations
# ---------------------------------------------------------------------------

_warmup_cancel = False
_warmup_running = False


def warmup_shader(vop_path=None, num_lenses=None, delay=5.0):
    """Pre-compile all lens variations to eliminate first-change lag.

    Karma recompiles the VEX shader the first time each lens_select value
    is used (~1 minute). This function cycles through all values upfront
    so that interactive use is lag-free afterward.

    The warmup runs asynchronously — Houdini remains responsive during the
    process. Progress is printed to the Python shell and status bar.

    Args:
        vop_path: Path to the VOP node (auto-discovered if None)
        num_lenses: Number of lenses (auto-detected from lens_select menu
                    if None)
        delay: Seconds to wait between lens changes (must be long enough
               for Karma to finish compiling each variant; default 5s).
               If you see renders not completing, increase this value.

    Usage:
        import lentilkarma_houdini
        lentilkarma_houdini.warmup_shader()

    To cancel a running warmup:
        lentilkarma_houdini.cancel_warmup()
    """
    global _warmup_cancel, _warmup_running

    if _warmup_running:
        _log_warn("Warmup already in progress. Use cancel_warmup() first.")
        return

    vop = _find_lentilkarma_vop(vop_path)
    if not vop:
        _log_error("VOP node not found. Checked /stage and /mat.")
        return

    parm = vop.parm("lens_select")
    if not parm:
        _log_error(f"No 'lens_select' parameter on {vop.path()}")
        return

    # Auto-detect number of lenses from the menu items
    if num_lenses is None:
        try:
            menu_items = parm.menuItems()
            num_lenses = len(menu_items)
        except Exception:
            num_lenses = 84
    _log_info(f"Detected {num_lenses} lens variations")

    viewer = _get_solaris_viewer()
    if not viewer:
        _log_error("No Solaris viewport found — cannot warmup")
        return

    # Remember original state
    original_lens = parm.eval()
    original_renderer = viewer.currentHydraRenderer()

    # Temporarily disable the safe callback so it doesn't interfere
    global _callback_installed_nodes
    saved_callbacks = _callback_installed_nodes.copy()
    _callback_installed_nodes.clear()

    _warmup_cancel = False
    _warmup_running = True

    import hdefereval
    import threading

    est_minutes = (num_lenses * delay) / 60.0
    _log_info(f"Starting warmup: {num_lenses} lenses, {delay}s delay")
    _log_info(f"Estimated time: {est_minutes:.1f} minutes")
    _log_info("Use lentilkarma_houdini.cancel_warmup() to abort")
    hou.ui.setStatusMessage(
        f"LentilKarma warmup: 0/{num_lenses} "
        f"(~{est_minutes:.0f} min remaining)")

    t_start = time.time()

    def _step(idx):
        global _warmup_cancel, _warmup_running

        # Check for cancellation
        if _warmup_cancel:
            _finish(idx, cancelled=True)
            return

        # Check all done
        if idx >= num_lenses:
            _finish(idx, cancelled=False)
            return

        # Set lens_select and cycle Karma
        def _do_change():
            global _warmup_cancel, _warmup_running
            if _warmup_cancel:
                _finish(idx, cancelled=True)
                return

            parm.set(idx)
            viewer.setHydraRenderer("GL")

            def _restart():
                global _warmup_cancel
                if _warmup_cancel:
                    _finish(idx, cancelled=True)
                    return

                viewer.setHydraRenderer(original_renderer)
                elapsed = time.time() - t_start
                remaining = (num_lenses - idx - 1) * delay
                _log_info(
                    f"Warmup: lens {idx + 1}/{num_lenses} "
                    f"({elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining)")
                hou.ui.setStatusMessage(
                    f"LentilKarma warmup: {idx + 1}/{num_lenses} "
                    f"(~{remaining / 60:.0f} min remaining)")

                # Schedule next step after delay
                timer = threading.Timer(
                    delay,
                    lambda: hdefereval.executeDeferred(lambda: _step(idx + 1)))
                timer.daemon = True
                timer.start()

            hdefereval.executeDeferred(_restart)

        hdefereval.executeDeferred(_do_change)

    def _finish(last_idx, cancelled):
        global _warmup_running, _callback_installed_nodes

        # Restore original lens
        def _do_restore():
            global _warmup_running

            parm.set(original_lens)
            viewer.setHydraRenderer("GL")

            def _final_restart():
                global _warmup_running
                viewer.setHydraRenderer(original_renderer)
                _warmup_running = False

                # Re-enable safe callbacks
                _callback_installed_nodes.update(saved_callbacks)

                elapsed = time.time() - t_start
                if cancelled:
                    _log_info(
                        f"Warmup cancelled after {last_idx}/{num_lenses} "
                        f"lenses ({elapsed:.0f}s)")
                    hou.ui.setStatusMessage(
                        f"LentilKarma warmup cancelled "
                        f"({last_idx}/{num_lenses} lenses)")
                else:
                    _log_info(
                        f"Warmup complete: {num_lenses} lenses "
                        f"in {elapsed:.0f}s")
                    hou.ui.setStatusMessage(
                        f"LentilKarma warmup complete! "
                        f"({num_lenses} lenses, {elapsed:.0f}s)")

            hdefereval.executeDeferred(_final_restart)

        hdefereval.executeDeferred(_do_restore)

    # Kick off the first step
    _step(0)


def cancel_warmup():
    """Cancel a running shader warmup."""
    global _warmup_cancel
    if not _warmup_running:
        _log_info("No warmup in progress")
        return
    _warmup_cancel = True
    _log_info("Warmup cancellation requested...")
