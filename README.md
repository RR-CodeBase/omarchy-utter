# Utter

**Say it, and the window manager does it.**

Omarchy already turns your voice into text. Utter turns it into *actions*. Hold
`F10`, say "focus left", "workspace three", "throw this to two", "lock the
screen" — and it happens.

Everything runs on your machine. Audio is recorded with `pw-record`,
transcribed by [Voxtype](https://voxtype.io) (whisper.cpp), matched against a
grammar you can edit, and then discarded. No network, no wake word, no
always-on microphone: the mic opens when you hold the key and closes when you
let go.

## Why it isn't dictation

Dictation types what you said into the focused window. Utter never types
anything. An utterance either matches a command in the grammar and runs it, or
it is thrown away. That is the whole safety model, and it means a misheard
sentence can't end up in your code.

`F9` dictates words. `F10` gives commands. Same hand, same gesture, different verb.

## Install

Voice commands need Voxtype, which Omarchy installs for you:

```bash
omarchy voxtype install     # once, if you haven't already
```

Then:

```bash
git clone https://github.com/RR-CodeBase/omarchy-utter
cd omarchy-utter
./install.sh
```

That registers the plugin, places the bar widget, and adds the keybindings.
Re-running it is safe. `./install.sh --uninstall` takes it all back out.

## Using it

| | |
|---|---|
| **Hold `F10`** | record; release to run |
| **`SUPER + CTRL + V`** | toggle recording instead of holding |
| **Click the bar icon** | status, recent utterances, on/off |
| **Middle-click the icon** | turn voice commands on or off |

The bar icon shows what is happening: `󰗋` ready, `󰍬` listening, `󰔟` thinking,
`󰘥` didn't catch that, `󰍭` off.

## What you can say

```bash
utter commands          # the full list, grouped
```

37 commands out of the box, covering windows, workspaces, apps, sound,
display, focus modes, capture and session. A few of them:

| Say | Runs |
|---|---|
| "focus left" / "go right" | `hl.dsp.focus({ direction = "l" })` |
| "workspace three" | `hl.dsp.focus({ workspace = "3" })` |
| "throw this to two" | `hl.dsp.window.move({ workspace = "2" })` |
| "close window" | `hl.dsp.window.close()` |
| "open the terminal" | `omarchy launch terminal` |
| "take a screenshot" | `omarchy capture screenshot region` |
| "do not disturb" | `omarchy toggle notification silencing` |
| "lock the screen" | `omarchy system lock` |

Anything destructive — reboot, shut down, sleep — has to be said twice within
eight seconds before it runs.

## Editing the grammar

The grammar lives at `~/.config/omarchy/utter/commands.json` and is yours.
Add a command by adding an entry:

```json
{
  "id": "notes.open",
  "group": "Apps",
  "say": ["open my notes", "show my notes", "notes"],
  "run": "omarchy launch or focus obsidian",
  "label": "Open notes"
}
```

Slots let one entry cover many phrasings. `{dir}`, `{num}` and `{app}` ship by
default, and you can add your own under `slots`:

```json
{
  "id": "focus.move",
  "say": ["focus {dir}", "go {dir}"],
  "run": "hyprctl dispatch movefocus {dir}",
  "label": "Focus {dir}"
}
```

A slot maps what you *say* to what gets *run*: `"l": ["left"]` means saying
"left" substitutes `l`. Only the canonical value ever reaches the command line,
so what you say can never inject arguments.

Hyprland commands go through its Lua dispatcher API (`hl.dsp.…`), not the
older `hyprctl dispatch workspace 3` form — that one is accepted by the CLI
and rejected by the compositor, so it looks like it worked. `utter doctor`
proves the calling convention against the running compositor and refuses to
let the legacy form back into the grammar.

After editing, `utter doctor` re-checks the whole file.

### When the shipped grammar changes

The grammar carries a `version`. When Utter ships a newer one, your file is
replaced and the old one kept beside it as `commands.v<n>.json`, so anything
you wrote is recoverable. Copy your own commands across and they survive the
next upgrade too.

## How the matching works

Two passes. First an exact match of the normalized utterance against every
phrase in the grammar — punctuation, capitalization, filler words ("um",
"please") and wake words ("omarchy", "computer") are stripped first. That
handles most clean transcriptions in microseconds.

If nothing matches exactly, a fuzzy pass scores the utterance against every
phrase and accepts the best one above `threshold` (0.80 by default). This is
what rescues "focus lefd" and "next workspase". Below the threshold you get
"Didn't catch that" and nothing runs — including for ordinary conversation
picked up by a hot mic, which the test suite pins down explicitly.

Whisper's habit of writing digits, and its homophones, are handled in the
grammar itself: `"2": ["two", "to", "too", "2"]`.

## Commands

```
utter ptt start|stop     push-to-talk, for keybindings
utter listen             toggle recording
utter say "focus left"   interpret typed text as if spoken
utter match "focus left" match without running (add --threshold)
utter commands [--json]  list the grammar
utter status [--json]    what the widget reads
utter history            recent utterances and what they matched
utter enable|disable|toggle
utter doctor             check the whole install
utter selftest           record 3s, transcribe, match
```

`utter say` is useful beyond testing: bind it to a key and you have a text
command palette that shares the grammar.

## Settings

`~/.config/omarchy/utter/settings.json`

| Key | Default | |
|---|---|---|
| `enabled` | `true` | master switch |
| `threshold` | `0.80` | fuzzy match floor; raise it if commands misfire |
| `maxSeconds` | `8` | recording safety limit |
| `osd` | `true` | show the Omarchy OSD on each result |
| `notify` | `false` | also send a notification |
| `stripWakeWords` | `true` | ignore a leading "omarchy" / "computer" |
| `voxtype` | `""` | path to a specific voxtype binary |
| `model` | `""` | override the whisper model |

## Requirements

- Omarchy Quattro
- `pipewire` (`pw-record`)
- Voxtype and a whisper model — `omarchy voxtype install`
- Python 3.11+ (standard library only)

## Tests

```bash
python3 tests/test_grammar.py
```

175 assertions covering slot canonicalization, homophones, transcription noise,
fuzzy tolerance, argument-injection safety, a corpus of ordinary speech that
must never match a command, and the phrasings real use turned up. Plus
`tests/test_pipeline.py`, which drives real audio through whisper into the
matcher and out to a process.

## Licence

MIT. See `LICENSE`, and `NOTICE` for what this builds on.
