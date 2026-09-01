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
from icalendar import Calendar, Event
import recurring_ical_events

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Librem Calendar")
        self.set_default_size(360, 720)

        # --- CONFIGURATION ---
        self.PROTON_URL = "https://calendar.proton.me/api/calendar/v1/url/YOUR_LINK.ics"

        # Cache paths
        self.app_id = 'org.example.LibremCalendar'
        self.cache_dir = os.path.join(GLib.get_user_cache_dir(), self.app_id)
        
        # We now have TWO files: one for Proton, one for local-only events
        self.cache_file = os.path.join(self.cache_dir, 'cached_events.ics')
        self.local_file = os.path.join(self.cache_dir, 'local_events.ics')
        os.makedirs(self.cache_dir, exist_ok=True)

        # --- UI SETUP ---
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        # Add Event Button (Left side)
        self.add_button = Gtk.Button(icon_name="list-add-symbolic")
        self.add_button.connect("clicked", self.on_add_clicked)
        header_bar.pack_start(self.add_button)

        # Sync Button (Right side)
        self.sync_button = Gtk.Button(label="Sync")
        self.sync_button.add_css_class("suggested-action")
        self.sync_button.connect("clicked", self.on_sync_clicked)
        header_bar.pack_end(self.sync_button)

        scrolled_window = Gtk.ScrolledWindow(vexpand=True)
        self.events_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.events_box.set_margin_top(18)
        self.events_box.set_margin_bottom(24)
        self.events_box.set_margin_start(12)
        self.events_box.set_margin_end(12)

        scrolled_window.set_child(self.events_box)
        toolbar_view.set_content(scrolled_window)

        # --- STARTUP ROUTINE ---
        self.load_all_events()
        GLib.timeout_add_seconds(3600, self.on_sync_timer_tick)
        self.trigger_sync()

    # --- ADD EVENT LOGIC (LOCAL ONLY) ---
    def on_add_clicked(self, button):
        # Create a Libadwaita Message Dialog for input
        dialog = Adw.MessageDialog(
            parent=self, 
            heading="New Local Event", 
            body="This event will be saved locally. It cannot sync to Proton."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add Event")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        # Input fields
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        
        title_entry = Gtk.Entry(placeholder_text="Event Title (e.g., Dentist)")
        vbox.append(title_entry)
        
        date_entry = Gtk.Entry(placeholder_text="Date (YYYY-MM-DD)")
        # Pre-fill with today's date for convenience
        date_entry.set_text(datetime.now().strftime("%Y-%m-%d"))
        vbox.append(date_entry)

        dialog.set_extra_child(vbox)

        # Handle the user's response
        def on_response(dialog, response):
            if response == "add":
                title = title_entry.get_text()
                date_str = date_entry.get_text()
                self.save_local_event(title, date_str)

        dialog.connect("response", on_response)
        dialog.present()

    def save_local_event(self, title, date_str):
        if not title or not date_str:
            return

        try:
            event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            print("Invalid date format. Use YYYY-MM-DD.")
            return

        # 1. Load existing local calendar or create a new one
        cal = Calendar()
        if os.path.exists(self.local_file):
            with open(self.local_file, 'rb') as f:
                cal = Calendar.from_ical(f.read())
        else:
            cal.add('prodid', '-//Librem Local Calendar//')
            cal.add('version', '2.0')

        # 2. Create the new event
        event = Event()
        event.add('summary', title)
        event.add('dtstart', event_date)
        cal.add_component(event)

        # 3. Save back to the local file
        with open(self.local_file, 'wb') as f:
            f.write(cal.to_ical())

        # 4. Refresh the UI
        self.load_all_events()

    # --- DATA FETCHING & CACHING ---
    def on_sync_clicked(self, button):
        self.trigger_sync()

    def on_sync_timer_tick(self):
        self.trigger_sync()
        return True

    def trigger_sync(self):
        if not self.sync_button.get_sensitive():
            return 
        self.sync_button.set_sensitive(False)
        self.sync_button.set_label("Syncing...")
        
        thread = threading.Thread(target=self.fetch_calendar_data)
        thread.daemon = True 
        thread.start()

    def fetch_calendar_data(self):
        try:
            req = urllib.request.Request(self.PROTON_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                ics_data = response.read()
                
            with open(self.cache_file, 'wb') as f:
                f.write(ics_data)
                
            # Safely tell the UI thread to refresh everything
            GLib.idle_add(self.load_all_events)
            
        except Exception as e:
            print(f"Network error (Offline?): {e}")
            GLib.idle_add(self.reset_sync_button)

    def reset_sync_button(self):
        self.sync_button.set_sensitive(True)
        self.sync_button.set_label("Sync")

    # --- PARSING & UI BUILDING ---
    def load_all_events(self):
        # Clear existing UI
        while child := self.events_box.get_first_child():
            self.events_box.remove(child)

        upcoming_events = []
        today = datetime.now(timezone.utc).date()
        end_date = today + timedelta(days=30)

        # Helper function to parse a specific ics file and add it to our list
        def extract_events_from_file(filepath, is_local=False):
            if not os.path.exists(filepath):
                return
                
            try:
                with open(filepath, 'rb') as f:
                    cal = Calendar.from_ical(f.read())
                    
                events = recurring_ical_events.of(cal).between(today, end_date)
                
                for component in events:
                    dtstart = component.get('dtstart')
                    if not dtstart: continue
                        
                    dt = dtstart.dt
                    summary = str(component.get('summary', 'No Title'))
                    
                    if is_local:
                        summary = f"📱 {summary}" # Visually distinguish local events
                    
                    if isinstance(dt, datetime):
                        sort_key = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                    else:
                        sort_key = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
                        
                    upcoming_events.append({
                        'summary': summary,
                        'dt': dt,
                        'sort_key': sort_key
                    })
            except Exception as e:
                print(f"Error reading {filepath}: {e}")

        # Extract from both Proton and Local files
        extract_events_from_file(self.cache_file, is_local=False)
        extract_events_from_file(self.local_file, is_local=True)

        # Sort combined list chronologically
        upcoming_events.sort(key=lambda x: x['sort_key'])

        # Group by Date String
        grouped_events = {}
        for event in upcoming_events:
            dt = event['dt']
            event_date = dt.date() if isinstance(dt, datetime) else dt
            date_label = event_date.strftime("%A, %B %d")
            
            if date_label not in grouped_events:
                grouped_events[date_label] = []
            grouped_events[date_label].append(event)

        # Build the UI
        for date_label, events_on_day in grouped_events.items():
            label = Gtk.Label(label=date_label)
            label.set_halign(Gtk.Align.START)
            label.add_css_class("title-4")
            label.set_margin_bottom(6)
            
            day_list = Gtk.ListBox()
            day_list.set_selection_mode(Gtk.SelectionMode.NONE)
            day_list.add_css_class("boxed-list")
            
            for event in events_on_day:
                dt = event['dt']
                if isinstance(dt, datetime):
                    time_str = dt.strftime("%H:%M")
                else:
                    time_str = "All Day"
                    
                row = Adw.ActionRow(title=event['summary'], subtitle=time_str)
                day_list.append(row)
                
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
