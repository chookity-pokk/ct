import sys
import os
import json
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

# --- CATEGORY TO ICON MAPPING ---
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
CATEGORIES_LIST = list(CATEGORY_MAP.keys())

# --- PAST EVENT FILTER OPTIONS ---
PAST_FILTER_OPTIONS = ["Last 7 Days", "Last 30 Days", "Last 90 Days", "Last Year", "All Time"]
PAST_FILTER_DAYS = [7, 30, 90, 365, 3650] 


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Librem Calendar")
        self.set_default_size(360, 720)

        # --- STATE VARIABLES ---
        self.all_parsed_events = []

        # --- CACHE & CONFIGURATION PATHS ---
        self.app_id = 'org.example.LibremCalendar'
        self.cache_dir = os.path.join(GLib.get_user_cache_dir(), self.app_id)
        
        self.cache_file = os.path.join(self.cache_dir, 'cached_events.ics')
        self.local_file = os.path.join(self.cache_dir, 'local_events.ics')
        self.completed_file = os.path.join(self.cache_dir, 'completed_ids.json')
        self.config_file = os.path.join(self.cache_dir, 'config.json')
        os.makedirs(self.cache_dir, exist_ok=True)

        self.PROTON_URL, self.past_days_filter = self.load_config()
        self.completed_ids = self.load_completed_ids()

        # --- UI SETUP ---
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        # Left side: Add Event Button
        self.add_button = Gtk.Button(icon_name="list-add-symbolic")
        self.add_button.connect("clicked", self.on_add_clicked)
        header_bar.pack_start(self.add_button)

        # Right side: Sync Button
        self.sync_button = Gtk.Button(label="Sync")
        self.sync_button.add_css_class("suggested-action")
        self.sync_button.connect("clicked", self.on_sync_clicked)
        header_bar.pack_end(self.sync_button)
        
        # Right side: Settings Button
        self.settings_button = Gtk.Button(icon_name="preferences-system-symbolic")
        self.settings_button.connect("clicked", self.on_settings_clicked)
        header_bar.pack_end(self.settings_button)

        # --- TAB NAVIGATION (Adw.ViewStack) ---
        self.view_stack = Adw.ViewStack()

        # 1. Past Tab
        scrolled_past = Gtk.ScrolledWindow(vexpand=True)
        self.past_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.setup_box_margins(self.past_box)
        scrolled_past.set_child(self.past_box)
        
        page_past = self.view_stack.add_titled(scrolled_past, "past", "Past")
        page_past.set_icon_name("document-open-recent-symbolic")

        # 2. Upcoming Tab
        scrolled_upcoming = Gtk.ScrolledWindow(vexpand=True)
        self.upcoming_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.setup_box_margins(self.upcoming_box)
        scrolled_upcoming.set_child(self.upcoming_box)
        
        page_upcoming = self.view_stack.add_titled(scrolled_upcoming, "upcoming", "Upcoming")
        page_upcoming.set_icon_name("x-office-calendar-symbolic")

        # 3. Completed Tab
        scrolled_completed = Gtk.ScrolledWindow(vexpand=True)
        self.completed_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.setup_box_margins(self.completed_box)
        scrolled_completed.set_child(self.completed_box)

        page_completed = self.view_stack.add_titled(scrolled_completed, "completed", "Completed")
        page_completed.set_icon_name("object-select-symbolic")

        toolbar_view.set_content(self.view_stack)

        # Bottom View Switcher Bar
        switcher_bar = Adw.ViewSwitcherBar()
        switcher_bar.set_stack(self.view_stack)
        switcher_bar.set_reveal(True)
        toolbar_view.add_bottom_bar(switcher_bar)
        
        self.view_stack.set_visible_child_name("upcoming")

        # --- STARTUP ROUTINE ---
        self.load_all_events()
        GLib.timeout_add_seconds(3600, self.on_sync_timer_tick)
        if self.PROTON_URL:
            self.trigger_sync()

    def setup_box_margins(self, box):
        box.set_margin_top(18)
        box.set_margin_bottom(24)
        box.set_margin_start(12)
        box.set_margin_end(12)

    # --- JSON CONFIGURATION ---
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    return data.get("proton_url", ""), data.get("past_days_filter", 30)
            except Exception as e:
                print(f"Error loading config: {e}")
        return "", 30

    def save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump({
                    "proton_url": self.PROTON_URL,
                    "past_days_filter": self.past_days_filter
                }, f)
        except Exception as e:
            print(f"Error saving config: {e}")

    def load_completed_ids(self):
        if os.path.exists(self.completed_file):
            try:
                with open(self.completed_file, 'r') as f:
                    return set(json.load(f))
            except Exception:
                pass
        return set()

    def save_completed_ids(self):
        try:
            with open(self.completed_file, 'w') as f:
                json.dump(list(self.completed_ids), f)
        except Exception as e:
            print(f"Error saving completed IDs: {e}")

    # --- SETTINGS DIALOG ---
    def on_settings_clicked(self, button):
        pref_window = Adw.PreferencesWindow(parent=self, title="Settings")
        page = Adw.PreferencesPage()
        
        sync_group = Adw.PreferencesGroup(title="Sync Integration")
        url_entry = Adw.EntryRow(title="Calendar .ics Link")
        url_entry.set_text(self.PROTON_URL)
        
        def on_text_changed(entry, param):
            self.PROTON_URL = entry.get_text().strip()
            self.save_config()
            
        url_entry.connect("notify::text", on_text_changed)
        sync_group.add(url_entry)
        page.add(sync_group)

        display_group = Adw.PreferencesGroup(title="Display Options")
        filter_row = Adw.ComboRow(title="Show Past Events")
        model = Gtk.StringList.new(PAST_FILTER_OPTIONS)
        filter_row.set_model(model)
        
        try:
            current_idx = PAST_FILTER_DAYS.index(self.past_days_filter)
        except ValueError:
            current_idx = 1
        filter_row.set_selected(current_idx)

        def on_filter_changed(combo, param):
            idx = combo.get_selected()
            self.past_days_filter = PAST_FILTER_DAYS[idx]
            self.save_config()
            self.load_all_events() 

        filter_row.connect("notify::selected", on_filter_changed)
        display_group.add(filter_row)
        page.add(display_group)

        pref_window.add(page)
        pref_window.present()

    # --- ROW CLICK / EDIT LOGIC ---
    def on_row_activated(self, listbox, row):
        event = getattr(row, '_event_data', None)
        if not event: return

        if not event.get('is_local'):
            dialog = Adw.MessageDialog(
                parent=self, 
                heading="Proton Event", 
                body="This event is synced from Proton Calendar and cannot be edited locally."
            )
            dialog.add_response("close", "Close")
            dialog.present()
            return

        # Build Edit Dialog for Local Events
        dialog = Adw.MessageDialog(
            parent=self, 
            heading="Edit Event", 
            body="Update or remove this local event."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.add_response("save", "Save")
        
        # Style the buttons properly
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        
        title_entry = Gtk.Entry()
        title_entry.set_text(event['summary_original'])
        vbox.append(title_entry)
        
        category_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        category_box.set_halign(Gtk.Align.CENTER)
        category_box.append(Gtk.Label(label="Category:"))
        
        category_dropdown = Gtk.DropDown.new_from_strings(CATEGORIES_LIST)
        try:
            idx = CATEGORIES_LIST.index(event['category_raw'])
        except ValueError:
            idx = 0
        category_dropdown.set_selected(idx)
        category_box.append(category_dropdown)
        vbox.append(category_box)

        calendar = Gtk.Calendar()
        dt_orig = event['dt_original']
        
        if isinstance(dt_orig, datetime):
            local_dt = dt_orig.astimezone() if dt_orig.tzinfo else dt_orig
        else:
            local_dt = dt_orig
            
        gdate = GLib.DateTime.new_local(local_dt.year, local_dt.month, local_dt.day, 0, 0, 0)
        calendar.select_day(gdate)
        vbox.append(calendar)

        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_box.set_halign(Gtk.Align.CENTER)
        time_box.append(Gtk.Label(label="Time (24h):"))

        current_hour = local_dt.hour if isinstance(dt_orig, datetime) else 0
        current_min = local_dt.minute if isinstance(dt_orig, datetime) else 0
        
        adj_hour = Gtk.Adjustment(value=current_hour, lower=0, upper=23, step_increment=1)
        hour_spin = Gtk.SpinButton(adjustment=adj_hour, numeric=True, orientation=Gtk.Orientation.VERTICAL)
        time_box.append(hour_spin)

        time_box.append(Gtk.Label(label=":"))

        adj_min = Gtk.Adjustment(value=current_min, lower=0, upper=59, step_increment=5)
        min_spin = Gtk.SpinButton(adjustment=adj_min, numeric=True, orientation=Gtk.Orientation.VERTICAL)
        time_box.append(min_spin)

        vbox.append(time_box)
        dialog.set_extra_child(vbox)

        def on_response(dialog, response):
            if response == "delete":
                self.update_local_event(event, delete=True)
            elif response == "save":
                new_title = title_entry.get_text()
                selected_idx = category_dropdown.get_selected()
                new_category = CATEGORIES_LIST[selected_idx]

                gdate = calendar.get_date()
                year, month, day = gdate.get_year(), gdate.get_month(), gdate.get_day_of_month()
                hour, minute = hour_spin.get_value_as_int(), min_spin.get_value_as_int()
                
                new_local_dt = datetime(year, month, day, hour, minute)
                new_utc_dt = new_local_dt.astimezone(timezone.utc)
                
                self.update_local_event(event, new_title, new_utc_dt, new_category, delete=False)

        dialog.connect("response", on_response)
        dialog.present()

    def update_local_event(self, old_event, new_title=None, new_dt=None, new_category=None, delete=False):
        if not os.path.exists(self.local_file):
            return
            
        try:
            with open(self.local_file, 'rb') as f:
                cal = Calendar.from_ical(f.read())
                
            found_idx = -1
            # Search through the .ics file to find the exact matching event block
            for i, component in enumerate(cal.subcomponents):
                if component.name == 'VEVENT':
                    c_summary = str(component.get('summary', ''))
                    c_dtstart = component.get('dtstart')
                    if c_dtstart and c_dtstart.dt == old_event['dt_original'] and c_summary == old_event['summary_original']:
                        found_idx = i
                        break
                        
            if found_idx != -1:
                if delete:
                    del cal.subcomponents[found_idx]
                else:
                    comp = cal.subcomponents[found_idx]
                    # Remove old properties before adding the new ones
                    del comp['summary']
                    del comp['dtstart']
                    if 'categories' in comp:
                        del comp['categories']
                        
                    comp.add('summary', new_title)
                    comp.add('dtstart', new_dt)
                    comp.add('categories', new_category)
                    
                with open(self.local_file, 'wb') as f:
                    f.write(cal.to_ical())
                    
                self.load_all_events() # Rebuild the UI from the fresh file
                
        except Exception as e:
            print(f"Error updating local event: {e}")

    # --- ADD EVENT DIALOG ---
    def on_add_clicked(self, button):
        dialog = Adw.MessageDialog(
            parent=self, 
            heading="New Local Event", 
            body="Select details for your new event."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add Event")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        
        title_entry = Gtk.Entry(placeholder_text="Event Title (e.g., Dentist)")
        vbox.append(title_entry)
        
        category_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        category_box.set_halign(Gtk.Align.CENTER)
        category_box.append(Gtk.Label(label="Category:"))
        
        category_dropdown = Gtk.DropDown.new_from_strings(CATEGORIES_LIST)
        category_box.append(category_dropdown)
        vbox.append(category_box)

        calendar = Gtk.Calendar()
        vbox.append(calendar)

        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_box.set_halign(Gtk.Align.CENTER)
        time_box.append(Gtk.Label(label="Time (24h):"))

        current_hour = datetime.now().hour
        adj_hour = Gtk.Adjustment(value=current_hour, lower=0, upper=23, step_increment=1)
        hour_spin = Gtk.SpinButton(adjustment=adj_hour, numeric=True, orientation=Gtk.Orientation.VERTICAL)
        time_box.append(hour_spin)

        time_box.append(Gtk.Label(label=":"))

        adj_min = Gtk.Adjustment(value=0, lower=0, upper=59, step_increment=5)
        min_spin = Gtk.SpinButton(adjustment=adj_min, numeric=True, orientation=Gtk.Orientation.VERTICAL)
        time_box.append(min_spin)

        vbox.append(time_box)
        dialog.set_extra_child(vbox)

        def on_response(dialog, response):
            if response == "add":
                title = title_entry.get_text()
                selected_idx = category_dropdown.get_selected()
                category_str = CATEGORIES_LIST[selected_idx]

                gdate = calendar.get_date()
                year, month, day = gdate.get_year(), gdate.get_month(), gdate.get_day_of_month()
                hour, minute = hour_spin.get_value_as_int(), min_spin.get_value_as_int()
                
                local_dt = datetime(year, month, day, hour, minute)
                utc_dt = local_dt.astimezone(timezone.utc)
                
                self.save_local_event(title, utc_dt, category_str)

        dialog.connect("response", on_response)
        dialog.present()

    def save_local_event(self, title, event_dt, category_str):
        if not title: return

        cal = Calendar()
        if os.path.exists(self.local_file):
            with open(self.local_file, 'rb') as f:
                cal = Calendar.from_ical(f.read())
        else:
            cal.add('prodid', '-//Librem Local Calendar//')
            cal.add('version', '2.0')

        event = Event()
        event.add('summary', title)
        event.add('dtstart', event_dt) 
        event.add('categories', category_str) 
        cal.add_component(event)

        with open(self.local_file, 'wb') as f:
            f.write(cal.to_ical())

        self.load_all_events()

    # --- SYNC LOGIC ---
    def on_sync_clicked(self, button):
        self.trigger_sync()

    def on_sync_timer_tick(self):
        self.trigger_sync()
        return True

    def trigger_sync(self):
        if not self.PROTON_URL or not self.PROTON_URL.startswith("http"):
            return

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
                
            GLib.idle_add(self.load_all_events)
            
        except Exception as e:
            print(f"Network error (Offline?): {e}")
            GLib.idle_add(self.reset_sync_button)

    def reset_sync_button(self):
        self.sync_button.set_sensitive(True)
        self.sync_button.set_label("Sync")

    # --- PARSING & UI BUILDING ---
    def load_all_events(self):
        self.all_parsed_events = []
        now_utc = datetime.now(timezone.utc)
        today_date = now_utc.date()
        
        start_date = today_date - timedelta(days=self.past_days_filter)
        end_date = today_date + timedelta(days=365)

        def extract_events_from_file(filepath, is_local=False):
            if not os.path.exists(filepath): return
                
            try:
                with open(filepath, 'rb') as f:
                    cal = Calendar.from_ical(f.read())
                    
                events = recurring_ical_events.of(cal).between(start_date, end_date)
                
                for component in events:
                    dtstart = component.get('dtstart')
                    if not dtstart: continue
                        
                    dt_original = dtstart.dt
                    summary_original = str(component.get('summary', 'No Title'))
                    
                    summary = summary_original
                    if is_local:
                        summary = f"📱 {summary}"
                    
                    cat_obj = component.get('categories')
                    category = "Default"
                    if cat_obj:
                        try:
                            cat_str = cat_obj.to_ical().decode('utf-8')
                            category = cat_str.split(',')[0].strip()
                        except Exception:
                            category = str(cat_obj)
                            
                    icon_name = CATEGORY_MAP.get(category, CATEGORY_MAP["Default"])

                    if isinstance(dt_original, datetime):
                        sort_key = dt_original if dt_original.tzinfo else dt_original.astimezone(timezone.utc)
                    else:
                        sort_key = datetime(dt_original.year, dt_original.month, dt_original.day, tzinfo=timezone.utc)
                    
                    event_id = f"{summary}_{sort_key.isoformat()}"
                        
                    self.all_parsed_events.append({
                        'id': event_id,
                        'summary': summary,
                        'summary_original': summary_original, # Track original for editing
                        'dt': dt_original,
                        'dt_original': dt_original,           # Track original for finding it in .ics
                        'sort_key': sort_key,
                        'icon_name': icon_name,
                        'category_raw': category,
                        'is_local': is_local                  # Flag so we know if we are allowed to edit it
                    })
            except Exception as e:
                print(f"Error reading {filepath}: {e}")

        extract_events_from_file(self.cache_file, is_local=False)
        extract_events_from_file(self.local_file, is_local=True)
        
        self.all_parsed_events.sort(key=lambda x: x['sort_key'])
        self.refresh_ui()
        self.reset_sync_button()

    def refresh_ui(self):
        for box in (self.past_box, self.upcoming_box, self.completed_box):
            while child := box.get_first_child():
                box.remove(child)

        now_utc = datetime.now(timezone.utc)
        today_local = datetime.now().date()

        past_list = []
        upcoming_list = []
        completed_list = []

        for e in self.all_parsed_events:
            if e['id'] in self.completed_ids:
                completed_list.append(e)
            else:
                dt = e['dt']
                if isinstance(dt, datetime):
                    is_past = e['sort_key'] < now_utc
                else:
                    is_past = dt < today_local
                
                if is_past:
                    past_list.append(e)
                else:
                    upcoming_list.append(e)

        self.render_event_group(past_list, self.past_box, empty_msg="No past uncompleted events", is_completed_tab=False)
        self.render_event_group(upcoming_list, self.upcoming_box, empty_msg="No upcoming events", is_completed_tab=False)
        self.render_event_group(completed_list, self.completed_box, empty_msg="No completed events", is_completed_tab=True)

    def render_event_group(self, events_list, target_box, empty_msg, is_completed_tab=False):
        if not events_list:
            empty_label = Gtk.Label(label=empty_msg)
            empty_label.add_css_class("dim-label")
            empty_label.set_margin_top(24)
            target_box.append(empty_label)
            return

        grouped = {}
        for event in events_list:
            dt = event['dt']
            if isinstance(dt, datetime):
                local_dt = dt.astimezone() if dt.tzinfo else dt
                event_date = local_dt.date()
            else:
                event_date = dt
                
            date_label = event_date.strftime("%A, %B %d")
            
            if date_label not in grouped:
                grouped[date_label] = []
            grouped[date_label].append(event)

        for date_label, events_on_day in grouped.items():
            label = Gtk.Label(label=date_label)
            label.set_halign(Gtk.Align.START)
            label.add_css_class("title-4")
            label.set_margin_bottom(6)
            
            day_list = Gtk.ListBox()
            # Allow items to be selected/clicked so we can edit them
            day_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
            day_list.add_css_class("boxed-list")
            
            # Connect the click event for the whole list block
            day_list.connect("row-activated", self.on_row_activated)
            
            for event in events_on_day:
                dt = event['dt']
                if isinstance(dt, datetime):
                    local_dt = dt.astimezone() if dt.tzinfo else dt
                    time_str = local_dt.strftime("%H:%M")
                else:
                    time_str = "All Day"
                    
                row = Adw.ActionRow(title=event['summary'], subtitle=time_str)
                row.set_activatable(True) # Make row emit signals
                
                # Attach the raw dictionary directly to the row UI object 
                # so we know EXACTLY what data this row is referencing when clicked.
                row._event_data = event
                
                prefix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                
                check = Gtk.CheckButton()
                check.set_active(is_completed_tab)
                
                def on_toggle(btn, event_id=event['id']):
                    if btn.get_active():
                        self.completed_ids.add(event_id)
                    else:
                        self.completed_ids.discard(event_id)
                    self.save_completed_ids()
                    self.refresh_ui()

                check.connect("toggled", on_toggle)
                
                category_icon = Gtk.Image.new_from_icon_name(event['icon_name'])
                category_icon.add_css_class("dim-label") 
                
                prefix_box.append(check)
                prefix_box.append(category_icon)
                
                row.add_prefix(prefix_box)
                day_list.append(row)
                
            section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            section_box.append(label)
            section_box.append(day_list)
            target_box.append(section_box)


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
