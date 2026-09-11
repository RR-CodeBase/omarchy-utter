#!/usr/bin/env python3
"""Tests for the two files Desktop Voice Control places outside its own folder.

Run: python3 tests/test_install_safety.py

`~/.local/bin/utter` and the bash completion are the only paths install.sh
writes into directories it does not own, so they are the only ones where it can
collide with something of the user's. The rule is that neither is replaced or
deleted unless Desktop Voice Control can prove it created it, and these tests plant every
shape of collision that rule exists for - a stranger's regular file, a symlink
aimed somewhere else, a directory - then check the real helpers, lifted out of
install.sh itself, refuse each one.
"""

import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ID = "io.github.rr-codebase.utter"
CLI_NAME = "utter"
MARK = "managed by " + PLUGIN_ID

PASSED, FAILED = 0, []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print("[PASS] " + name)
    else:
        FAILED.append(name + ((": " + detail) if detail else ""))
        print("[FAIL] " + name + ((" - " + detail) if detail else ""))


# ---- the ownership helpers, lifted out of the real install.sh ---------------
# Extracted rather than reimplemented: a copy in the test would happily keep
# passing after the shipped ones drifted.

SH = (ROOT / "install.sh").read_text()
_start = SH.index('CLI_NAME="')
_body = SH.index("file_is_ours() {", _start)
_end = SH.index("\n}\n", _body) + 3
HELPERS = SH[_start:_end]
check("the ownership helpers were found in install.sh",
      "link_is_ours" in HELPERS and "file_is_ours" in HELPERS)

SB = Path(tempfile.mkdtemp(prefix="utter-install-safety-"))
PLUGIN = SB / ".config/omarchy/plugins" / PLUGIN_ID / "bin"
PLUGIN.mkdir(parents=True)
CLI = PLUGIN / CLI_NAME
CLI.write_text("#!/bin/sh\n")
CLI.chmod(0o755)


def probe(predicate, path):
    """Run one helper out of install.sh against one planted path."""
    script = "\n".join([
        "set -uo pipefail",
        "HOME=" + shlex.quote(str(SB)),
        "PLUGIN_ID=" + shlex.quote(PLUGIN_ID),
        "CLI=" + shlex.quote(str(CLI)),
        HELPERS,
        predicate + " " + shlex.quote(str(path)),
    ])
    return subprocess.run(["bash", "-c", script],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


# ---- link_is_ours: only a symlink naming our own CLI counts -----------------

cases = SB / "cases"
cases.mkdir()

check("an absent path is not ours to replace",
      not probe("link_is_ours", cases / "absent"))

stranger = cases / "stranger"
stranger.write_text("#!/bin/sh\necho someone else's script\n")
check("a stranger's regular file on PATH is not ours",
      not probe("link_is_ours", stranger))

elsewhere = cases / "elsewhere"
elsewhere.symlink_to("/bin/sh")
check("a symlink pointing somewhere else is not ours",
      not probe("link_is_ours", elsewhere))

adir = cases / "adir"
adir.mkdir()
check("a directory in the way is not ours", not probe("link_is_ours", adir))

ours = cases / "ours"
ours.symlink_to(CLI)
check("our own symlink is recognised", probe("link_is_ours", ours))

dangling = cases / "dangling"
dangling.symlink_to("/gone/" + PLUGIN_ID + "/bin/" + CLI_NAME)
check("our own symlink is still recognised once the plugin folder is gone",
      probe("link_is_ours", dangling),
      "otherwise --uninstall would strand its own dangling link")

# ---- file_is_ours: only a marked regular file counts ------------------------

shipped = ROOT / "completions" / CLI_NAME
check("the shipped completion carries the ownership marker",
      MARK in shipped.read_text(),
      "without it install.sh could never recognise its own file")

check("an absent completion is not ours to delete",
      not probe("file_is_ours", cases / "no-completion"))

unmarked = cases / "unmarked"
unmarked.write_text("# somebody else's completion\ncomplete -W 'a b' utter\n")
check("an unmarked completion belonging to someone else is left alone",
      not probe("file_is_ours", unmarked))

marked = cases / "marked"
shutil.copyfile(shipped, marked)
check("a completion we installed is recognised", probe("file_is_ours", marked))

symmarked = cases / "symmarked"
symmarked.symlink_to(marked)
check("a symlink to a marked file is not treated as ours",
      not probe("file_is_ours", symmarked),
      "removing it would delete a link the user made deliberately")

# ---- and that install.sh actually routes through them -----------------------

check("install.sh guards the symlink it creates",
      '! link_is_ours "$BIN_LINK"' in SH)
check("install.sh guards the completion it installs",
      '! file_is_ours "$COMPLETION"' in SH)
check("install.sh stages the completion in an exclusive temporary file",
      'mktemp "${COMPLETION%/*}/' in SH and 'mv -f "$tmp" "$COMPLETION"' in SH)
check("install.sh no longer uses a predictable staging name",
      'install -m 0644 "$SCRIPT_DIR/completions/' not in SH,
      "a fixed $COMPLETION.new can be pre-created as a symlink or a FIFO")
check("uninstall proves ownership before removing the symlink",
      re.search(r'if link_is_ours "\$BIN_LINK"; then\s+rm -f', SH) is not None)
check("uninstall proves ownership before removing the completion",
      re.search(r'if file_is_ours "\$COMPLETION"; then\s+rm -f', SH) is not None)
check("uninstall no longer deletes on mere existence",
      '[[ -L $BIN_LINK || -f $BIN_LINK ]] && { rm -f' not in SH)

# ---- report -----------------------------------------------------------------

shutil.rmtree(SB, ignore_errors=True)
print("\n%d passed, %d failed" % (PASSED, len(FAILED)))
for f in FAILED:
    print("  FAIL  " + f)
sys.exit(1 if FAILED else 0)
