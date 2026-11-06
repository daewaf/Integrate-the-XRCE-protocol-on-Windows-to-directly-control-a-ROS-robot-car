#!/usr/bin/env bash
set -eo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
source /opt/ros/humble/setup.bash
exec /usr/bin/python3 app.py
