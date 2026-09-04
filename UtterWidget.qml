import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar icon plus a popup panel, shaped like Omarchy's own audio and network
// panels: one BarIconButton for the bar, a KeyboardPanel anchored to it.
//
// The widget is a window onto the CLI, never a second source of truth. Every
// piece of state is read from the files `utter` writes, so the panel, the
// keybinding and anything you run in a terminal always agree. Actions go
// through the bundled CLI by absolute path, so this works whether or not
// `utter` is on PATH.
//
// The icon deliberately does not reuse Omarchy's dictation microphone: a
// command that runs and a word that gets typed are different enough that
// they should not look the same in the bar.
Panel {
  id: root
  moduleName: "io.github.rr-codebase.utter"
  ipcTarget: "io.github.rr-codebase.utter"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // barForeground contrasts with the WALLPAPER, which is right for the bar
  // icon and wrong for anything inside the popup sitting on Color.popups.
  readonly property color panelText: Color.popups.text

  readonly property string cli:
    Qt.resolvedUrl("bin/utter").toString().replace(/^file:\/\//, "")

  property bool enabled: true
  property string state: "idle"      // idle listening thinking ok unheard confirm error
  property string heard: ""
  property string action: ""
  property string lastError: ""
  property real score: 0
  property string pttKey: ""
  property var recent: []
  property var examples: []
  property int commandCount: 0

  readonly property bool busy: state === "listening" || state === "thinking"

  readonly property string glyph: {
    if (!enabled) return "󰍭"
    if (state === "listening") return "󰍬"
    if (state === "thinking") return "󰔟"
    if (state === "unheard" || state === "confirm") return "󰘥"
    return "󰗋"
  }

  readonly property string statusLine: {
    if (!enabled) return "Voice commands off"
    if (state === "listening") return "Listening…"
    if (state === "thinking") return "Thinking…"
    if (state === "confirm") return "Say it again to confirm"
    if (state === "unheard") return "Didn't catch that"
    if (state === "error") return lastError !== "" ? lastError : "Something went wrong"
    if (state === "ok" && action !== "") return action
    return "Ready"
  }

  function run(args) {
    if (root.bar) root.bar.run("'" + root.cli.replace(/'/g, "'\\''") + "' " + args)
  }

  function shell(cmd) {
    if (root.bar) root.bar.run(cmd)
  }

  // ---- state written by the CLI -------------------------------------------

  FileView {
    id: stateFile
    path: Quickshell.env("HOME") + "/.local/state/omarchy/utter.json"
    watchChanges: true
    printErrors: false
    onLoaded: {
      try {
        var s = JSON.parse(text() || "{}") || {}
        root.enabled = s.enabled !== false
        root.state = typeof s.state === "string" ? s.state : "idle"
        root.heard = typeof s.heard === "string" ? s.heard : ""
        root.action = typeof s.action === "string" ? s.action : ""
        root.lastError = typeof s.error === "string" ? s.error : ""
        var sc = Number(s.score)
        root.score = isFinite(sc) ? sc : 0
        if (typeof s.pttKey === "string" && s.pttKey !== "") root.pttKey = s.pttKey
      } catch (error) {
        // A half-written file is transient; keep the last good state.
      }
    }
    onFileChanged: reload()
  }

  FileView {
    id: historyFile
    path: Quickshell.env("HOME") + "/.local/state/omarchy/utter-history.jsonl"
    watchChanges: true
    printErrors: false
    onLoaded: {
      try {
        var lines = (text() || "").split("\n").filter(function (l) { return l.trim() !== "" })
        var out = []
        for (var i = lines.length - 1; i >= 0 && out.length < 3; i--) {
          var e = JSON.parse(lines[i])
          out.push({
            heard: typeof e.heard === "string" ? e.heard : "",
            label: typeof e.label === "string" ? e.label : "no match"
          })
        }
        root.recent = out
      } catch (error) {
        // Ignore a torn append; the next write brings us back.
      }
    }
    onFileChanged: reload()
  }

  FileView {
    id: grammarFile
    path: Quickshell.env("HOME") + "/.config/omarchy/utter/commands.json"
    watchChanges: true
    printErrors: false
    onLoaded: {
      try {
        var g = JSON.parse(text() || "{}") || {}
        var cmds = g.commands || []
        root.commandCount = cmds.length
        // A handful of real phrases from the grammar beats an invented
        // example: what is shown here is exactly what will work.
        var picks = []
        var wanted = ["focus.move", "workspace.go", "window.close", "app.launch", "capture.region"]
        for (var w = 0; w < wanted.length; w++) {
          for (var c = 0; c < cmds.length; c++) {
            if (cmds[c].id === wanted[w] && (cmds[c].say || []).length > 0) {
              picks.push(cmds[c].say[0].replace("{dir}", "left").replace("{num}", "3").replace("{app}", "terminal"))
              break
            }
          }
        }
        root.examples = picks
      } catch (error) {
        // Keep whatever we last parsed.
      }
    }
    onFileChanged: reload()
  }

  // ---- bar icon ------------------------------------------------------------

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.glyph
    active: root.enabled && (root.busy || root.state === "ok")
    activeColor: root.state === "listening" ? Color.accent : Color.popups.text
    tooltipText: root.statusLine
      + (root.enabled && root.pttKey !== "" ? "\nHold " + root.pttKey + " and speak" : "")
      + "\nClick for voice commands"
    opacity: pulse.running ? pulseOpacity : 1.0

    property real pulseOpacity: 1.0

    // Fixed endpoints only: a NaN target here takes the whole shell down in
    // the scene graph renderer, with no QML warning to explain it.
    SequentialAnimation {
      id: pulse
      running: root.busy
      loops: Animation.Infinite
      alwaysRunToEnd: true
      NumberAnimation { target: button; property: "pulseOpacity"; from: 1.0; to: 0.45; duration: 600; easing.type: Easing.InOutQuad }
      NumberAnimation { target: button; property: "pulseOpacity"; from: 0.45; to: 1.0; duration: 600; easing.type: Easing.InOutQuad }
      onStopped: button.pulseOpacity = 1.0
    }

    onPressed: function (b) {
      if (b === Qt.MiddleButton) root.run("toggle")
      else root.toggle()
    }
  }

  // ---- panel ---------------------------------------------------------------

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(700))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function (direction) { root.switchPanel(direction) }

      Column {
        id: panelColumn
        width: parent.width
        spacing: Style.spacing.controlGap

        PanelSectionHeader {
          text: root.statusLine
          foreground: root.panelText
          fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
        }

        // How to use it, named after the key Hyprland is really bound to
        // rather than the one the installer wrote, so a rebind follows.
        Row {
          visible: root.enabled && root.pttKey !== ""
          width: panelColumn.width
          spacing: Style.space(8)

          Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            radius: Style.space(3)
            color: "transparent"
            border.width: Math.max(1, Style.space(1))
            border.color: root.panelText
            opacity: 0.85
            implicitWidth: keyLabel.implicitWidth + Style.space(12)
            implicitHeight: keyLabel.implicitHeight + Style.space(5)

            Text {
              id: keyLabel
              anchors.centerIn: parent
              text: root.pttKey
              textFormat: Text.PlainText
              color: root.panelText
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
              font.bold: true
            }
          }

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.busy ? "keep holding, then release" : "hold and speak"
            textFormat: Text.PlainText
            color: root.panelText
            opacity: 0.75
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.bodySmall
          }
        }

        // What was actually heard, verbatim. When a command misfires this is
        // the only thing that explains why, so it is never hidden.
        Text {
          visible: root.heard !== ""
          width: panelColumn.width
          text: "“" + root.heard + "”"
          textFormat: Text.PlainText
          color: root.panelText
          opacity: 0.75
          wrapMode: Text.WordWrap
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.body
          font.italic: true
        }

        PanelSeparator {
          width: panelColumn.width
          foreground: root.panelText
        }

        Item {
          width: panelColumn.width
          height: Style.spacing.controlHeight

          Text {
            id: enableIcon
            text: root.enabled ? "󰗋" : "󰍭"
            textFormat: Text.PlainText
            color: root.enabled ? Color.accent : root.panelText
            opacity: root.enabled ? 1.0 : 0.7
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.icon
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
          }

          Text {
            text: "Voice commands"
            textFormat: Text.PlainText
            color: root.panelText
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body
            anchors.left: enableIcon.right
            anchors.leftMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
          }

          ToggleSwitch {
            checked: root.enabled
            foreground: root.panelText
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            onToggled: root.run("toggle")
          }
        }

        PanelSeparator {
          width: panelColumn.width
          foreground: root.panelText
        }

        PanelSectionHeader {
          visible: root.recent.length > 0
          text: "Recent"
          foreground: root.panelText
          fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
        }

        Repeater {
          model: root.recent

          Item {
            required property var modelData
            width: panelColumn.width
            height: Style.spacing.controlHeight

            Text {
              width: parent.width * 0.52
              text: modelData.heard
              textFormat: Text.PlainText
              elide: Text.ElideRight
              color: root.panelText
              opacity: 0.7
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              width: parent.width * 0.44
              text: modelData.label
              textFormat: Text.PlainText
              elide: Text.ElideRight
              horizontalAlignment: Text.AlignRight
              color: root.panelText
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }

        PanelSeparator {
          visible: root.recent.length > 0
          width: panelColumn.width
          foreground: root.panelText
        }

        PanelSectionHeader {
          text: "Try saying"
          foreground: root.panelText
          fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
        }

        Repeater {
          model: root.examples

          Text {
            required property var modelData
            width: panelColumn.width
            text: "“" + modelData + "”"
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: root.panelText
            opacity: 0.8
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.bodySmall
          }
        }

        PanelSeparator {
          width: panelColumn.width
          foreground: root.panelText
        }

        Row {
          width: panelColumn.width
          spacing: Style.spacing.sm

          PanelActionButton {
            iconText: "󰘥"
            tooltipText: "All " + root.commandCount + " commands"
            foreground: root.panelText
            fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
            onClicked: {
              root.close()
              root.shell("omarchy-launch-floating-terminal-with-presentation '"
                + root.cli.replace(/'/g, "'\\''") + "' commands")
            }
          }

          PanelActionButton {
            iconText: "󰏫"
            tooltipText: "Edit the grammar"
            foreground: root.panelText
            fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
            onClicked: {
              root.close()
              root.shell("omarchy-launch-editor "
                + Quickshell.env("HOME") + "/.config/omarchy/utter/commands.json")
            }
          }

          PanelActionButton {
            iconText: "󰄬"
            tooltipText: "Check the install"
            foreground: root.panelText
            fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
            onClicked: {
              root.close()
              root.shell("omarchy-launch-floating-terminal-with-presentation '"
                + root.cli.replace(/'/g, "'\\''") + "' doctor")
            }
          }
        }
      }
    }
  }
}
