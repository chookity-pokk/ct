#!/bin/bash

echo "Starting Librem Calendar Daemon Setup..."

# 1. Define paths
BIN_DIR="$HOME/.local/bin"
DAEMON_DEST="$BIN_DIR/librem_calendar_daemon.py"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_DIR/librem-calendar-daemon.service"

# 2. Create the necessary hidden system directories
mkdir -p "$BIN_DIR"
mkdir -p "$SYSTEMD_DIR"
echo "  -> Created system directories."

# 3. Write the Python Daemon script directly to the bin directory
# We use 'EOF' in quotes so Bash doesn't try to evaluate Python variables
cat << 'EOF' > "$DAEMON_DEST"
import os
import json
import time
import subprocess
from datetime import datetime, timezone, timedelta
from icalendar import Calendar
import recurring_ical_events
import gi

gi.require_version('GLib', '2.0')
from gi.repository import GLib

# Paths (must match the GUI app exactly)
APP_ID = 'org.example.LibremCalendar'
CACHE_DIR = os.path.join(GLib.get_user_cache_dir(), APP_ID)
CACHE_FILE = os.path.join(CACHE_DIR, 'cached_events.ics')
LOCAL_FILE = os.path.join(CACHE_DIR, 'local_events.ics')
COMPLETED_FILE = os.path.join(CACHE_DIR, 'completed_ids.json')
NOTIFIED_FILE = os.path.join(CACHE_DIR, 'notified_ids.json')

CATEGORY_MAP = {
    "Default": "x-office-calendar-symbolic",
    "Work": "computer-symbolic",
    "Personal": "user-home-symbolic",
    "Social": "system-users-symbolic",
    "Health": "starred-symbolic",
    "Chores": "view-list-symbolic",
    "Activity": "weather-clear-symbolic",
    "Finance": "accessories-calculator-symbolic"
}

def load_json_set(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def save_json_set(filepath, data_set):
    try:
        with open(filepath, 'w') as f:
            json.dump(list(data_set), f)
    except Exception as e:
        print(f"Error saving {filepath}: {e}")

def check_upcoming_events():
    today = datetime.now(timezone.utc).date()
    end_date = today + timedelta(days=2) 
    now = datetime.now(timezone.utc)
    
    completed_ids = load_json_set(COMPLETED_FILE)
    notified_ids = load_json_set(NOTIFIED_FILE)
    
    def process_file(filepath):
        if not os.path.exists(filepath):
            return
            
        try:
            with open(filepath, 'rb') as f:
                cal = Calendar.from_ical(f.read())
            events = recurring_ical_events.of(cal).between(today, end_date)
            
            for component in events:
                dtstart = component.get('dtstart')
                if not dtstart: continue
                
                dt_original = dtstart.dt
                # Skip all-day events (they have no specific start time)
                if not isinstance(dt_original, datetime): continue
                
                event_time = dt_original if dt_original.tzinfo else dt_original.astimezone(timezone.utc)
                summary = str(component.get('summary', 'No Title'))
                
                # Fetch Category for Icon
                cat_obj = component.get('categories')
                category = "Default"
                if cat_obj:
                    try:
                        cat_str = cat_obj.to_ical().decode('utf-8')
                        category = cat_str.split(',')[0].strip()
                    except Exception:
                        pass
                icon_name = CATEGORY_MAP.get(category, CATEGORY_MAP["Default"])
                
                event_id = f"{summary}_{event_time.isoformat()}"
                
                if event_id in completed_ids or event_id in notified_ids:
                    continue
                    
                time_diff = event_time - now
                
                # Notify if event starts in the next 15 minutes
                if timedelta(minutes=0) < time_diff <= timedelta(minutes=15):
                    local_time = event_time.astimezone().strftime("%I:%M %p")
                    
                    subprocess.run([
                        "notify-send",
                        "-a", "Librem Calendar",
                        "-i", icon_name,
                        f"{summary}",
                        f"Starts at {local_time}"
                    ])
                    
                    notified_ids.add(event_id)
        except Exception as e:
            print(f"Daemon error reading {filepath}: {e}")

    process_file(CACHE_FILE)
    process_file(LOCAL_FILE)
    
    save_json_set(NOTIFIED_FILE, notified_ids)

if __name__ == "__main__":
    os.makedirs(CACHE_DIR, exist_ok=True)
    while True:
        check_upcoming_events()
        time.sleep(60) 
EOF
echo "  -> Generated Python daemon script."

# 4. Make the Python script executable
chmod +x "$DAEMON_DEST"

# 5. Generate the systemd service file dynamically
cat << EOF > "$SERVICE_FILE"
[Unit]
Description=Librem Calendar Notification Daemon
After=network.target

[Service]
ExecStart=/usr/bin/python3 $DAEMON_DEST
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
EOF
echo "  -> Created systemd service file."

# 6. Register, enable, and start the service
echo "  -> Registering daemon with systemd..."
systemctl --user daemon-reload
systemctl --user enable librem-calendar-daemon.service
systemctl --user restart librem-calendar-daemon.service

echo ""
echo "✅ Installation complete!"
echo "The daemon is now running in the background and will start automatically on boot."
echo "You can check its status at any time by running:"
echo "systemctl --user status librem-calendar-daemon.service"
