#!/bin/bash
# Install Utter into Omarchy: register the plugin, place the bar widget, and
# wire up the push-to-talk keybindings.
#
# Safe to re-run. Every step checks for its own result first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ID="io.github.rr-codebase.utter"
PLUGINS_DIR="$HOME/.config/omarchy/plugins"
BINDINGS="$HOME/.config/hypr/bindings.lua"
BEGIN_MARK="-- >>> utter (managed) >>>"
END_MARK="-- <<< utter (managed) <<<"
BIN_LINK="$HOME/.local/bin/utter"
COMPLETION="$HOME/.local/share/bash-completion/completions/utter"

WITH_BINDINGS=1
SECTION="right"

usage() {
  cat <<USAGE
Usage: ./install.sh [options]

  --no-bindings      Skip the Hyprland keybindings
  --section <where>  Bar section for the widget (left|center|right) [right]
  --uninstall        Remove the keybindings and the plugin
  -h, --help         This message
USAGE
}

say()  { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

remove_bindings() {
  [[ -f $BINDINGS ]] || return 0
  grep -qF -e "$BEGIN_MARK" "$BINDINGS" || return 0
  # Cut the managed block, leaving anything the user wrote around it alone.
  awk -v b="$BEGIN_MARK" -v e="$END_MARK" '
    index($0, b) { skip = 1 }
    !skip { print }
    index($0, e) { skip = 0 }
  ' "$BINDINGS" > "$BINDINGS.utter.tmp"
  mv "$BINDINGS.utter.tmp" "$BINDINGS"
}

uninstall() {
  echo
  echo "Removing Utter"
  remove_bindings && ok "keybindings removed"
  [[ -L $BIN_LINK || -f $BIN_LINK ]] && { rm -f "$BIN_LINK"; ok "removed ${BIN_LINK/#$HOME/\~}"; }
  [[ -f $COMPLETION ]] && { rm -f "$COMPLETION"; ok "removed shell completion"; }
  if [[ -d "$PLUGINS_DIR/$PLUGIN_ID" ]]; then
    omarchy plugin remove "$PLUGIN_ID" --yes >/dev/null 2>&1 || true
    ok "plugin removed"
  fi
  hyprctl reload >/dev/null 2>&1 || true
  echo
  say "Your grammar is still at ~/.config/omarchy/utter/commands.json"
  echo
  exit 0
}

while (($#)); do
  case "$1" in
    --no-bindings) WITH_BINDINGS=0; shift ;;
    --section) SECTION="${2:-right}"; shift 2 ;;
    --uninstall) uninstall ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

echo
echo "Installing Utter"
echo

# ---- prerequisites ---------------------------------------------------------

command -v omarchy >/dev/null || die "Omarchy not found. This plugin needs Omarchy Quattro."
command -v hyprctl >/dev/null || warn "hyprctl not found - window commands will not work"
command -v python3 >/dev/null || die "python3 not found"

if command -v pw-record >/dev/null; then
  ok "pw-record found"
else
  warn "pw-record not found - install pipewire-audio to record"
fi

if command -v voxtype >/dev/null; then
  ok "Voxtype found ($(command -v voxtype))"
elif ls /usr/lib/voxtype/voxtype-* >/dev/null 2>&1; then
  ok "Voxtype found in /usr/lib/voxtype"
else
  warn "Voxtype is not installed - run: omarchy voxtype install"
  warn "Utter will match typed text until then (utter say \"focus left\")"
fi

if compgen -G "$HOME/.local/share/voxtype/models/*.bin" >/dev/null; then
  ok "whisper model present"
else
  warn "no whisper model - run: omarchy voxtype install"
fi

# ---- plugin ----------------------------------------------------------------

if [[ -d "$PLUGINS_DIR/$PLUGIN_ID" ]]; then
  ok "plugin already registered"
else
  omarchy plugin validate "$SCRIPT_DIR" >/dev/null || die "manifest failed validation"
  # plugin add clones, so the source needs at least one commit.
  if ! git -C "$SCRIPT_DIR" rev-parse HEAD >/dev/null 2>&1; then
    die "commit this repo first (omarchy plugin add clones it)"
  fi
  omarchy plugin add "$SCRIPT_DIR" --enable --yes >/dev/null || die "omarchy plugin add failed"
  ok "plugin added and enabled"
fi

if omarchy bar put "$PLUGIN_ID" "$SECTION" >/dev/null 2>&1; then
  ok "widget placed in the $SECTION section"
else
  say "widget already placed (or place it from the bar's settings)"
fi

# ---- keybindings -----------------------------------------------------------

# The installed clone is the canonical CLI; fall back to this checkout only if
# the plugin somehow is not registered.
CLI="$PLUGINS_DIR/$PLUGIN_ID/bin/utter"
[[ -x $CLI ]] || CLI="$SCRIPT_DIR/bin/utter"

if ((WITH_BINDINGS)); then
  mkdir -p "$(dirname "$BINDINGS")"
  touch "$BINDINGS"
  remove_bindings
  {
    echo ""
    echo "$BEGIN_MARK"
    sed "s|CLI_PATH|$CLI|g" "$SCRIPT_DIR/hypr/utter.lua"
    echo "$END_MARK"
  } >> "$BINDINGS"
  ok "keybindings written to ${BINDINGS/#$HOME/\~}"
  hyprctl reload >/dev/null 2>&1 && ok "hyprland reloaded" || warn "run: hyprctl reload"
fi

# ---- CLI on PATH -----------------------------------------------------------

# The README documents `utter ...` as a bare command, so put it on PATH. The
# script itself stays in the plugin; this is only a link to it.
mkdir -p "$(dirname "$BIN_LINK")"
ln -sfn "$CLI" "$BIN_LINK"
ok "utter linked into ${BIN_LINK/#$HOME/\~}"
# Only advertise the short form if it will actually resolve.
PRETTY_CLI="$CLI"
case ":$PATH:" in
  *":${BIN_LINK%/*}:"*) PRETTY_CLI="utter" ;;
  *) warn "${BIN_LINK%/*} is not on your PATH - add it to use \`utter\` directly" ;;
esac

if [[ -f $SCRIPT_DIR/completions/utter ]]; then
  mkdir -p "$(dirname "$COMPLETION")"
  install -m 0644 "$SCRIPT_DIR/completions/utter" "$COMPLETION"
  ok "shell completion installed"
fi

# ---- seed config and report -------------------------------------------------

"$CLI" status >/dev/null 2>&1 || true
ok "grammar seeded at ~/.config/omarchy/utter/commands.json"

echo
"$CLI" doctor || true
echo
echo "  Hold F10 and say \"focus left\"."
echo "  Everything you can say:  $PRETTY_CLI commands"
echo
