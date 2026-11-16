#!/bin/bash
# Start red light, green light on the robot. PUPPER STANDS UP AND WALKS when the
# game is played: on the ground, clear floor ahead, a hand near the e-stop
# (press the gamepad's right stick).
#   robot/start.sh            robot stack + game server + eye (use from a laptop through an SSH tunnel)
#   robot/start.sh --kiosk    also show the app full-screen on the robot's own screen. Our Pupper
#                             has no microphone and the kiosk has no fast ear: play from a laptop.
# Stop everything with robot/stop.sh.
#
# This is gemini_pupper/robot/start.sh with two changes. Step 2 starts
# robot/game_server.py (the game's tools, prompt and page) instead of gemini_pupper's
# server.py, and then robot/eye.py, which watches the caller in a game by camera.
# The robot stack, the web app and the kiosk are gemini_pupper's own.
#
# The eye needs the Hailo, and one program holds the Hailo at a time. The robot
# stack's own person detector would hold it all day. So we point the stack at our
# lab 5 follower instead (FOLLOW_ME_DIR, see person_follower in gemini_pupper's
# launch file): it only takes the Hailo while Pupper follows somebody, which
# never happens in the game. This also keeps the Pi much cooler.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(dirname "$HERE")
GP=${GEMINI_PUPPER_DIR:-$(dirname "$REPO")/gemini_pupper}
LOG=/tmp/gemini-pupper; mkdir -p $LOG   # gemini_pupper's log folder: its launch files write there too
KEY_FILE=${GEMINI_KEY_FILE:-$HOME/.config/gemini-pupper/api_key}
KIOSK=0; [ "${1:-}" = "--kiosk" ] && KIOSK=1
free_port() {  # stop whatever is serving port 8000 (an older robot server)
  local pids; pids=$(ss -ltnpH "sport = :8000" 2>/dev/null | grep -oP "pid=\\K[0-9]+" | sort -u)
  [ -n "$pids" ] && kill $pids 2>/dev/null && sleep 1
  return 0
}
export FOLLOW_ME_DIR=${FOLLOW_ME_DIR:-$(dirname "$REPO")/follow_me_pupper}
ROS="source /opt/ros/jazzy/setup.bash; source $HOME/pupperv3-monorepo/ros2_ws/install/local_setup.bash; export ROS_LOCALHOST_ONLY=1"

[ -f "$GP/robot/server.py" ] || { echo "Can't find gemini_pupper at $GP: clone it next to this repo, or set GEMINI_PUPPER_DIR"; exit 1; }
[ -f "$GP/web/dist/index.html" ] || { echo "Missing $GP/web/dist: run $GP/robot/setup.sh first (it builds the web app)"; exit 1; }
if [ $KIOSK = 1 ] && [ ! -s "$KEY_FILE" ]; then
  echo "Missing $KEY_FILE. Run $GP/robot/setup.sh, or create it with:  mkdir -p $(dirname $KEY_FILE) && (umask 077; cat > $KEY_FILE)"; exit 1
fi

if pgrep -f "[r]os2_control_node" >/dev/null; then
  echo "[1/3] robot stack already running"
  pgrep -f "[h]ailo_detection" >/dev/null && echo "      its person detector holds the Hailo, so the eye cannot start and games" \
    "by camera are refused. For those: robot/stop.sh, then robot/start.sh again."
else
  [ -f "$FOLLOW_ME_DIR/robot/follow_service.py" ] || echo "      no lab 5 follower at $FOLLOW_ME_DIR: the stack's own" \
    "person detector will hold the Hailo, and games by camera will be refused"
  echo "[1/3] starting robot stack (about a minute; log $LOG/robot.log)"
  rm -f $LOG/controllers_ready
  setsid nohup bash -c "$ROS; exec ros2 launch $GP/robot/launch/gemini_pupper.launch.py" > $LOG/robot.log 2>&1 < /dev/null &
  # spawn_controllers.py writes this once gemini_walk and every trick controller is loaded
  for i in $(seq 1 240); do [ -f $LOG/controllers_ready ] && break; sleep 1; done
  if [ -f $LOG/controllers_ready ]; then echo "      $(cat $LOG/controllers_ready)"
  else echo "      controllers still loading after 4 min; see $LOG/robot.log"; fi
fi

echo "[2/3] starting the game server on localhost:8000 (log $LOG/server.log)"
pkill -f "[r]obot/server.py" 2>/dev/null; pkill -f "[r]obot/game_server.py" 2>/dev/null; free_port
setsid nohup bash -c "$ROS; cd $HERE && exec python3 -u $HERE/game_server.py" > $LOG/server.log 2>&1 < /dev/null &
for i in $(seq 1 30); do curl -s -o /dev/null localhost:8000/health && break; sleep 1; done
curl -s -o /dev/null localhost:8000/health || { echo "game server did not start; see $LOG/server.log"; exit 1; }
echo "      starting the eye (log $LOG/eye.log)"
pkill -f "[r]obot/eye.py" 2>/dev/null; rm -f $LOG/eye.jpg
setsid nohup bash -c "$ROS; cd $HERE && exec python3 -u $HERE/eye.py" > $LOG/eye.log 2>&1 < /dev/null &

if [ $KIOSK = 0 ]; then
  echo "[3/3] ready. From a laptop:  ssh -N -L 8000:localhost:8000 pi@<pupper>  then open http://localhost:8000/play in Chrome"
  exit 0
fi
echo "[3/3] opening the app on the robot's screen"
export XDG_RUNTIME_DIR=/run/user/$(id -u) WAYLAND_DISPLAY=wayland-0
sudo -n systemctl stop pupper-gui 2>/dev/null
pkill -f "[g]emini-pupper-kiosk" 2>/dev/null; pkill -f "[r]obot/kiosk.py" 2>/dev/null; sleep 1
amixer -q sset Master 100% 2>/dev/null; wpctl set-volume @DEFAULT_SINK@ 1.0 2>/dev/null
setsid nohup chromium --ozone-platform=wayland --kiosk --noerrdialogs --disable-infobars --no-first-run \
  --password-store=basic --use-fake-ui-for-media-stream --autoplay-policy=no-user-gesture-required \
  --remote-debugging-port=9222 --user-data-dir=$HOME/.cache/gemini-pupper-kiosk http://localhost:8000 \
  > $LOG/chromium.log 2>&1 < /dev/null &
setsid nohup python3 -u $GP/robot/kiosk.py "$KEY_FILE" > $LOG/kiosk.log 2>&1 < /dev/null &
sleep 12; tail -2 $LOG/kiosk.log
echo "ready. Stop with robot/stop.sh"
