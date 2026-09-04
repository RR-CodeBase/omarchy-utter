#!/usr/bin/env python3
"""Conformance with the Omarchy plugin guide.

Run: python3 tests/test_plugin.py

https://plugins.omarchy.org/develop.html sets out what a plugin folder must
look like and how to validate it. Doing that once by hand is not the same as
keeping it true, so the checks live here: the manifest contract, the entry
point, the folder rules, and qmllint against the installed shell.

Checks needing Omarchy or qmllint are skipped when those are missing, so this
still runs on a machine that is not the target.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / "manifest.json").read_text())

PASSED, SKIPPED, FAILED = 0, [], []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
    else:
        FAILED.append(f"{name}{(': ' + detail) if detail else ''}")


def skip(name, why):
    SKIPPED.append(f"{name} ({why})")


# ---- the manifest contract -------------------------------------------------

for field in ["schemaVersion", "id", "name", "version", "author", "description",
              "kinds", "entryPoints"]:
    check(f"manifest has {field}", field in MANIFEST and MANIFEST[field] not in ("", [], {}))

check("schemaVersion is 1", MANIFEST.get("schemaVersion") == 1)
check("license is declared", bool(MANIFEST.get("license")), "the guide's example declares one")
check("version is under 64 characters", len(str(MANIFEST.get("version", ""))) <= 64)

# Third-party ids cannot use the omarchy.* namespace.
check("id is not in the omarchy namespace",
      not str(MANIFEST["id"]).startswith("omarchy."), MANIFEST["id"])
check("id is namespaced", str(MANIFEST["id"]).count(".") >= 2, MANIFEST["id"])
check("no clone marker is left in the manifest",
      "clonedFrom" not in (MANIFEST.get("omarchy") or {}),
      "remove omarchy.clonedFrom before publishing")

# ---- kind and entry point agree --------------------------------------------

KIND_TO_KEY = {"bar-widget": "barWidget", "panel": "panel", "overlay": "overlay",
               "menu": "menu", "service": "service", "bar": "bar"}

for kind in MANIFEST["kinds"]:
    check(f"{kind} is a known kind", kind in KIND_TO_KEY, kind)
    key = KIND_TO_KEY.get(kind)
    check(f"{kind} declares entryPoints.{key}", key in MANIFEST["entryPoints"])

for key, rel in MANIFEST["entryPoints"].items():
    target = ROOT / rel
    check(f"entry point {rel} exists", target.is_file(), str(target))
    check(f"entry point {rel} is a safe relative path",
          not os.path.isabs(rel) and ".." not in Path(rel).parts, rel)
    # "Make the value in entryPoints match the filename and capitalization on
    # disk" -- a case mismatch is a Troubleshooting entry in the guide.
    if target.is_file():
        check(f"entry point {rel} matches the on-disk capitalisation",
              target.name in [p.name for p in target.parent.iterdir()], rel)

# ---- folder rules ----------------------------------------------------------

symlinks = [p for p in ROOT.rglob("*") if p.is_symlink() and ".git" not in p.parts]
check("no symlinks in the plugin folder", not symlinks, str(symlinks[:3]))

for required in ["README.md", "LICENSE"]:
    check(f"{required} is present", (ROOT / required).exists())

readme = (ROOT / "README.md").read_text()
for section in ["## Install", "## Usage", "## Configure", "## Remove"]:
    check(f"README has an {section.strip('# ')} section", section in readme)
check("README documents removal by id", MANIFEST["id"] in readme)

# ---- the CLI, its completion, and the installer that wires them up ----------

# The READMEs document bare `<cli> ...` commands, so something has to put the
# CLI on PATH. install.sh does, and must undo it again on --uninstall.

CLI_NAME = MANIFEST["id"].rsplit(".", 1)[-1]
cli = ROOT / "bin" / CLI_NAME
check(f"bin/{CLI_NAME} exists and is executable", cli.is_file() and os.access(cli, os.X_OK))

completion = ROOT / "completions" / CLI_NAME
check(f"completions/{CLI_NAME} is shipped", completion.is_file())
if completion.is_file():
    r = subprocess.run(["bash", "-n", str(completion)], capture_output=True, text=True)
    check("completion is valid bash", r.returncode == 0, r.stderr.strip()[:200])
    check("completion registers the command",
          f"complete -F _{CLI_NAME} {CLI_NAME}" in completion.read_text())

installer = ROOT / "install.sh"
check("install.sh is present and executable", installer.is_file() and os.access(installer, os.X_OK))
if installer.is_file():
    sh = installer.read_text()
    r = subprocess.run(["bash", "-n", str(installer)], capture_output=True, text=True)
    check("install.sh is valid bash", r.returncode == 0, r.stderr.strip()[:200])
    check("install.sh links the CLI onto PATH", ".local/bin/" + CLI_NAME in sh)
    check("install.sh installs the completion", "bash-completion/completions/" + CLI_NAME in sh)
    # Whatever it creates outside the plugin folder, --uninstall must remove.
    check("install.sh removes the symlink again", 'rm -f "$BIN_LINK"' in sh)
    check("install.sh removes the completion again", 'rm -f "$COMPLETION"' in sh)

# ---- listing preview --------------------------------------------------------

previews = [p for p in ROOT.glob("preview.*")
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".avif"}]
check("exactly one root preview image", len(previews) == 1,
      "the marketplace reads a single root preview.*: " + str([p.name for p in previews]))
if previews:
    size = previews[0].stat().st_size
    check("preview is under the 50 MB marketplace limit", size < 50 * 1024 * 1024,
          f"{size / 1e6:.1f} MB")

# ---- omarchy's own validator -----------------------------------------------

if not shutil.which("omarchy"):
    skip("omarchy plugin validate", "omarchy not installed")
else:
    r = subprocess.run(["omarchy", "plugin", "validate", str(ROOT)],
                       capture_output=True, text=True, timeout=60)
    check("omarchy plugin validate passes", r.returncode == 0,
          (r.stdout + r.stderr).strip()[:200])

# ---- qmllint ---------------------------------------------------------------
# Quickshell exposes the shell directory as the module `qs`, so qmllint needs
# an import root containing a `qs` entry rather than the shell path itself.

qmllint = shutil.which("qmllint") or "/usr/lib/qt6/bin/qmllint"
shell_dir = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell"

if not Path(qmllint).exists() or not shell_dir.is_dir():
    skip("qmllint", "qmllint or the Omarchy shell is not installed")
else:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.symlink(shell_dir, Path(td) / "qs")
        for rel in MANIFEST["entryPoints"].values():
            r = subprocess.run([qmllint, "-I", td, str(ROOT / rel)],
                               capture_output=True, text=True, timeout=120)
            out = r.stdout + r.stderr
            # missing-property and unqualified fire in Omarchy's own widgets
            # too -- the bar and the Style/Color singletons are dynamically
            # typed. property-override does not, and it is the one that bites:
            # shadowing Item.state or Item.enabled silently breaks a widget.
            overrides = [l for l in out.splitlines() if "[property-override]" in l]
            check(f"{rel} shadows no base-type property", not overrides,
                  "; ".join(overrides[:2]))
            check(f"{rel} has no syntax errors",
                  "error:" not in out.lower() or r.returncode == 0,
                  out.strip()[:200])

print(f"\n{PASSED} passed, {len(FAILED)} failed, {len(SKIPPED)} skipped")
for s in SKIPPED:
    print(f"  SKIP  {s}")
for f in FAILED:
    print(f"  FAIL  {f}")
sys.exit(1 if FAILED else 0)
