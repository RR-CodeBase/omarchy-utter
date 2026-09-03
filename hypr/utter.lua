-- Utter keybindings.
--
-- F9 dictates words (Voxtype). F10 gives commands (Utter). Holding either key
-- records; releasing it acts. The pairing is deliberate: same hand, same
-- gesture, different verb.
--
-- CLI_PATH is rewritten by install.sh to the absolute path of the bundled
-- `utter`, so this works whether or not it is on your PATH.

o.bind("F10", "Voice command (push-to-talk)", "CLI_PATH ptt start")
o.bind("F10", "Voice command (release)", "CLI_PATH ptt stop", { release = true })
o.bind("SUPER + CTRL + V", "Voice command (toggle)", "CLI_PATH listen")
