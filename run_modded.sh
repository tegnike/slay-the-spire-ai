#!/bin/sh
set -eu

APP="/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app"
MACOS="$APP/Contents/MacOS"
LAUNCHER_OPTS="$MACOS/launcher_opts.toml"
BACKUP="$MACOS/launcher_opts.toml.codex-backup"
MTS="/Users/user/Library/Application Support/Steam/steamapps/workshop/content/646570/1605060445/ModTheSpire.jar"

restore_launcher_opts() {
    if [ -f "$BACKUP" ]; then
        cp -p "$BACKUP" "$LAUNCHER_OPTS"
        rm -f "$BACKUP"
    fi
}

cp -p "$LAUNCHER_OPTS" "$BACKUP"
trap restore_launcher_opts EXIT HUP INT TERM

python3 - "$LAUNCHER_OPTS" "$MTS" <<'PY'
from pathlib import Path
import sys

launcher_opts = Path(sys.argv[1])
mts = sys.argv[2]
launcher_opts.write_text(
    "\n".join(
        [
            'program = "jre/bin/java"',
            'args = ["-Xdock:icon=icons.icns", "-jar", '
            f'"{mts}", "--mods", "basemod,CommunicationMod", "--skip-intro"]',
            'working_dir = "../Resources"',
            "",
        ]
    ),
    encoding="utf-8",
)
PY

"$MACOS/SlayTheSpire"
