import sys
import os
import gi
import urllib.request
import threading
from datetime import datetime, date, timezone, timedelta

# Require GTK4 and Libadwaita
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio, GLib
from icalendar import Calendar
import recurring_ical_events

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Librem Calendar")
        # Simulates a mobile screen proportion for testing on desktop
        self.set_default_size(360, 720)

        # --- CONFIGURATION ---
        # PASTE YOUR PROTON CALENDAR LINK HERE
        self.PROTON_URL = "https://calendar.proton.me/api/calendar/v1/url/YOUR_LINK.ics"

        # Set up standard Linux cache directory (~/.cache/org.example.LibremCalendar/)
        self.app_id = 'org.example.LibremCalendar'
        self.cache_dir = os.path.join(GLib.get_user_cache_dir(), self.app_id)
        self.cache_file = os.path.join(self.cache_dir, 'cached_events.ics')
        os.makedirs(self.cache_dir, exist_ok=True)

        # --- UI SETUP ---
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        self.sync_button = Gtk.Button(label="Sync")
        self.sync_button.add_css_class("suggested-action")
        self.sync_button.connect("clicked", self.on_sync_clicked)
        header_bar.pack_start(self.sync_button)

        scrolled_window = Gtk.ScrolledWindow(vexpand=True)
        
        # Main vertical box to hold our daily grouped lists
        self.events_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.events_box.set_margin_top(18)
        self.events_box.set_margin_bottom(24)
        self.events_box.set_margin_start(12)
        self.events_box.set_margin_end(12)

        scrolled_window.set_child(self.events_box)
        toolbar_view.set_content(scrolled_window)

        # --- STARTUP ROUTINE ---
        # 1. Load cached data instantly so the UI isn't empty
        self.load_cached_data()

        # 2. Start an automatic sync every 3600 seconds (1 hour)
        GLib.timeout_add_seconds(3600, self.on_sync_timer_tick)
        
        # 3. Trigger a background network sync to check for new events
        self.trigger_sync()

    # --- DATA FETCHING & CACHING ---
    def load_cached_data(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'rb') as f:
                    ics_data = f.read()
                print("Loaded events from local cache.")
                self.load_ical_data(ics_data)
            except Exception as e:
                print(f"Error reading cache: {e}")

    def on_sync_clicked(self, button):
        self.trigger_sync()

    def on_sync_timer_tick(self):
        print("Running automatic hourly sync...")
        self.trigger_sync()
        return True # Keep the timer running

    def trigger_sync(self):
        # Prevent overlapping syncs
        if not self.sync_button.get_sensitive():
            return 
            
        self.sync_button.set_sensitive(False)
        self.sync_button.set_label("Syncing...")
        
        # Run network request in background
        thread = threading.Thread(target=self.fetch_calendar_data)
        thread.daemon = True 
        thread.start()

    def fetch_calendar_data(self):
        try:
            req = urllib.request.Request(self.PROTON_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                ics_data = response.read()
                
            # Save to disk
            try:
                with open(self.cache_file, 'wb') as f:
                    f.write(ics_data)
                print("Cache updated successfully.")
            except Exception as e:
                print(f"Failed to write cache: {e}")
                
            # Safely update UI on main thread
            GLib.idle_add(self.load_ical_data, ics_data)
            
        except Exception as e:
            print(f"Network error (Offline?): {e}")
            GLib.idle_add(self.reset_sync_button)

    def reset_sync_button(self):
        self.sync_button.set_sensitive(True)
        self.sync_button.set_label("Sync")

    # --- PARSING & UI BUILDING ---
    def load_ical_data(self, ics_data):
        # 1. Clear existing UI elements
        while child := self.events_box.get_first_child():
            self.events_box.remove(child)

        try:
            cal = Calendar.from_ical(ics_data)
        except Exception as e:
            print(f"Error parsing iCal data: {e}")
            self.reset_sync_button()
            return

        # 2. Expand recurring events for the next 30 days
        today = datetime.now(timezone.utc).date()
        end_date = today + timedelta(days=30)

        try:
            events = recurring_ical_events.of(cal).between(today, end_date)
        except Exception as e:
            print(f"Error expanding recurring events: {e}")
            self.reset_sync_button()
            return

        # 3. Normalize timestamps for sorting
        upcoming_events = []
        for component in events:
            dtstart = component.get('dtstart')
            if not dtstart:
                continue
                
            dt = dtstart.dt
            summary = str(component.get('summary', 'No Title'))
            
            if isinstance(dt, datetime):
                sort_key = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            else:
                sort_key = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
                
            upcoming_events.append({
                'summary': summary,
                'dt': dt,
                'sort_key': sort_key
            })

        # Sort chronologically
        upcoming_events.sort(key=lambda x: x['sort_key'])

        # 4. Group by Date String
        grouped_events = {}
        for event in upcoming_events:
            dt = event['dt']
            event_date = dt.date() if isinstance(dt, datetime) else dt
            date_label = event_date.strftime("%A, %B %d")
            
            if date_label not in grouped_events:
                grouped_events[date_label] = []
            grouped_events[date_label].append(event)

        # 5. Build the UI
        for date_label, events_on_day in grouped_events.items():
            
            # Day header
            label = Gtk.Label(label=date_label)
            label.set_halign(Gtk.Align.START)
            label.add_css_class("title-4")
            label.set_margin_bottom(6)
            
            # List container for the day
            day_list = Gtk.ListBox()
            day_list.set_selection_mode(Gtk.SelectionMode.NONE)
            day_list.add_css_class("boxed-list")
            
            # Add events to list
            for event in events_on_day:
                dt = event['dt']
                if isinstance(dt, datetime):
                    time_str = dt.strftime("%H:%M")
                else:
                    time_str = "All Day"
                    
                row = Adw.ActionRow(title=event['summary'], subtitle=time_str)
                day_list.append(row)
                
            # Bundle label and list
            section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            section_box.append(label)
            section_box.append(day_list)
            
            self.events_box.append(section_box)
            
        self.reset_sync_button()


class CalendarApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id='org.example.LibremCalendar',
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = MainWindow(application=self)
        win.present()

if __name__ == '__main__':
    app = CalendarApp()
    sys.exit(app.run(sys.argv))
