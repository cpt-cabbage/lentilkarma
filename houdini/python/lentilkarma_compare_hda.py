"""
Extract and compare DialogScript from our test modern HDA vs the anaglyphlens demo.

Usage in Houdini Python Shell:
    exec(open(r"C:/Users/christophe.leyder/Desktop/LensSim-3.2.0/houdini/python/lentilkarma_compare_hda.py").read())
"""

import hou
import os
import subprocess

print("=" * 60)
print("HDA DialogScript Comparison")
print("=" * 60)

output_dir = r"C:\Users\christophe.leyder\Desktop\LensSim-3.2.0\houdini\vex\_hda_compare"
os.makedirs(output_dir, exist_ok=True)

# Find HDAs
otls_dir = os.path.join(hou.homeHoudiniDirectory(), "otls")
our_hda = os.path.join(otls_dir, "lentilkarma_test_modern.hda")
hfs = os.environ.get("HFS", "")
demo_hda = os.path.join(hfs, "houdini", "help", "files", "anaglyphlens.hda")

# Also check for the combined shader
combined_hda = os.path.join(otls_dir, "lentilkarma_combined.hda")

# Find hotl
hotl = os.path.join(hfs, "bin", "hotl.exe")
if not os.path.exists(hotl):
    hotl = os.path.join(hfs, "bin", "hotl")

print(f"  hotl: {hotl}")
print(f"  Our HDA: {our_hda} (exists: {os.path.exists(our_hda)})")
print(f"  Demo HDA: {demo_hda} (exists: {os.path.exists(demo_hda)})")
print(f"  Combined HDA: {combined_hda} (exists: {os.path.exists(combined_hda)})")

# Extract both
for label, hda_path, subdir in [
    ("OUR TEST", our_hda, "ours"),
    ("DEMO", demo_hda, "demo"),
    ("COMBINED", combined_hda, "combined"),
]:
    if not os.path.exists(hda_path):
        print(f"\n  Skipping {label}: HDA not found")
        continue

    extract_dir = os.path.join(output_dir, subdir)
    os.makedirs(extract_dir, exist_ok=True)

    print(f"\n--- Extracting {label} ---")
    cmd = [hotl, "-t", extract_dir, hda_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"  hotl failed: {result.stderr}")
        continue
    print(f"  Extracted to: {extract_dir}")

    # List contents
    for root, dirs, files in os.walk(extract_dir):
        for f in files:
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, extract_dir)
            print(f"    {rel} ({os.path.getsize(fp)} bytes)")

# Now read and print DialogScripts side by side
print(f"\n{'=' * 60}")
print("DialogScript Comparison")
print(f"{'=' * 60}")

for label, subdir in [("OUR TEST", "ours"), ("DEMO", "demo"), ("COMBINED", "combined")]:
    ds_dir = os.path.join(output_dir, subdir)
    # Find DialogScript
    ds_path = None
    for root, dirs, files in os.walk(ds_dir):
        for f in files:
            if f == "DialogScript":
                ds_path = os.path.join(root, f)
                break

    if ds_path:
        print(f"\n--- {label} DialogScript ---")
        with open(ds_path, "r") as f:
            content = f.read()
        print(content)
    else:
        print(f"\n--- {label}: DialogScript not found ---")

print("=" * 60)
