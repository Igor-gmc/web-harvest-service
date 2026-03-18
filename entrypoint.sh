#!/bin/bash
# Start Xvfb (virtual display) so Chrome runs in headed mode
# This avoids --headless flag which gets detected by WAF
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
export DISPLAY=:99

# Wait for Xvfb to be ready
sleep 1

exec uvicorn src.web.app:app --host 0.0.0.0 --port 8000
