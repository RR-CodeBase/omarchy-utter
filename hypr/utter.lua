-- Utter keybindings.
--
-- F9 dictates words (Voxtype). F10 gives commands (Utter). Hold the key while
-- you speak, release to act. The pairing is deliberate: same hand, same
-- gesture, different verb.
--
-- Push-to-talk only, on purpose. A toggle needs a second free chord, and the
-- obvious ones are taken -- SUPER + CTRL + V is Omarchy's clipboard manager.
-- If you want one, bind `utter listen` to a chord you know is free.
--
-- install.sh rewrites the placeholder below to the absolute path of the
-- installed `utter`, so these work whether or not it is on your PATH.

o.bind("F10", "Voice command (push-to-talk)", "CLI_PATH ptt start")
o.bind("F10", "Voice command (release)", "CLI_PATH ptt stop", { release = true })
