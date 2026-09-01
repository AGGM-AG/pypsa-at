#!/bin/sh
# Prints the currently valid "Connect to running IDE" link for the PyCharm backend in this devcontainer.
# The jt= token changes when Gateway opens a new session with the backend.
export XDG_CACHE_HOME=/.jbdevcontainer XDG_CONFIG_HOME=/.jbdevcontainer/config XDG_DATA_HOME=/.jbdevcontainer/data
W=$(ls /.jbdevcontainer/JetBrains/RemoteDev/remote-dev-worker/remote-dev-worker_* | head -1)
# IDE dist of the *running* backend (…/dist/<hash>_pycharm-<ver>/bin/remote-dev-server)
BIN=$(tr '\0' '\n' < /proc/"$(pgrep -f 'bin/remote-dev-server run' | head -1)"/cmdline | head -1)
IDE=$(dirname "$(dirname "$BIN")")
[ -d "$IDE" ] || { echo "backend not running?" >&2; exit 1; }
"$W" host-status --ide-path="$IDE" --project-path=/IdeaProjects/pypsa-at 2>/dev/null | python3 -c '
import sys, json
outer = json.loads(sys.stdin.read()); inner = json.loads(outer["data"])
print(inner.get("joinLink") or "no joinLink in: %s" % inner)'
