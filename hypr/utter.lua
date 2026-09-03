-- Utter keybindings.
--
-- F9 dictates words (Voxtype). F10 gives commands (Utter). Holding either key
-- records; releasing it acts. The pairing is deliberate: same hand, same
-- gesture, different verb.
--
-- install.sh rewrites the placeholder below to the absolute path of the
-- installed `utter`, so these work whether or not it is on your PATH.

o.bind("F10", "Voice command (push-to-talk)", "CLI_PATH ptt start")
o.bind("F10", "Voice command (release)", "CLI_PATH ptt stop", { release = true })
o.bind("SUPER + CTRL + V", "Voice command (toggle)", "CLI_PATH listen")
