#!/bin/sh
# Start the PyCharm remote-dev backend headless inside the devcontainer,
# without going through JetBrains Gateway (issue #317 workaround).
# Safe to run repeatedly; exits 0 if the backend is already up.
# Usage (from the docker host):  docker exec -d <container> sh /IdeaProjects/pypsa-at/.devcontainer/backend.sh
export XDG_CACHE_HOME=/.jbdevcontainer XDG_CONFIG_HOME=/.jbdevcontainer/config XDG_DATA_HOME=/.jbdevcontainer/data

pgrep -f 'bin/remote-dev-server run' >/dev/null 2>&1 && { echo "backend already running"; exit 0; }

# prefer the dist Gateway used last; fall back to the newest installed dist
IDE=$(python3 -c 'import json; print(json.load(open("/.jbdevcontainer/config/JetBrains/host-config.json"))["connectionParams"]["idePath"])' 2>/dev/null)
[ -n "$IDE" ] && [ -d "$IDE" ] || IDE=$(ls -td /.jbdevcontainer/JetBrains/RemoteDev/dist/*/ 2>/dev/null | head -1)
[ -n "$IDE" ] && [ -d "$IDE" ] || { echo "no PyCharm dist found - connect once via Gateway first" >&2; exit 1; }

echo "starting backend from $IDE (log: /tmp/backend.log)"
nohup "${IDE%/}/bin/remote-dev-server.sh" run /IdeaProjects/pypsa-at >/tmp/backend.log 2>&1 &
