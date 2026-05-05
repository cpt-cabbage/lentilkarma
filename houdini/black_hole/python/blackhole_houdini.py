"""
Black Hole CVEX Lens Shader — Houdini Integration

One-button build pipeline: generate VFL -> compile HDA -> patch for Karma ->
install -> create VOP in /mat -> configure camera.

After vcc compilation, the HDA needs patching for Karma (same as lentilkarma):
  1. CVexVflCode -> VflCode copy (Karma reads ?VflCode, not ?CVexVflCode)
  2. FunctionName section (shader entry point for shaderString())
  3. Extra: shadertype=cvex subtype=material (vcc generates vopmaterial)
  4. DialogScript: fix shadertype/rendermask
  5. TypePropertiesOptions for VEX context metadata

Usage from Houdini Python shell:
    import blackhole_houdini
    blackhole_houdini.build_blackhole_shader()
"""

import os
import re
import time
import traceback
import subprocess
import hou

from blackhole_codegen import generate_vfl_shader


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_SOURCE = "BlackHole"
_log_file = None


def _get_log_path():
    """Return the path to the BlackHole log file."""
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR", "")
    if pref_dir:
        log_dir = os.path.join(pref_dir, "logs")
    else:
        log_dir = os.path.join(os.path.expanduser("~"), "houdini20.5", "logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "blackhole.log")


def _open_log():
    """Open the log file for appending."""
    global _log_file
    if _log_file is None:
        path = _get_log_path()
        _log_file = open(path, "a", encoding="utf-8")
        _log_file.write(f"\n{'='*72}\n")
        _log_file.write(f"BlackHole session started: "
                        f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        _log_file.write(f"{'='*72}\n")
        _log_file.flush()
    return _log_file


def _log(message, severity=None):
    """Log to both hou.logging and disk log file."""
    if severity is None:
        severity = hou.severityType.Message

    tag = "INFO"
    if severity == hou.severityType.Warning:
        tag = "WARN"
    elif severity == hou.severityType.Error:
        tag = "ERROR"

    timestamp = time.strftime("%H:%M:%S")
    formatted = f"[{timestamp}] [{tag}] {message}"

    try:
        f = _open_log()
        f.write(formatted + "\n")
        f.flush()
    except Exception:
        pass

    try:
        entry = hou.logging.LogEntry(
            message=message,
            severity=severity,
        )
        hou.logging.log(entry, source_name=_LOG_SOURCE)
    except Exception:
        pass

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

def get_output_dir():
    """Return the directory for generated VEX shaders."""
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR", "")
    if pref_dir:
        out = os.path.join(pref_dir, "vex", "blackhole")
    else:
        out = os.path.join(os.path.expanduser("~"),
                           "houdini20.5", "vex", "blackhole")
    os.makedirs(out, exist_ok=True)
    return out


def get_otls_dir():
    """Return the otls directory for HDA installation."""
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR", "")
    if pref_dir:
        out = os.path.join(pref_dir, "otls")
    else:
        out = os.path.join(os.path.expanduser("~"), "houdini20.5", "otls")
    os.makedirs(out, exist_ok=True)
    return out


# ---------------------------------------------------------------------------
# VFL Generation
# ---------------------------------------------------------------------------

def _generate_vfl():
    """Generate the black hole lens shader VFL source.

    Returns:
        tuple: (vfl_path, vfl_source)
    """
    output_dir = get_output_dir()
    vfl_path = os.path.join(output_dir, "blackhole_lens.vfl")

    _log_info(f"Generating VFL: {vfl_path}")
    t0 = time.time()
    source = generate_vfl_shader(vfl_path)
    dt = time.time() - t0
    line_count = source.count("\n") + 1
    _log_info(f"VFL generated: {line_count} lines in {dt:.2f}s")

    return vfl_path, source


# ---------------------------------------------------------------------------
# VFL Compilation
# ---------------------------------------------------------------------------

def _compile_vfl(vfl_path):
    """Compile VFL to HDA using vcc.

    Args:
        vfl_path: Path to the .vfl source file

    Returns:
        str: Path to the compiled .hda file
    """
    hda_path = os.path.join(get_otls_dir(), "blackhole_lens.hda")
    _log_info(f"Compiling VFL -> HDA: {vfl_path}")
    _log_info(f"HDA output: {hda_path}")

    # Uninstall any previous version first
    if os.path.exists(hda_path):
        try:
            hou.hda.uninstallFile(hda_path)
            _log_info("Uninstalled previous HDA")
        except Exception:
            pass

    # Build vcc command
    cmd = ['vcc', '-O', 'vop', '-l', hda_path, vfl_path]
    _log_info(f"Running: {' '.join(cmd)}")

    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    dt = time.time() - t0

    if result.stdout:
        _log_info(f"vcc stdout: {result.stdout}")
    if result.stderr:
        if result.returncode == 0:
            _log_warn(f"vcc warnings:\n{result.stderr}")
        else:
            _log_error(f"vcc stderr:\n{result.stderr}")

    if result.returncode != 0:
        _log_error(f"vcc failed with exit code {result.returncode} "
                   f"after {dt:.2f}s")
        raise RuntimeError(
            f"vcc compilation failed (exit code {result.returncode}):\n"
            f"{result.stderr}")

    if not os.path.exists(hda_path):
        _log_error(f"vcc produced no HDA file: {hda_path}")
        raise RuntimeError(f"vcc produced no HDA file: {hda_path}")

    hda_size = os.path.getsize(hda_path)
    _log_info(f"HDA compiled: {hda_path} ({hda_size} bytes, {dt:.2f}s)")

    return hda_path


# ---------------------------------------------------------------------------
# HDA Patching for Karma
# ---------------------------------------------------------------------------

def _patch_for_karma(hda_path):
    """Patch the vcc-compiled flat VOP HDA for Karma CVEX lens shader use.

    vcc creates a correctly-named operator but with wrong metadata.
    We replace the DialogScript entirely (not regex-patched) and fix
    Extra, VflCode, FunctionName, and TPO.
    """
    _log_info(f"Patching HDA for Karma: {hda_path}")

    hou.hda.installFile(hda_path)
    defn_list = hou.hda.definitionsInFile(hda_path)
    if not defn_list:
        _log_error(f"No definitions found in {hda_path}")
        raise RuntimeError(f"No HDA definitions found in {hda_path}")
    defn = defn_list[0]

    # Log raw vcc state
    _log_info(f"Raw vcc Extra: {defn.extraInfo()!r}")
    _log_info(f"Raw vcc Sections: {sorted(defn.sections().keys())}")
    raw_ds = defn.sections().get("DialogScript")
    if raw_ds:
        _log_info(f"Raw vcc DialogScript ({len(raw_ds.contents())} bytes):")
        for i, line in enumerate(raw_ds.contents().split('\n')[:20]):
            _log_info(f"  {i+1:3d}: {line}")

    # 1. Copy CVexVflCode -> VflCode.
    cvex_section = defn.sections().get("CVexVflCode")
    if not cvex_section:
        raise RuntimeError("No CVexVflCode section in compiled HDA")
    vfl_code = cvex_section.contents()
    defn.addSection("VflCode", vfl_code)
    _log_info(f"Copied CVexVflCode -> VflCode ({len(vfl_code)} bytes)")

    # 2. Set FunctionName.
    defn.addSection("FunctionName", "blackhole_lens")
    _log_info("Set FunctionName = 'blackhole_lens'")

    # 3. Set Extra info.
    defn.setExtraInfo("shadertype=cvex subtype=material ")
    _log_info("Set Extra = 'shadertype=cvex subtype=material'")

    # 4. REPLACE DialogScript entirely (not regex-patched).
    #    This guarantees rendermask, shadertype, and all metadata are correct.
    ds = _build_dialog_script_for_blackhole()
    defn.addSection("DialogScript", ds)
    _log_info(f"Replaced DialogScript ({len(ds)} bytes)")

    # 5. Copy TPO from kma_physicallens.
    _copy_or_create_tpo(defn)

    # 6. Save and reinstall.
    defn.save(hda_path)
    hou.hda.installFile(hda_path)
    _log_info("Patched HDA saved and reinstalled")

    # 7. Verify by re-reading from disk.
    _verify_hda(hda_path)


def _copy_or_create_tpo(defn):
    """Copy TypePropertiesOptions from kma_physicallens.

    Same approach as lentilkarma's _copy_vex_builder_tpo().
    Copies TPO from kma_physicallens to make our HDA a proper VEX shader.

    After copying, fixes GzipContents := 0 to prevent gzip corruption of
    short sections like FunctionName on save.
    """
    # Primary: copy from kma_physicallens (same as lentilkarma)
    try:
        ref_nt = hou.nodeType(hou.vopNodeTypeCategory(), "kma_physicallens")
        if ref_nt and ref_nt.definition():
            ref_tpo = ref_nt.definition().sections().get(
                "TypePropertiesOptions")
            if ref_tpo:
                tpo = ref_tpo.contents()
                _log_info(f"kma_physicallens TPO:\n{tpo}")
                # Fix GzipContents (kma_physicallens may have it set to 1)
                tpo = re.sub(
                    r'GzipContents\s*:=\s*\d+',
                    'GzipContents := 0', tpo)
                our_tpo = defn.sections().get("TypePropertiesOptions")
                if our_tpo:
                    our_tpo.setContents(tpo)
                else:
                    defn.addSection("TypePropertiesOptions", tpo)
                _log_info("Copied TPO from kma_physicallens "
                          "(GzipContents fixed to 0)")
                return True
    except Exception as e:
        _log_warn(f"Could not copy TPO from kma_physicallens: {e}")

    # Fallback: minimal hardcoded TPO
    _log_warn("kma_physicallens not found — using fallback TPO")
    tpo_content = (
        "CheckExternal := 1;\n"
        "ContentsCompressionType := 0;\n"
        "ForbidOutsideParms := 1;\n"
        "GzipContents := 0;\n"
        "LockContents := 1;\n"
        "MakeDefault := 1;\n"
        "ParmsFromVfl := 0;\n"
        "PrefixDroppedParmLabel := 0;\n"
        "PrefixDroppedParmName := 0;\n"
        "SaveCachedCode := 0;\n"
        "SaveIcon := 1;\n"
        "SaveSpareParms := 0;\n"
        "UnlockOnCreate := 0;\n"
        "UseDSParms := 1;\n"
    )
    defn.addSection("TypePropertiesOptions", tpo_content)
    _log_info("Set fallback TPO")
    return False


def _test_shader_string(vop_node):
    """Test shaderString() on the VOP node and compare with lentilkarma."""
    # Test our shader
    try:
        ss = vop_node.shaderString()
        if ss:
            _log_info(f"shaderString() OK: {len(ss)} chars")
            _log_info(f"  Preview: {ss[:200]}")
        else:
            _log_error("shaderString() returned EMPTY!")
    except Exception as e:
        _log_error(f"shaderString() raised exception: {e}")
        ss = None

    # Test code()
    try:
        code = vop_node.code()
        if code:
            _log_info(f"code() OK: {len(code)} chars")
            _log_info(f"  Full code(): {code}")
        else:
            _log_warn("code() returned EMPTY")
    except Exception as e:
        _log_warn(f"code() raised exception: {e}")

    # Log full DialogScript P/I parm blocks for debugging
    our_defn = vop_node.type().definition()
    if our_defn:
        ds_sec = our_defn.sections().get("DialogScript")
        if ds_sec:
            ds_text = ds_sec.contents()
            # Find and log P and I parm blocks
            for parm_name in ("P", "I", "tint"):
                idx = ds_text.find(f'name "{parm_name}"')
                if idx >= 0:
                    # Find the parm block start (search backward for 'parm')
                    block_start = ds_text.rfind('parm', 0, idx)
                    # Find the parm block end (matching closing brace)
                    brace_count = 0
                    block_end = idx
                    for ci in range(block_start, len(ds_text)):
                        if ds_text[ci] == '{':
                            brace_count += 1
                        elif ds_text[ci] == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                block_end = ci + 1
                                break
                    parm_block = ds_text[block_start:block_end]
                    _log_info(f"  DS parm '{parm_name}': {parm_block}")

    # Compare with working lentilkarma shader (if installed)
    _log_info("--- Comparing with lentilkarma reference ---")
    try:
        ref_nt = hou.nodeType(hou.vopNodeTypeCategory(), "lentilkarma")
        if ref_nt and ref_nt.definition():
            ref_defn = ref_nt.definition()
            ref_extra = ref_defn.extraInfo()
            ref_sections = sorted(ref_defn.sections().keys())
            _log_info(f"  lentilkarma Extra: {ref_extra!r}")
            _log_info(f"  lentilkarma Sections: {ref_sections}")

            # Check for FunctionName
            ref_fn = ref_defn.sections().get("FunctionName")
            if ref_fn:
                _log_info(f"  lentilkarma FunctionName: '{ref_fn.contents()}'")

            # Check VflCode presence
            ref_vfl = ref_defn.sections().get("VflCode")
            if ref_vfl:
                _log_info(f"  lentilkarma VflCode: {len(ref_vfl.contents())} bytes")

            # Check TPO
            ref_tpo = ref_defn.sections().get("TypePropertiesOptions")
            if ref_tpo:
                _log_info(f"  lentilkarma TPO: {len(ref_tpo.contents())} bytes")
                _log_info(f"  lentilkarma TPO preview: "
                          f"{ref_tpo.contents()[:300]}")

            # Check DialogScript key fields
            ref_ds = ref_defn.sections().get("DialogScript")
            if ref_ds:
                ds_text = ref_ds.contents()
                for line in ds_text.split('\n')[:20]:
                    stripped = line.strip()
                    if any(kw in stripped.lower() for kw in
                           ('shadertype', 'rendermask', 'name ', 'script ',
                            'context')):
                        _log_info(f"  lentilkarma DS: {stripped}")

            # Try to create a temp node and test shaderString()
            mat = hou.node("/mat")
            if mat:
                tmp = None
                try:
                    tmp = mat.createNode("lentilkarma", "__test_lk_ref")
                    ref_ss = tmp.shaderString()
                    if ref_ss:
                        _log_info(f"  lentilkarma shaderString(): "
                                  f"{len(ref_ss)} chars")
                        _log_info(f"  lentilkarma SS preview: "
                                  f"{ref_ss[:200]}")
                    else:
                        _log_warn("  lentilkarma shaderString() also EMPTY!")
                finally:
                    if tmp:
                        tmp.destroy()
        else:
            _log_info("  lentilkarma not installed — skipping comparison")
    except Exception as e:
        _log_warn(f"  lentilkarma comparison failed: {e}")

    # Compare our definition side-by-side
    our_defn = vop_node.type().definition()
    if our_defn:
        our_extra = our_defn.extraInfo()
        our_sections = sorted(our_defn.sections().keys())
        _log_info(f"--- Our HDA ---")
        _log_info(f"  Our Extra: {our_extra!r}")
        _log_info(f"  Our Sections: {our_sections}")

        our_ds = our_defn.sections().get("DialogScript")
        if our_ds:
            ds_text = our_ds.contents()
            for line in ds_text.split('\n')[:20]:
                stripped = line.strip()
                if any(kw in stripped.lower() for kw in
                       ('shadertype', 'rendermask', 'name ', 'script ',
                        'context')):
                    _log_info(f"  Our DS: {stripped}")

        our_tpo = our_defn.sections().get("TypePropertiesOptions")
        if our_tpo:
            _log_info(f"  Our TPO preview: {our_tpo.contents()[:300]}")


def _verify_hda(hda_path):
    """Verify the patched HDA has the correct sections for Karma."""
    defn_list = hou.hda.definitionsInFile(hda_path)
    if not defn_list:
        _log_error("No HDA definitions found after install!")
        return

    defn = defn_list[0]
    sections = defn.sections()
    extra = defn.extraInfo()

    _log_info(f"HDA Extra: {extra!r}")
    _log_info(f"HDA Sections: {sorted(sections.keys())}")

    # Check required sections
    required = ["CVexVflCode", "VflCode", "FunctionName",
                "DialogScript", "TypePropertiesOptions"]
    for name in required:
        if name in sections:
            _log_info(f"  {name}: {len(sections[name].contents())} bytes")
        else:
            _log_error(f"  {name}: MISSING!")

    # Check FunctionName content
    fn_section = sections.get("FunctionName")
    if fn_section:
        fn = fn_section.contents()
        _log_info(f"  FunctionName value: '{fn}'")
        if fn != "blackhole_lens":
            _log_warn(f"  FunctionName mismatch! Expected 'blackhole_lens'")

    # Check CVexVflCode for export declarations
    if "CVexVflCode" in sections:
        cvex_code = sections["CVexVflCode"].contents()
        has_export_P = "export" in cvex_code and "P" in cvex_code
        has_export_I = "export" in cvex_code and "I" in cvex_code
        _log_info(f"  CVexVflCode exports: P={has_export_P} I={has_export_I}")

    # Check DialogScript
    if "DialogScript" in sections:
        ds = sections["DialogScript"].contents()
        has_output_P = 'output' in ds and '"P"' in ds
        has_output_I = 'output' in ds and '"I"' in ds
        has_output_tint = 'output' in ds and '"tint"' in ds
        _log_info(f"  DialogScript outputs: P={has_output_P} "
                  f"I={has_output_I} tint={has_output_tint}")

        # Log key metadata lines and verify critical fields
        has_rendermask = False
        has_shadertype_cvex = False
        for line in ds.split('\n'):
            stripped = line.strip()
            if any(kw in stripped.lower() for kw in
                   ('shadertype', 'rendermask', 'name ', 'script ')):
                _log_info(f"  DS: {stripped}")
            if 'rendermask' in stripped.lower():
                has_rendermask = True
            if 'shadertype' in stripped.lower() and 'cvex' in stripped.lower():
                has_shadertype_cvex = True

        if not has_rendermask:
            _log_error("  rendermask MISSING from DialogScript!")
        if not has_shadertype_cvex:
            _log_error("  shadertype cvex MISSING from DialogScript!")

    # Check Extra info
    if "shadertype=cvex" in extra:
        _log_info("Extra: shadertype=cvex confirmed")
    else:
        _log_warn(f"Extra may be wrong: {extra!r}")


# ---------------------------------------------------------------------------
# VOP Node Creation
# ---------------------------------------------------------------------------

def _find_installed_type(opname):
    """Find the installed VOP type name for a given opname."""
    # First pass: exact match
    for cat_name, cat in hou.nodeTypeCategories().items():
        for type_name in cat.nodeTypes():
            if type_name == opname:
                return type_name
    # Second pass: substring match (namespaced types)
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


def _find_or_create_vop_node(optype_name):
    """Find an existing VOP node of the given type, or create one in /mat."""
    installed_type = _find_installed_type(optype_name)
    if not installed_type:
        _log_warn(f"Could not find installed node type for '{optype_name}'")
        _log_info("Available VOP types with 'blackhole':")
        for cat_name, cat in hou.nodeTypeCategories().items():
            for type_name in cat.nodeTypes():
                if "blackhole" in type_name.lower():
                    _log_info(f"  {cat_name}/{type_name}")
        return None

    _log_info(f"Found installed type: {installed_type}")

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
# Camera / Stage Configuration
# ---------------------------------------------------------------------------

def _find_camera_lop(stage_net):
    """Find the first Camera LOP in the stage network."""
    for child in stage_net.children():
        if child.type().name() in ("camera", "cam"):
            return child
    # Check one level deep (subnets)
    for child in stage_net.children():
        try:
            for sub in child.children():
                if sub.type().name() in ("camera", "cam"):
                    return sub
        except hou.OperationFailed:
            pass
    return None


def _setup_lens_in_stage(vop_node, stage_net):
    """Configure the camera to use the lens shader via Camera LOP params.

    Sets three Camera LOP properties:
    1. use_lensshader = 1 (enable lens shader)
    2. lensshadervop = VOP node path (for Karma to find the VOP)
    3. lensshader = shader string (the resolved opdef: path, set directly)

    Each property also needs its companion _control parameter set to "set"
    so the property is authored on the USD stage.

    Returns True if at least one property was set successfully.
    """
    shader_string = ""
    try:
        shader_string = vop_node.shaderString() or ""
    except Exception as e:
        _log_error(f"shaderString() failed: {e}")
        return False

    if not shader_string:
        _log_error("shaderString() returned empty — cannot configure camera")
        return False

    _log_info(f"Shader string: {shader_string}")

    cam_lop = _find_camera_lop(stage_net)
    if not cam_lop:
        _log_warn("No Camera LOP found in /stage — manual setup required")
        return False

    _log_info(f"Found Camera LOP: {cam_lop.path()}")
    return _try_set_camera_params(cam_lop, vop_node.path(), shader_string)


def _try_set_camera_params(cam_lop, vop_path, shader_string):
    """Set Camera LOP parameters for lens shader.

    Matches lentilkarma's _try_configure_camera() approach plus an
    additional step: directly setting the hidden 'lensshader' property
    with the shader string, bypassing the Camera LOP's internal
    VOP-to-shaderString resolution.

    Camera LOP Karma properties follow this pattern:
    - xn__karmacamera<property>_<hash>  (value parameter)
    - xn__karmacamera<property>_control_<hash>  (control: "none"/"set"/"block")

    The _control parameter MUST be set to "set" (or int 1) for the
    property to be authored on the USD stage.
    """
    _log_info(f"Setting Camera LOP params on {cam_lop.path()}")

    # Log all lens-related parameters BEFORE changes
    for parm in cam_lop.parms():
        pname = parm.name().lower()
        if any(kw in pname for kw in ('lens', 'shader', 'vop')):
            try:
                val = parm.eval()
                _log_info(f"  BEFORE: {parm.name()} = {repr(val)[:80]}")
            except Exception:
                pass

    def _set_prop(pattern, value, exclude=None):
        """Set value + control parameters matching pattern.

        Args:
            pattern: Substring to match in lowercased parameter names
            value: Value to set on the value parameter
            exclude: Substrings that must NOT appear in the name
        """
        if exclude is None:
            exclude = []

        value_set = False
        control_set = False

        for parm in cam_lop.parms():
            pname = parm.name().lower()
            if pattern not in pname:
                continue
            if any(ex in pname for ex in exclude):
                continue

            is_ctrl = '_control' in pname

            if not is_ctrl and not value_set:
                try:
                    parm.set(value)
                    _log_info(f"  Set {parm.name()} = {repr(value)[:80]}")
                    value_set = True
                except Exception as e:
                    _log_warn(f"  Failed to set {parm.name()}: {e}")

            elif is_ctrl and not control_set:
                for ctrl_val in ("set", 1):
                    try:
                        parm.set(ctrl_val)
                        _log_info(f"  Set {parm.name()} = {ctrl_val!r}")
                        control_set = True
                        break
                    except Exception:
                        pass
                if not control_set:
                    _log_warn(f"  Could not set control for '{pattern}'")

        return value_set

    # 1. Enable "Use Lens Shader" toggle (value + control)
    enable_ok = _set_prop('karmacamerause_lensshader', 1)

    # 2. Set Lens Shader VOP path (value + control)
    vop_ok = _set_prop('karmacameralensshadervop', vop_path)

    # 3. Set the hidden 'lensshader' property DIRECTLY with the shader string.
    #    This bypasses the Camera LOP's VOP-to-shaderString resolution.
    #    CRITICAL: exclude 'vop' and 'use' from matching to avoid the
    #    substring collision where 'karmacameralensshader' matches
    #    'karmacameralensshadervop' (the former is a prefix of the latter).
    shader_ok = _set_prop('karmacameralensshader', shader_string,
                          exclude=['vop', 'use'])

    # Log all lens-related parameters AFTER changes
    for parm in cam_lop.parms():
        pname = parm.name().lower()
        if any(kw in pname for kw in ('lens', 'shader', 'vop')):
            try:
                val = parm.eval()
                _log_info(f"  AFTER: {parm.name()} = {repr(val)[:80]}")
            except Exception:
                pass

    if not enable_ok and not vop_ok and not shader_ok:
        _log_warn("Could not auto-configure camera — "
                  "run blackhole_houdini.discover_camera_parms()")

    return enable_ok or vop_ok or shader_ok


def discover_camera_parms(camera_path=None):
    """Print all lens/shader/material parameters on a Camera LOP.

    Use this if auto-configuration fails to find the correct parameter names.

    Usage:
        import blackhole_houdini
        blackhole_houdini.discover_camera_parms()
    """
    if camera_path:
        cam = hou.node(camera_path)
    else:
        stage = hou.node("/stage")
        cam = None
        if stage:
            cam = _find_camera_lop(stage)

    if not cam:
        print("No Camera LOP found. Pass camera_path='/stage/camera1'")
        return

    print(f"\nCamera: {cam.path()}")
    print(f"Type:   {cam.type().name()}")
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
        for parm in cam.parms():
            try:
                val = parm.eval()
            except Exception:
                val = "<error>"
            print(f"  {parm.name():50s} = {val}")


def _get_solaris_viewer():
    """Find the active Solaris SceneViewer pane tab."""
    desktop = hou.ui.curDesktop()
    for pane_tab in desktop.paneTabs():
        if pane_tab.type() == hou.paneTabType.SceneViewer:
            try:
                pane_tab.currentHydraRenderer()
                return pane_tab
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def diagnose(vop_path=None):
    """Run diagnostics on the black hole lens shader.

    Call this if Karma reports errors. Prints all relevant information
    about the HDA sections, Extra info, shaderString(), and the USD
    stage camera attributes.

    Usage:
        import blackhole_houdini
        blackhole_houdini.diagnose()
    """
    _log_info("=== Black Hole Lens Shader Diagnostics ===")

    # Find the VOP node
    if vop_path:
        vop = hou.node(vop_path)
    else:
        mat = hou.node("/mat")
        vop = None
        if mat:
            for child in mat.allSubChildren():
                if "blackhole" in child.type().name().lower():
                    vop = child
                    break

    if not vop:
        _log_error("No blackhole VOP node found in /mat")
        print("No blackhole VOP node found. Run build_blackhole_shader() first.")
        return

    print(f"\nVOP node: {vop.path()}")
    print(f"Type:     {vop.type().name()}")

    # Check definition
    defn = vop.type().definition()
    if not defn:
        _log_error("VOP type has no HDA definition!")
        print("ERROR: No HDA definition found!")
        return

    # Print all sections
    print(f"\n--- HDA Sections ---")
    for name, section in sorted(defn.sections().items()):
        contents = section.contents()
        print(f"  {name}: {len(contents)} bytes")

    # Print Extra info
    extra = defn.extraInfo()
    print(f"\n--- Extra Info ---")
    print(f"  {extra!r}")

    # Check FunctionName
    fn_section = defn.sections().get("FunctionName")
    if fn_section:
        print(f"\n--- FunctionName ---")
        print(f"  '{fn_section.contents()}'")
    else:
        print("\n  FunctionName: MISSING!")

    # Check CVexVflCode
    cvex_section = defn.sections().get("CVexVflCode")
    if cvex_section:
        code = cvex_section.contents()
        print(f"\n--- CVexVflCode ({len(code)} bytes) ---")
        print(f"  Has 'export': {'export' in code}")
        print(f"  Has 'vector P': {'vector P' in code}")
        print(f"  Has 'vector I': {'vector I' in code}")
        print(f"  Has 'blackhole_lens': {'blackhole_lens' in code}")
        print(f"  Preview: {code[:500]}...")
    else:
        print("\n  CVexVflCode: MISSING!")

    # Check VflCode
    vfl_section = defn.sections().get("VflCode")
    if vfl_section:
        vfl = vfl_section.contents()
        print(f"\n--- VflCode ({len(vfl)} bytes) ---")
        matches_cvex = (cvex_section and
                        vfl == cvex_section.contents())
        print(f"  Matches CVexVflCode: {matches_cvex}")
        has_include = '#include' in vfl
        has_pragma = '#pragma' in vfl
        has_Pragma = '_Pragma' in vfl
        print(f"  Has #include: {has_include} (should be False)")
        print(f"  Has #pragma: {has_pragma}")
        print(f"  Has _Pragma: {has_Pragma}")
        if has_include:
            print("  WARNING: VflCode has #include — Karma may fail "
                  "to resolve includes at render time!")
    else:
        print("\n  VflCode: MISSING! (Karma needs this)")

    # Check DialogScript — show FULL header with input/output declarations
    ds_section = defn.sections().get("DialogScript")
    if ds_section:
        ds = ds_section.contents()
        print(f"\n--- DialogScript ({len(ds)} bytes) ---")
        print(f"  First 30 lines:")
        for i, line in enumerate(ds.split('\n')[:30]):
            print(f"    {i+1:3d}: {line}")
        # Check for critical output declarations
        has_output_P = 'output\tvector\tP' in ds or 'output  vector  P' in ds
        has_output_I = 'output\tvector\tI' in ds or 'output  vector  I' in ds
        has_output_tint = ('output\tvector\ttint' in ds or
                           'output  vector  tint' in ds)
        print(f"\n  Output connectors: P={has_output_P} "
              f"I={has_output_I} tint={has_output_tint}")
        if not has_output_P or not has_output_I:
            print("  WARNING: Missing output connector declarations!")
            print("  Karma needs 'output vector P \"P\"' etc. in DialogScript")
    else:
        print("\n  DialogScript: MISSING!")

    # Check TypePropertiesOptions
    tpo_section = defn.sections().get("TypePropertiesOptions")
    if tpo_section:
        print(f"\n--- TypePropertiesOptions ({len(tpo_section.contents())} bytes) ---")
        print(f"  {tpo_section.contents()[:200]}")
    else:
        print("\n  TypePropertiesOptions: MISSING!")

    # Try shaderString()
    print(f"\n--- shaderString() ---")
    try:
        shader_str = vop.shaderString()
        if shader_str:
            print(f"  Length: {len(shader_str)} chars")
            print(f"  Value: {shader_str[:300]}")
        else:
            print("  EMPTY (None or empty string)")
            print("  This causes 'Missing shader name' error")
    except Exception as e:
        print(f"  ERROR: {e}")

    # Try code()
    print(f"\n--- code() ---")
    try:
        code_str = vop.code()
        if code_str:
            print(f"  Length: {len(code_str)} chars")
            print(f"  Full: {code_str}")
        else:
            print("  EMPTY")
    except Exception as e:
        print(f"  ERROR: {e}")

    # === USD Stage Inspection ===
    print(f"\n{'='*60}")
    print("USD STAGE INSPECTION")
    print(f"{'='*60}")

    stage_net = hou.node("/stage")
    if not stage_net:
        print("  No /stage network found")
    else:
        # Find display node (skip RopNodes which lack isDisplayFlagSet)
        display_node = None
        for child in stage_net.children():
            try:
                if child.isDisplayFlagSet():
                    display_node = child
                    break
            except AttributeError:
                continue

        if display_node:
            print(f"  Display node: {display_node.path()} "
                  f"({display_node.type().name()})")
            try:
                stage = display_node.stage()
                if stage:
                    print(f"  USD stage: {stage}")
                    # Find all Camera prims
                    for prim in stage.Traverse():
                        if prim.GetTypeName() == "Camera":
                            print(f"\n  Camera prim: {prim.GetPath()}")
                            # Check lens shader attributes
                            for attr_name in [
                                "karma:camera:lensshader",
                                "karma:camera:use_lensshader",
                                "karma:camera:lensshadervop",
                            ]:
                                attr = prim.GetAttribute(attr_name)
                                if attr and attr.HasValue():
                                    print(f"    {attr_name} = "
                                          f"{attr.Get()!r}")
                                else:
                                    print(f"    {attr_name} = "
                                          f"NOT SET")
                else:
                    print("  No USD stage available")
            except Exception as e:
                print(f"  Could not read stage: {e}")
        else:
            print("  No display node found in /stage")

    # === Reference shader comparison ===
    print(f"\n{'='*60}")
    print("REFERENCE SHADER COMPARISON (kma_physicallens)")
    print(f"{'='*60}")
    try:
        ref_nt = hou.nodeType(hou.vopNodeTypeCategory(),
                              "kma_physicallens")
        if ref_nt and ref_nt.definition():
            ref_defn = ref_nt.definition()
            ref_extra = ref_defn.extraInfo()
            ref_sections = sorted(ref_defn.sections().keys())
            print(f"  Extra: {ref_extra!r}")
            print(f"  Sections: {ref_sections}")

            ref_ds = ref_defn.sections().get("DialogScript")
            if ref_ds:
                ds_text = ref_ds.contents()
                print(f"  DialogScript first 25 lines:")
                for i, line in enumerate(ds_text.split('\n')[:25]):
                    print(f"    {i+1:3d}: {line}")
        else:
            print("  kma_physicallens not installed")
    except Exception as e:
        print(f"  Could not check kma_physicallens: {e}")

    print(f"\nLog file: {_get_log_path()}")


def dump_reference():
    """Dump kma_physicallens HDA structure for comparison.

    Use this to see exactly what a working Karma lens shader HDA looks like.

    Usage:
        import blackhole_houdini
        blackhole_houdini.dump_reference()
    """
    print("=== kma_physicallens HDA Structure ===\n")
    try:
        ref_nt = hou.nodeType(hou.vopNodeTypeCategory(), "kma_physicallens")
        if not ref_nt or not ref_nt.definition():
            print("kma_physicallens not installed!")
            return

        defn = ref_nt.definition()
        print(f"Extra Info: {defn.extraInfo()!r}")
        print(f"Sections: {sorted(defn.sections().keys())}")

        # FunctionName
        fn = defn.sections().get("FunctionName")
        if fn:
            print(f"\nFunctionName: '{fn.contents()}'")

        # TPO
        tpo = defn.sections().get("TypePropertiesOptions")
        if tpo:
            print(f"\nTypePropertiesOptions:\n{tpo.contents()}")

        # DialogScript header (first 30 lines)
        ds = defn.sections().get("DialogScript")
        if ds:
            print(f"\nDialogScript (first 30 lines):")
            for i, line in enumerate(ds.contents().split('\n')[:30]):
                print(f"  {i+1:3d}: {line}")

        # VflCode stats
        vfl = defn.sections().get("VflCode")
        if vfl:
            code = vfl.contents()
            print(f"\nVflCode: {len(code)} bytes, "
                  f"{code.count(chr(10))+1} lines")
            print(f"  Has 'export': {'export' in code}")
            print(f"  Has 'vector P': {'vector P' in code}")
            print(f"  Preview: {code[:200]}...")

        # CVexVflCode stats
        cvex = defn.sections().get("CVexVflCode")
        if cvex:
            print(f"\nCVexVflCode: {len(cvex.contents())} bytes")
        else:
            print(f"\nCVexVflCode: NOT PRESENT")

        # Test shaderString
        mat = hou.node("/mat")
        if mat:
            tmp = None
            try:
                tmp = mat.createNode("kma_physicallens", "__dump_test")
                ss = tmp.shaderString()
                print(f"\nshaderString(): {ss[:200] if ss else 'EMPTY'}...")
                code_str = tmp.code()
                print(f"code(): {code_str!r}")
            finally:
                if tmp:
                    tmp.destroy()

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Minimal Test
# ---------------------------------------------------------------------------

def test_minimal():
    """Build a MINIMAL lens shader to test the pipeline.

    If this works but the full blackhole shader doesn't, the issue is
    in the VFL code. If this also fails, the issue is in the pipeline
    (patching, camera config, etc.).

    Usage:
        import blackhole_houdini
        blackhole_houdini.test_minimal()
    """
    _log_info("=== Minimal Lens Shader Test ===")

    # Write the simplest possible CVEX lens shader
    minimal_vfl = '''#pragma opname      test_lens
#pragma oplabel     "Test Lens"
#pragma opmininputs 0
#pragma opmaxinputs 0

#pragma hint P invisible
#pragma hint I invisible
#pragma hint tint invisible

cvex test_lens(
    float x = 0;
    float y = 0;
    export vector P = {0, 0, 0};
    export vector I = {0, 0, 0};
    export vector tint = {1, 1, 1};
)
{
    P = {0, 0, 0};
    I = set(x, y, -1.0);
    tint = {1, 1, 1};
}
'''

    output_dir = get_output_dir()
    vfl_path = os.path.join(output_dir, "test_lens.vfl")
    with open(vfl_path, 'w') as f:
        f.write(minimal_vfl)
    _log_info(f"Wrote minimal VFL: {vfl_path}")

    # Compile
    hda_path = os.path.join(get_otls_dir(), "test_lens.hda")
    if os.path.exists(hda_path):
        try:
            hou.hda.uninstallFile(hda_path)
        except Exception:
            pass

    cmd = ['vcc', '-O', 'vop', '-l', hda_path, vfl_path]
    _log_info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        _log_error(f"vcc failed: {result.stderr}")
        print(f"vcc compilation failed:\n{result.stderr}")
        return

    _log_info(f"Compiled: {hda_path}")

    # Install and check raw vcc output
    hou.hda.installFile(hda_path)
    defn_list = hou.hda.definitionsInFile(hda_path)
    if not defn_list:
        print("No HDA definitions found!")
        return
    defn = defn_list[0]

    # Print raw vcc output for comparison
    print("\n=== RAW VCC OUTPUT (before patching) ===")
    print(f"Extra: {defn.extraInfo()!r}")
    print(f"Sections: {sorted(defn.sections().keys())}")
    ds = defn.sections().get("DialogScript")
    if ds:
        print("\nDialogScript (full):")
        for i, line in enumerate(ds.contents().split('\n')):
            print(f"  {i+1:3d}: {line}")
    cvex = defn.sections().get("CVexVflCode")
    if cvex:
        print(f"\nCVexVflCode ({len(cvex.contents())} bytes):")
        print(cvex.contents())

    # Patch (same order as lentilkarma: VflCode, FunctionName, Extra, DS, TPO)
    cvex_code = cvex.contents() if cvex else ""
    if cvex_code:
        defn.addSection("VflCode", cvex_code)
    defn.addSection("FunctionName", "test_lens")
    defn.setExtraInfo("shadertype=cvex subtype=material ")
    if ds:
        ds_text = ds.contents()
        ds_text = re.sub(r'(\s+shadertype\s+)\S+', r'\1cvex', ds_text)
        if re.search(r'\s+rendermask\s+', ds_text):
            ds_text = re.sub(r'(\s+rendermask\s+)\S+',
                             r'\1"VMantra OGL"', ds_text)
        else:
            lines = ds_text.split('\n')
            new_lines = []
            for line in lines:
                new_lines.append(line)
                if re.match(r'\s+shadertype\s+', line):
                    new_lines.append('  rendermask\t"VMantra OGL"')
            ds_text = '\n'.join(new_lines)
        ds.setContents(ds_text)
    _copy_or_create_tpo(defn)

    defn.save(hda_path)
    hou.hda.installFile(hda_path)

    print("\n=== AFTER PATCHING ===")
    print(f"Extra: {defn.extraInfo()!r}")
    print(f"Sections: {sorted(defn.sections().keys())}")

    # Create VOP node
    mat = hou.node("/mat")
    if mat:
        old = mat.node("test_lens")
        if old:
            old.destroy()

    vop = _find_or_create_vop_node("test_lens")
    if vop:
        ss = vop.shaderString()
        print(f"\nshaderString(): {ss!r}")
        code = vop.code()
        print(f"code(): {code!r}")
    else:
        print("\nCould not create VOP node!")

    print(f"\nIf this minimal shader ALSO fails in Karma, the issue is "
          f"in the pipeline. If it works, the issue is the VFL code.")


def test_with_strings():
    """Test whether string parameters break the CVEX lens shader.

    Builds the same minimal lens shader as test_minimal(), but adds
    string parameters (env_map, star_file). If shaderString() returns
    empty here but works in test_minimal(), string parameters are the
    cause of the '(null)' error.

    Every working CVEX lens shader in this project (anaglyphlens,
    lentilkarma, kma_physicallens) has ZERO string parameters.

    Usage:
        import blackhole_houdini
        blackhole_houdini.test_with_strings()
    """
    _log_info("=== String Parameter Test ===")

    vfl = '''#pragma opname      test_strings
#pragma oplabel     "Test Strings"
#pragma opmininputs 0
#pragma opmaxinputs 0

#pragma hint P invisible
#pragma hint I invisible
#pragma hint tint invisible

#pragma label env_map "Environment Map"
#pragma hint  env_map file
#pragma label star_file "Star Point Cloud"
#pragma hint  star_file file

cvex test_strings(
    float x = 0;
    float y = 0;
    export vector P = {0, 0, 0};
    export vector I = {0, 0, 0};
    export vector tint = {1, 1, 1};
    string env_map = "";
    string star_file = "";
)
{
    P = {0, 0, 0};
    I = set(x, y, -1.0);
    tint = {1, 1, 1};
}
'''

    output_dir = get_output_dir()
    vfl_path = os.path.join(output_dir, "test_strings.vfl")
    with open(vfl_path, 'w') as f:
        f.write(vfl)

    hda_path = os.path.join(get_otls_dir(), "test_strings.hda")
    if os.path.exists(hda_path):
        try:
            hou.hda.uninstallFile(hda_path)
        except Exception:
            pass

    cmd = ['vcc', '-O', 'vop', '-l', hda_path, vfl_path]
    _log_info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        _log_error(f"vcc failed: {result.stderr}")
        print(f"vcc compilation failed:\n{result.stderr}")
        return

    hou.hda.installFile(hda_path)
    defn_list = hou.hda.definitionsInFile(hda_path)
    if not defn_list:
        print("No HDA definitions found!")
        return
    defn = defn_list[0]

    # Show raw DialogScript for inspection
    ds = defn.sections().get("DialogScript")
    if ds:
        print("RAW DialogScript:")
        for i, line in enumerate(ds.contents().split('\n')):
            print(f"  {i+1:3d}: {line}")

    # Patch (same order as lentilkarma: VflCode, FunctionName, Extra, DS, TPO)
    cvex = defn.sections().get("CVexVflCode")
    cvex_code = cvex.contents() if cvex else ""
    if cvex_code:
        defn.addSection("VflCode", cvex_code)
    defn.addSection("FunctionName", "test_strings")
    defn.setExtraInfo("shadertype=cvex subtype=material ")
    if ds:
        ds_text = ds.contents()
        ds_text = re.sub(r'(\s+shadertype\s+)\S+', r'\1cvex', ds_text)
        if re.search(r'\s+rendermask\s+', ds_text):
            ds_text = re.sub(r'(\s+rendermask\s+)\S+',
                             r'\1"VMantra OGL"', ds_text)
        else:
            lines = ds_text.split('\n')
            new_lines = []
            for line in lines:
                new_lines.append(line)
                if re.match(r'\s+shadertype\s+', line):
                    new_lines.append('  rendermask\t"VMantra OGL"')
            ds_text = '\n'.join(new_lines)
        ds.setContents(ds_text)
    _copy_or_create_tpo(defn)
    defn.save(hda_path)
    hou.hda.installFile(hda_path)

    # Create VOP and test
    mat = hou.node("/mat")
    if mat:
        old = mat.node("test_strings")
        if old:
            old.destroy()

    vop = _find_or_create_vop_node("test_strings")
    if vop:
        ss = vop.shaderString()
        code = vop.code()
        print(f"\nshaderString(): {ss!r}")
        print(f"code(): {code!r}")

        if ss:
            print("\n*** STRING PARAMS WORK — issue is elsewhere ***")
        else:
            print("\n*** STRING PARAMS BREAK shaderString() ***")
            print("Fix: Remove string params from function signature,")
            print("     bake file paths at code generation time instead.")
    else:
        print("\nCould not create VOP node!")


def test_full_params():
    """Test with ALL blackhole params/pragmas but trivial body.

    Isolates whether the issue is in the parameter declarations/pragmas
    or in the function body code.

    Usage:
        import blackhole_houdini
        blackhole_houdini.test_full_params()
    """
    _log_info("=== Full Params Test ===")

    vfl = '''#pragma opname      test_fullp
#pragma oplabel     "Test Full Params"
#pragma opmininputs 0
#pragma opmaxinputs 0

#pragma hint x invisible
#pragma hint y invisible
#pragma hint Time invisible
#pragma hint dofx invisible
#pragma hint dofy invisible
#pragma hint aspect invisible
#pragma hint P invisible
#pragma hint I invisible
#pragma hint tint invisible

#pragma hint  singularity_pos hidden

#pragma label mass "Black Hole Mass"
#pragma range mass 0.001 1.0
#pragma label maxsteps "Max Steps"
#pragma range maxsteps 1 500
#pragma label stepsize "Step Size"
#pragma range stepsize 0.01 10.0

#pragma label env_map "Environment Map"
#pragma hint  env_map file
#pragma label env_map_mask "Environment Mask"
#pragma hint  env_map_mask file
#pragma label env_intensity "Env Intensity"
#pragma range env_intensity 0.0 10.0
#pragma label env_blur "Env Blur"
#pragma range env_blur 0.0 1.0

#pragma label star_file "Star Point Cloud"
#pragma hint  star_file file
#pragma label star_intensity "Star Intensity"
#pragma range star_intensity 0.0 50.0
#pragma label star_size "Star Size"
#pragma range star_size 0.0001 0.01
#pragma label star_blur "Motion Blur Amount"
#pragma range star_blur 0.0 1.0

#pragma label focal_length "Focal Length"
#pragma label horizontal_aperture "Horizontal Aperture"

#include "math.h"

cvex test_fullp(
    float x = 0;
    float y = 0;
    float Time = 0;
    float dofx = 0;
    float dofy = 0;
    float aspect = 1;
    export vector P = {0, 0, 0};
    export vector I = {0, 0, 0};
    export vector tint = {1, 1, 1};

    vector singularity_pos = {0, 0, 0};
    float mass = 0.04;
    int maxsteps = 200;
    float stepsize = 1.0;

    string env_map = "";
    string env_map_mask = "";
    float env_intensity = 1.0;
    float env_blur = 0.0;

    string star_file = "";
    float star_intensity = 10.0;
    float star_size = 0.002;
    float star_blur = 0.5;

    float focal_length = 50.0;
    float horizontal_aperture = 41.4214;
)
{
    P = {0, 0, 0};
    I = set(x, y, -1.0);
    tint = {1, 1, 1};
}
'''

    opname = "test_fullp"
    result = _build_and_test(vfl, opname)
    if result:
        print("\n*** FULL PARAMS WORK — issue is in function body ***")
    else:
        print("\n*** FULL PARAMS BREAK IT — issue is in params/pragmas ***")


def test_full_build():
    """Build the FULL blackhole shader and report shaderString() result.

    This is the same as build_blackhole_shader() but focuses only on
    whether shaderString() works, without camera configuration.

    Usage:
        import blackhole_houdini
        blackhole_houdini.test_full_build()
    """
    _log_info("=== Full Build Test ===")

    vfl_path, vfl_source = _generate_vfl()
    hda_path = _compile_vfl(vfl_path)
    _patch_for_karma(hda_path)

    mat = hou.node("/mat")
    if mat:
        old = mat.node("blackhole_lens")
        if old:
            old.destroy()

    vop = _find_or_create_vop_node("blackhole_lens")
    if vop:
        ss = vop.shaderString()
        code = vop.code()
        print(f"\nshaderString(): {ss!r}")
        print(f"code(): {code!r}")
        if ss:
            print("\n*** shaderString() WORKS for full shader ***")
            print("Issue is in Karma shader compilation or camera config.")
        else:
            print("\n*** shaderString() EMPTY for full shader ***")
            print("Issue is in VFL code or HDA structure.")
    else:
        print("\nCould not create VOP node!")


def _build_and_test(vfl_source, opname):
    """Helper: compile VFL, patch, create VOP, test shaderString().

    Returns True if shaderString() returns a non-empty value.
    """
    output_dir = get_output_dir()
    vfl_path = os.path.join(output_dir, f"{opname}.vfl")
    with open(vfl_path, 'w') as f:
        f.write(vfl_source)

    hda_path = os.path.join(get_otls_dir(), f"{opname}.hda")
    if os.path.exists(hda_path):
        try:
            hou.hda.uninstallFile(hda_path)
        except Exception:
            pass

    cmd = ['vcc', '-O', 'vop', '-l', hda_path, vfl_path]
    _log_info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        _log_error(f"vcc failed: {result.stderr}")
        print(f"vcc compilation failed:\n{result.stderr}")
        return False
    if result.stderr:
        print(f"vcc warnings: {result.stderr}")

    hou.hda.installFile(hda_path)
    defn_list = hou.hda.definitionsInFile(hda_path)
    if not defn_list:
        print("No HDA definitions found!")
        return False
    defn = defn_list[0]

    # Patch (same order as lentilkarma: VflCode, FunctionName, Extra, DS, TPO)
    cvex = defn.sections().get("CVexVflCode")
    cvex_code = cvex.contents() if cvex else ""
    if cvex_code:
        defn.addSection("VflCode", cvex_code)
    defn.addSection("FunctionName", opname)
    defn.setExtraInfo("shadertype=cvex subtype=material ")
    ds = defn.sections().get("DialogScript")
    if ds:
        ds_text = ds.contents()
        ds_text = re.sub(r'(\s+shadertype\s+)\S+', r'\1cvex', ds_text)
        if re.search(r'\s+rendermask\s+', ds_text):
            ds_text = re.sub(r'(\s+rendermask\s+)\S+',
                             r'\1"VMantra OGL"', ds_text)
        else:
            lines = ds_text.split('\n')
            new_lines = []
            for line in lines:
                new_lines.append(line)
                if re.match(r'\s+shadertype\s+', line):
                    new_lines.append('  rendermask\t"VMantra OGL"')
            ds_text = '\n'.join(new_lines)
        ds.setContents(ds_text)
    _copy_or_create_tpo(defn)
    defn.save(hda_path)
    hou.hda.installFile(hda_path)

    # Create VOP
    mat = hou.node("/mat")
    if mat:
        old = mat.node(opname)
        if old:
            old.destroy()

    vop = _find_or_create_vop_node(opname)
    if not vop:
        print("Could not create VOP node!")
        return False

    ss = vop.shaderString()
    code = vop.code()
    print(f"  shaderString(): {ss!r}")
    print(f"  code(): {code!r}")
    return bool(ss)


# ---------------------------------------------------------------------------
# Main Build API
# ---------------------------------------------------------------------------

def _build_dialog_script_for_blackhole():
    """Build a DialogScript for the blackhole lens shader.

    Models the DialogScript on kma_physicallens format with our parameters.
    """
    ds = """{
    name	blackhole_lens
    script	blackhole_lens
    label	"Black Hole Lens"
    rendermask	"VMantra OGL"
    shadertype	cvex
    input	float	x	x
    input	float	y	y
    input	float	Time	Time
    input	float	dofx	dofx
    input	float	dofy	dofy
    input	float	aspect	aspect
    output	vector	P	P
    output	vector	I	I
    output	vector	tint	tint
    inputflags	x	2
    inputflags	y	2
    inputflags	Time	2
    inputflags	dofx	2
    inputflags	dofy	2
    inputflags	aspect	2
    signature	"Default Inputs"	default	{ float float float float float float vector vector vector }

    outputoverrides	default
    {
	___begin	auto
			(0,0,0)
	___begin	auto
			(0,0,0)
	___begin	auto
			(1,1,1)
    }

    help {
	"Black Hole gravitational lensing CVEX lens shader for Karma."
	""
	"Based on Matt Ebb's gravitational lensing VOP (CC-BY 3.0)."
    }

    parm {
	name	"singularity_pos"
	label	"Singularity Position (World)"
	type	vector
	size	3
	default	{ "0" "0" "0" }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"camera_pos"
	label	"Camera Position (World)"
	type	vector
	size	3
	default	{ "0" "0" "10" }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"mass"
	label	"Black Hole Mass"
	type	float
	default	{ "0.04" }
	range	{ 0.001! 1 }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"maxsteps"
	label	"Max Steps"
	type	integer
	default	{ "200" }
	range	{ 1! 500 }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"stepsize"
	label	"Step Size"
	type	float
	default	{ "1" }
	range	{ 0.01! 10 }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"env_map"
	label	"Environment Map"
	type	image
	default	{ "" }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"env_map_mask"
	label	"Environment Mask"
	type	image
	default	{ "" }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"env_intensity"
	label	"Env Intensity"
	type	float
	default	{ "1" }
	range	{ 0 10 }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"env_blur"
	label	"Env Blur"
	type	float
	default	{ "0" }
	range	{ 0 1 }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"star_file"
	label	"Star Point Cloud"
	type	geometry
	default	{ "" }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"star_intensity"
	label	"Star Intensity"
	type	float
	default	{ "10" }
	range	{ 0 50 }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"star_size"
	label	"Star Size"
	type	float
	default	{ "0.002" }
	range	{ 0.0001 0.01 }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"star_blur"
	label	"Motion Blur Amount"
	type	float
	default	{ "0.5" }
	range	{ 0 1 }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"focal_length"
	label	"Focal Length"
	type	float
	default	{ "50" }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
    parm {
	name	"horizontal_aperture"
	label	"Horizontal Aperture"
	type	float
	default	{ "41.4214" }
	parmtag	{ "shaderparmcontexts" "cvex" }
    }
}
"""
    return ds


def build_blackhole_shader():
    """One-button build: generate VFL, compile with vcc, patch for Karma.

    Pipeline:
      1. Generate VFL source from blackhole_codegen
      2. Compile with vcc -O vop -l (creates correctly-named operator)
      3. Patch: replace DialogScript from scratch, set Extra/TPO/VflCode
      4. Create VOP node in /mat
      5. Auto-configure camera if possible

    Call from Houdini Python Shell:
        import blackhole_houdini
        blackhole_houdini.build_blackhole_shader()
    """
    _log_info("=== Black Hole Lens Shader Build ===")
    t0 = time.time()

    # Clean up stale nodes from previous runs
    mat = hou.node("/mat")
    if mat:
        for old_name in ("blackhole_lens",):
            old_node = mat.node(old_name)
            if old_node:
                _log_info(f"Removing stale node: {old_node.path()}")
                old_node.destroy()

    # Clean up stale Python Script LOP from previous approach
    stage_net = hou.node("/stage")
    if stage_net:
        old_lop = stage_net.node("blackhole_lens_setup")
        if old_lop:
            _log_info(f"Removing stale Python Script LOP: {old_lop.path()}")
            old_lop.destroy()

    # Uninstall any previous HDA
    otls_dir = get_otls_dir()
    old_hda = os.path.join(otls_dir, "blackhole_lens.hda")
    if os.path.exists(old_hda):
        try:
            hou.hda.uninstallFile(old_hda)
            _log_info("Uninstalled previous HDA")
        except Exception:
            pass

    # Step 1: Generate VFL
    _log_info("Step 1: Generating VFL...")
    try:
        vfl_path, vfl_source = _generate_vfl()
    except Exception as e:
        _log_error(f"VFL generation failed: {e}")
        _log_error(traceback.format_exc())
        hou.ui.displayMessage(
            f"Error generating VFL:\n{str(e)}\n\n"
            f"Check log: {_get_log_path()}",
            title="Black Hole Lens Error",
            severity=hou.severityType.Error
        )
        return

    # Step 2: Compile with vcc
    _log_info("Step 2: Compiling with vcc...")
    try:
        hda_path = _compile_vfl(vfl_path)
    except Exception as e:
        _log_error(f"Compilation failed: {e}")
        _log_error(traceback.format_exc())
        hou.ui.displayMessage(
            f"Error compiling shader:\n{str(e)}\n\n"
            f"Check log: {_get_log_path()}",
            title="Black Hole Lens Error",
            severity=hou.severityType.Error
        )
        return

    # Step 3: Patch for Karma
    _log_info("Step 3: Patching for Karma...")
    try:
        _patch_for_karma(hda_path)
    except Exception as e:
        _log_error(f"Patching failed: {e}")
        _log_error(traceback.format_exc())
        hou.ui.displayMessage(
            f"Error patching shader:\n{str(e)}\n\n"
            f"Check log: {_get_log_path()}",
            title="Black Hole Lens Error",
            severity=hou.severityType.Error
        )
        return

    # Step 4: Create VOP node in /mat
    _log_info("Step 4: Creating VOP node...")
    vop_node = _find_or_create_vop_node("blackhole_lens")
    if not vop_node:
        _log_error("Could not create VOP node in /mat")
        hou.ui.displayMessage(
            "Shader compiled but could not create VOP node.\n"
            "Try creating manually: Tab menu in /mat > blackhole_lens",
            title="Black Hole Lens Warning",
            severity=hou.severityType.Warning
        )
        return

    _log_info(f"VOP node: {vop_node.path()}")

    # Test shaderString() immediately
    _log_info("Testing shaderString()...")
    _test_shader_string(vop_node)

    # Step 5: Configure camera
    _log_info("Step 5: Configuring camera...")
    camera_configured = False
    stage_net = hou.node("/stage")
    if stage_net:
        try:
            camera_configured = _setup_lens_in_stage(
                vop_node, stage_net)
        except Exception as e:
            _log_warn(f"Camera auto-config failed: {e}")
            _log_warn(traceback.format_exc())

    dt = time.time() - t0
    _log_info(f"=== Build complete in {dt:.2f}s ===")

    _show_result(vop_node, camera_configured, dt)


def _show_result(vop_node, camera_configured, build_time):
    """Show a result dialog with setup instructions."""
    msg = "Black Hole lens shader compiled!\n\n"
    msg += f"VOP node: {vop_node.path()}\n"
    msg += f"Build time: {build_time:.1f}s\n"

    if camera_configured:
        msg += "\nCamera configured automatically.\n"
    else:
        msg += "\nCamera setup (manual):\n"
        msg += "  1. Camera LOP > Karma tab > Use Lens Shader = ON\n"
        msg += f"  2. Lens Shader VOP = {vop_node.path()}\n"

    msg += "\nParameters on the VOP node:\n"
    msg += "  - mass: Black hole strength (0.04 default)\n"
    msg += "  - maxsteps: Ray march quality (200 default)\n"
    msg += "  - stepsize: Integration step multiplier\n"
    msg += "  - env_map: Environment map (.exr/.hdr)\n"
    msg += "  - star_file: Star point cloud (.bgeo)\n"
    msg += "  - singularity_pos: Black hole position\n"

    msg += f"\nIf Karma reports errors, run:\n"
    msg += f"  import blackhole_houdini; blackhole_houdini.diagnose()\n"

    msg += f"\nLog: {_get_log_path()}"

    hou.ui.displayMessage(msg, title="Black Hole Lens Shader")
