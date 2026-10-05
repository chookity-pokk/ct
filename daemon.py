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

# Tracks which notifications have already been sent so they don't loop
NOTIFIED_FILE = os.path.join(CACHE_DIR, 'notified_ids.json')

# Maps category names to standard GNOME system icons
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
                
                # Standardize to UTC for accurate time math
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
                
                # Create a unique ID for this specific occurrence
                event_id = f"{summary}_{event_time.isoformat()}"
                
                # If marked as completed or already notified, ignore it
                if event_id in completed_ids or event_id in notified_ids:
                    continue
                    
                time_diff = event_time - now
                
                # Notify if event starts in the next 15 minutes
                if timedelta(minutes=0) < time_diff <= timedelta(minutes=15):
                    # Convert UTC back to local time for the notification text
                    local_time = event_time.astimezone().strftime("%I:%M %p")
                    
                    # Fire the native Linux notification
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
    print("Librem Calendar Daemon is running...")
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    while True:
        check_upcoming_events()
        time.sleep(60) # Pause for 60 seconds before checking again
