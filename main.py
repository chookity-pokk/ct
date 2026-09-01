import sys
import gi
import urllib.request
import threading
from datetime import datetime
from icalendar import Calendar

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio, GLib

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Librem Calendar")
        self.set_default_size(360, 720)

        # PASTE YOUR PROTON CALENDAR LINK HERE
        self.PROTON_URL = "https://calendar.proton.me/api/calendar/v1/url/YOUR_LINK.ics"

        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        # Replaced the Open button with a Sync button
        self.sync_button = Gtk.Button(label="Sync Proton")
        self.sync_button.add_css_class("suggested-action")
        self.sync_button.connect("clicked", self.on_sync_clicked)
        header_bar.pack_start(self.sync_button)

        scrolled_window = Gtk.ScrolledWindow(vexpand=True)
        
        self.events_list = Gtk.ListBox()
        self.events_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.events_list.add_css_class("boxed-list")
        self.events_list.set_margin_top(12)
        self.events_list.set_margin_bottom(12)
        self.events_list.set_margin_start(12)
        self.events_list.set_margin_end(12)

        scrolled_window.set_child(self.events_list)
        toolbar_view.set_content(scrolled_window)

    def on_sync_clicked(self, button):
        # Disable the button so the user doesn't spam requests
        self.sync_button.set_sensitive(False)
        self.sync_button.set_label("Syncing...")
        
        # Start the network request in a background thread
        thread = threading.Thread(target=self.fetch_calendar_data)
        thread.daemon = True # Thread dies when app closes
        thread.start()

    def fetch_calendar_data(self):
        try:
            # Some servers block default python user-agents, so we spoof a browser
            req = urllib.request.Request(self.PROTON_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                ics_data = response.read()
                
            # Safely schedule the UI update on the main GTK thread
            GLib.idle_add(self.load_ical_data, ics_data)
            
        except Exception as e:
            print(f"Network error: {e}")
            # Reset button on failure
            GLib.idle_add(self.reset_sync_button)

    def load_ical_data(self, ics_data):
        # Clear existing list
        while child := self.events_list.get_first_child():
            self.events_list.remove(child)

        try:
            cal = Calendar.from_ical(ics_data)
        except Exception as e:
            print(f"Error parsing downloaded iCal data: {e}")
            self.reset_sync_button()
            return

        for component in cal.walk('VEVENT'):
            summary = str(component.get('summary', 'No Title'))
            dtstart = component.get('dtstart')
            date_str = "Unknown Date"
            
            if dtstart:
                dt = dtstart.dt
                if hasattr(dt, 'hour'):
                    date_str = dt.strftime("%B %d, %Y - %H:%M")
                else:
                    date_str = dt.strftime("%B %d, %Y (All Day)")

            row = Adw.ActionRow(title=summary, subtitle=date_str)
            self.events_list.append(row)
            
        self.reset_sync_button()

    def reset_sync_button(self):
        self.sync_button.set_sensitive(True)
        self.sync_button.set_label("Sync Proton")

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
