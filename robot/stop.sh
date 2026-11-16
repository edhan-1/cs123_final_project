#!/bin/bash
# Stop red light, green light: relax the motors, stop the app, the game server and
# the robot stack. gemini_pupper's stop.sh does all of it (it relaxes the motors
# through the server on port 8000, then stops whatever serves that port, which is
# the game server), so this only finds it and makes sure the game server is gone.
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(dirname "$HERE")
GP=${GEMINI_PUPPER_DIR:-$(dirname "$REPO")/gemini_pupper}
[ -x "$GP/robot/stop.sh" ] || { echo "Can't find $GP/robot/stop.sh: set GEMINI_PUPPER_DIR"; exit 1; }
"$GP/robot/stop.sh"
pkill -f "[r]obot/game_server.py" 2>/dev/null
exit 0
