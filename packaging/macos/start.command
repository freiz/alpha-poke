#!/bin/bash
# The review app for macOS: double-click (the first time: right-click -> Open -> Open, the app is
# not from the App Store). The browser opens at the app; closing this Terminal window stops it.
cd "$(dirname "$0")" || exit 1
# (a downloaded zip marks every file "quarantined": macOS would ask about each of the app's own
# libraries; the person opened this script on purpose, so the rest of the folder is cleared too)
xattr -dr com.apple.quarantine . 2>/dev/null
exec ./alpha-poke-review
