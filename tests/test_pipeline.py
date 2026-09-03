#!/usr/bin/env python3
"""End-to-end tests for the audio path: record -> transcribe -> match -> run.

Run: python3 tests/test_pipeline.py

Speaking into a microphone is not something a test can do, so the transcription
leg is proved with a real speech recording (the whisper.cpp JFK sample) matched
against a scratch grammar built from words that recording actually contains.
Every link in the chain is the real one: real audio, real whisper, real
matching, a real process launched.

Set UTTER_VOXTYPE if voxtype is not on PATH. Tests that need a missing
dependency are skipped, not failed.
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# A real recording of one complete utterance, so the matcher is exercised the
# way it will be in use: whole-utterance, not a phrase buried in a sentence.
SAMPLE = Path(os.environ.get("UTTER_SAMPLE_WAV") or (ROOT / "tests/fixtures/speech-sample.wav"))

PASSED, SKIPPED, FAILED = 0, [], []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print(f"[PASS] {name}")
    else:
        FAILED.append(f"{name}{(': ' + detail) if detail else ''}")
        print(f"[FAIL] {name}{(' - ' + detail) if detail else ''}")


def skip(name, why):
    SKIPPED.append(f"{name} ({why})")
    print(f"[SKIP] {name} - {why}")


def load_utter(config_home: Path, state_home: Path):
    """Import bin/utter with its config and state pointed at a scratch dir.

    XDG_RUNTIME_DIR is deliberately left alone: it is how PipeWire finds its
    socket, and repointing it makes pw-record fail with nothing written.
    """
    os.environ["XDG_CONFIG_HOME"] = str(config_home)
    os.environ["XDG_STATE_HOME"] = str(state_home)
    os.environ["UTTER_RUNTIME_DIR"] = str(state_home / "run")
    loader = importlib.machinery.SourceFileLoader("utter_e2e", str(ROOT / "bin" / "utter"))
    spec = importlib.util.spec_from_loader("utter_e2e", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


tmp = Path(tempfile.mkdtemp(prefix="utter-e2e-"))
utter = load_utter(tmp / "config", tmp / "state")
proof = tmp / "proof"

# A grammar whose phrases are words the JFK sample really contains, so a real
# recording can drive the real matcher.
scratch = {
    "version": 1,
    "wakeWords": [],
    "slots": {"who": {"country": ["country"], "americans": ["americans"]}},
    "commands": [
        {
            "id": "e2e.touch",
            "group": "Test",
            "say": ["ask not what your {who} can do for you"],
            "note": "the exact words in tests/fixtures/speech-sample.wav",
            "run": f"touch {proof}",
            "label": "Proof of pipeline",
        },
        {
            "id": "e2e.destructive",
            "group": "Test",
            "confirm": True,
            "say": ["and so my fellow americans"],
            "run": f"touch {tmp / 'must-not-exist'}",
            "label": "Needs confirming",
        },
    ],
}
utter.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
utter.COMMANDS_FILE.write_text(json.dumps(scratch))
utter.save_settings(dict(utter.DEFAULT_SETTINGS, osd=False, notify=False))

# ---- 1. recording produces a WAV whisper can actually read -----------------

if not shutil.which("pw-record"):
    skip("pw-record captures 16 kHz mono", "pw-record not installed")
else:
    utter.record_start(4)
    time.sleep(1.2)
    wav = utter.record_stop()
    if wav is None or not wav.exists():
        check("pw-record captures 16 kHz mono", False, "no file produced")
    else:
        try:
            with wave.open(str(wav)) as w:
                fmt = (w.getframerate(), w.getnchannels(), w.getsampwidth())
                frames = w.getnframes()
            check("recording is a readable WAV", True)
            check("recording is 16 kHz mono 16-bit", fmt == (16000, 1, 2), str(fmt))
            check("recording contains audio", frames > 8000, f"{frames} frames")
        except Exception as exc:
            # A truncated header here means SIGINT did not let pw-record finish.
            check("recording is a readable WAV", False, str(exc))

# ---- 2. transcription of real speech ---------------------------------------

binary = utter.find_voxtype()
sample = SAMPLE if SAMPLE and SAMPLE.exists() else None

if not binary:
    skip("voxtype transcribes real speech", "voxtype not found (set UTTER_VOXTYPE)")
elif not sample:
    skip("voxtype transcribes real speech", "no sample (set UTTER_SAMPLE_WAV)")
else:
    text = utter.transcribe(sample)
    check("voxtype transcribes real speech", "country can do for you" in text.lower(), repr(text))

    # ---- 3. the full chain: speech -> match -> a process actually runs ------

    hit, cleaned = utter.Matcher(utter.grammar()).match(text)
    check("real transcript matches the grammar",
          hit is not None and hit.cmd["id"] == "e2e.touch",
          f"cleaned={cleaned!r} hit={hit.cmd['id'] if hit else None}")

    # The real entry point, so state and history are written as they are in use.
    rc = utter.interpret(text, quiet=True)
    check("interpret() reports success", rc == 0, f"rc={rc}")
    for _ in range(60):
        if proof.exists():
            break
        time.sleep(0.05)
    check("command really ran (side effect on disk)", proof.exists())

    # ---- 4. state the widget reads reflects what happened -------------------

    state = json.loads(utter.STATE_FILE.read_text()) if utter.STATE_FILE.exists() else {}
    check("state file records the result", state.get("state") == "ok", str(state)[:140])
    check("state file records what was heard", "country" in (state.get("heard") or "").lower(),
          str(state.get("heard")))
    check("history was appended", utter.HISTORY_FILE.exists()
          and "e2e.touch" in utter.HISTORY_FILE.read_text())

# ---- 5. destructive commands do not run on the first hearing ---------------

hit, _ = utter.Matcher(utter.grammar()).match("and so my fellow americans")
if hit is None:
    check("confirm-gated command matches", False, "no match")
else:
    ok, detail = utter.execute(hit)
    check("confirm-gated command does not run first time",
          ok is False and detail == "confirm", f"{ok} {detail}")
    check("...and nothing touched the disk", not (tmp / "must-not-exist").exists())
    ok2, _ = utter.execute(hit)          # said again, inside the window
    check("...but runs when repeated", ok2 is True)

# ---- 6. an unmatched utterance runs nothing --------------------------------

marker = tmp / "should-never-appear"
scratch["commands"].append({
    "id": "e2e.never", "group": "Test",
    "say": ["lunch tomorrow"], "run": f"touch {marker}", "label": "Never",
})
utter.COMMANDS_FILE.write_text(json.dumps(scratch))
rc = utter.interpret("i was thinking about lunch tomorrow", quiet=True)
check("unmatched speech returns 'unheard'", rc == 1, f"rc={rc}")
time.sleep(0.4)
check("unmatched speech runs nothing", not marker.exists())

# ---- report ----------------------------------------------------------------

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{PASSED} passed, {len(FAILED)} failed, {len(SKIPPED)} skipped")
for s in SKIPPED:
    print(f"  SKIP  {s}")
for f in FAILED:
    print(f"  FAIL  {f}")
sys.exit(1 if FAILED else 0)
