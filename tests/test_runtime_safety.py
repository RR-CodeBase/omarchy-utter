#!/usr/bin/env python3
"""Tests for the private runtime directory and the recorder pid.

Run: python3 tests/test_runtime_safety.py

Desktop Voice Control keeps the recording, the pid file and the pending-confirmation file under
predictable names, so their safety rests on two things: the directory being one
only this user can reach, and the pid never being handed to os.kill() unless
the process wearing it is provably the recorder we started. Everything here
attacks one of those two, using the real code paths rather than mocks: real
symlinks planted at the names it is about to write, real directory modes,
real pids read back out of /proc.
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UID = os.getuid()

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


def load(**env):
    """Import bin/utter fresh under a given environment.

    RUNTIME_DIR is decided at import time, so a test that wants a different one
    has to re-import rather than reassign - reassigning would leave the derived
    PID_FILE, WAV_FILE and friends pointing at the old directory.
    """
    saved = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        loader = importlib.machinery.SourceFileLoader("utter_rt", str(ROOT / "bin/utter"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def refuses(fn, *a):
    try:
        fn(*a)
    except RuntimeError:
        return True
    return False


TMP = Path(tempfile.mkdtemp(prefix="utter-safety-"))

# ---- where the runtime directory lands --------------------------------------

m = load(UTTER_RUNTIME_DIR=None, XDG_RUNTIME_DIR=None)
check("the /tmp fallback is not a name every account can guess",
      m.RUNTIME_DIR != Path("/tmp/utter"), str(m.RUNTIME_DIR))
check("the /tmp fallback carries the uid",
      m.RUNTIME_DIR == Path(f"/tmp/utter-{UID}"), str(m.RUNTIME_DIR))

m = load(UTTER_RUNTIME_DIR=None, XDG_RUNTIME_DIR=f"/run/user/{UID}")
check("XDG_RUNTIME_DIR is used when the session provides one",
      m.RUNTIME_DIR == Path(f"/run/user/{UID}/utter"), str(m.RUNTIME_DIR))

# ---- what ensure_runtime_dir() will and will not accept ---------------------

fresh = TMP / "fresh"
m = load(UTTER_RUNTIME_DIR=str(fresh))
m.ensure_runtime_dir()
check("a new runtime directory is created 0700",
      stat.S_IMODE(os.lstat(fresh).st_mode) == 0o700,
      oct(stat.S_IMODE(os.lstat(fresh).st_mode)))

loose = TMP / "loose"
loose.mkdir()
os.chmod(loose, 0o777)
m = load(UTTER_RUNTIME_DIR=str(loose))
m.ensure_runtime_dir()
check("a world-writable runtime directory is tightened to 0700",
      stat.S_IMODE(os.lstat(loose).st_mode) == 0o700,
      oct(stat.S_IMODE(os.lstat(loose).st_mode)))

elsewhere = TMP / "elsewhere"
elsewhere.mkdir()
linked = TMP / "linked"
linked.symlink_to(elsewhere)
m = load(UTTER_RUNTIME_DIR=str(linked))
check("a symlinked runtime directory is refused", refuses(m.ensure_runtime_dir))

plain = TMP / "plainfile"
plain.write_text("not a directory")
m = load(UTTER_RUNTIME_DIR=str(plain))
check("a regular file where the runtime directory should be is refused",
      refuses(m.ensure_runtime_dir))

foreign = TMP / "foreign"
foreign.mkdir(mode=0o700)
m = load(UTTER_RUNTIME_DIR=str(foreign))
real_getuid = os.getuid
os.getuid = lambda: UID + 4242  # pretend the directory belongs to someone else
try:
    check("a runtime directory owned by another user is refused",
          refuses(m.ensure_runtime_dir))
finally:
    os.getuid = real_getuid

# ---- writing into it --------------------------------------------------------

work = TMP / "work"
m = load(UTTER_RUNTIME_DIR=str(work))
m.ensure_runtime_dir()

made = work / "made"
with m.open_private(made, "w") as fh:
    fh.write("x")
check("open_private creates 0600 files",
      stat.S_IMODE(os.lstat(made).st_mode) == 0o600,
      oct(stat.S_IMODE(os.lstat(made).st_mode)))

victim = TMP / "victim"
victim.write_text("precious")
planted = work / "planted"
planted.symlink_to(victim)
followed = True
try:
    with m.open_private(planted, "w") as fh:
        fh.write("clobbered")
except OSError:
    followed = False
check("open_private will not write through a planted symlink", not followed)
check("the symlink's target is left untouched", victim.read_text() == "precious")

victim2 = TMP / "victim2"
victim2.write_text("precious")
target = work / "state.json"
(work / "state.json.tmp").symlink_to(victim2)
m.atomic_write(target, '{"ok":true}')
check("atomic_write will not write through a symlink planted at its .tmp name",
      victim2.read_text() == "precious")
check("atomic_write still writes the real file",
      json.loads(target.read_text()) == {"ok": True})
check("atomic_write leaves the result 0600",
      stat.S_IMODE(os.lstat(target).st_mode) == 0o600,
      oct(stat.S_IMODE(os.lstat(target).st_mode)))

# ---- wiping the recording ---------------------------------------------------

audio = work / "audio"
audio.write_bytes(b"A" * 4096)
hard = work / "audio.hardlink"
os.link(audio, hard)
m.wipe(audio)
check("wipe overwrites the audio before unlinking it",
      hard.read_bytes() == b"\0" * 4096)
check("wipe unlinks the file it overwrote", not audio.exists())
hard.unlink()

victim3 = TMP / "victim3"
victim3.write_text("precious")
symwav = work / "sym.wav"
symwav.symlink_to(victim3)
m.wipe(symwav)
check("wipe removes a planted symlink rather than its target",
      not os.path.lexists(symwav) and victim3.read_text() == "precious")

# ---- which pids are allowed to be signalled ---------------------------------

for bad in (-1, 0, 1):
    m.atomic_write(m.PID_FILE, json.dumps({"pid": bad, "startTime": "1", "comm": "x"}))
    check(f"a pid of {bad} is never signalled", m.recording_pid() is None)
    check(f"the pid file holding {bad} is cleared", not m.PID_FILE.exists())

m.atomic_write(m.PID_FILE, str(os.getpid()))
check("a bare-integer pid file from 0.1.0 is not trusted", m.recording_pid() is None)

m.atomic_write(m.PID_FILE, json.dumps({"pid": "not-a-number", "startTime": "1"}))
check("a non-numeric pid is not trusted", m.recording_pid() is None)

me = os.getpid()
ident = m._proc_ident(me)
check("a live process reports a start time", ident is not None and ident[0].isdigit(),
      repr(ident))

m.atomic_write(m.PID_FILE, json.dumps(
    {"pid": me, "startTime": "999999999999", "comm": "pw-record"}))
check("a recycled pid is rejected when the start time does not match",
      m.recording_pid() is None)

m.atomic_write(m.PID_FILE, json.dumps(
    {"pid": me, "startTime": ident[0], "comm": ident[1]}))
check("a live pid carrying the recorded start time is accepted",
      m.recording_pid() == me, str(m.recording_pid()))

gone = subprocess.Popen(["true"])
gone.wait()
m.atomic_write(m.PID_FILE, json.dumps(
    {"pid": gone.pid, "startTime": "1", "comm": "true"}))
check("a pid that has since exited is rejected", m.recording_pid() is None)
m.clear_pid()

# ---- the real recorder, through the path the keybinding uses ----------------

if shutil.which("pw-record"):
    live = load(UTTER_RUNTIME_DIR=str(TMP / "live"))
    try:
        started = live.record_start(5)
        check("record_start starts a recorder", started)
        check("the pid file it wrote identifies a live process",
              live.recording_pid() is not None)
        check("the recording is created 0600, not at the default umask",
              not (stat.S_IMODE(os.lstat(live.WAV_FILE).st_mode) & 0o077),
              oct(stat.S_IMODE(os.lstat(live.WAV_FILE).st_mode)))
        time.sleep(1.0)
        wav = live.record_stop()
        check("record_stop returns the recording", wav is not None and wav.exists())
        check("record_stop clears the pid file", not live.PID_FILE.exists())
        if wav:
            live.wipe(wav)
    except RuntimeError as exc:
        skip("live recorder round trip", str(exc))
else:
    skip("live recorder round trip", "pw-record not installed")

# ---- report -----------------------------------------------------------------

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{PASSED} passed, {len(FAILED)} failed, {len(SKIPPED)} skipped")
for s in SKIPPED:
    print(f"  SKIP  {s}")
for f in FAILED:
    print(f"  FAIL  {f}")
sys.exit(1 if FAILED else 0)
