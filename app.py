import sys
import os
import json
import uuid
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

# --- RECURRENCE MAPPING ---
RECURRENCE_OPTIONS = ["None", "Daily", "Weekly", "Monthly", "Yearly"]
FREQ_MAP = {
    "None": None,
    "Daily": "DAILY",
    "Weekly": "WEEKLY",
    "Monthly": "MONTHLY",
    "Yearly": "YEARLY"
}

# --- PAST EVENT FILTER OPTIONS ---
PAST_FILTER_OPTIONS = ["Last 7 Days", "Last 30 Days", "Last 90 Days", "Last Year", "All Time"]
PAST_FILTER_DAYS = [7, 30, 90, 365, 3650] 


# --- FULL-SCREEN EVENT EDITOR ---
class EventEditorWindow(Adw.Window):
    def __init__(self, parent, event=None, on_save_cb=None, on_delete_cb=None, **kwargs):
        super().__init__(parent=parent, modal=True, **kwargs)
        self.set_default_size(360, 720)
        self.maximize()

        self.event = event
        self.on_save_cb = on_save_cb
        self.on_delete_cb = on_delete_cb

        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)
        
        self.set_title("New Event" if not event else "Edit Event")

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", self.on_cancel)
        header_bar.pack_start(cancel_btn)

        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self.on_save)
        header_bar.pack_end(save_btn)

        scrolled_window = Gtk.ScrolledWindow(vexpand=True)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        vbox.set_margin_top(24)
        vbox.set_margin_bottom(24)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)
        
        scrolled_window.set_child(vbox)
        toolbar_view.set_content(scrolled_window)

        # 1. Title Input
        self.title_entry = Gtk.Entry(placeholder_text="Event Title (e.g., Dentist)")
        vbox.append(self.title_entry)

        # 2. Category Dropdown
        category_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        category_box.set_halign(Gtk.Align.CENTER)
        category_box.append(Gtk.Label(label="Category:"))
        
        self.category_dropdown = Gtk.DropDown.new_from_strings(CATEGORIES_LIST)
        category_box.append(self.category_dropdown)
        vbox.append(category_box)
        
        # 3. Recurrence Dropdown
        recur_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        recur_box.set_halign(Gtk.Align.CENTER)
        recur_box.append(Gtk.Label(label="Repeats:"))
        
        self.recur_dropdown = Gtk.DropDown.new_from_strings(RECURRENCE_OPTIONS)
        recur_box.append(self.recur_dropdown)
        vbox.append(recur_box)

        # 4. Native Calendar Widget
        self.calendar = Gtk.Calendar()
        self.calendar.set_halign(Gtk.Align.CENTER)
        vbox.append(self.calendar)

        # 5. Time Pickers
        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        time_box.set_halign(Gtk.Align.CENTER)
        time_box.append(Gtk.Label(label="Time (24h):"))

        self.adj_hour = Gtk.Adjustment(lower=0, upper=23, step_increment=1)
        self.hour_spin = Gtk.SpinButton(adjustment=self.adj_hour, numeric=True, orientation=Gtk.Orientation.VERTICAL)
        time_box.append(self.hour_spin)

        time_box.append(Gtk.Label(label=":"))

        self.adj_min = Gtk.Adjustment(lower=0, upper=59, step_increment=5)
        self.min_spin = Gtk.SpinButton(adjustment=self.adj_min, numeric=True, orientation=Gtk.Orientation.VERTICAL)
        time_box.append(self.min_spin)

        vbox.append(time_box)

        # Populate Data (If Editing)
        if event:
            self.title_entry.set_text(event['summary_original'])
            
            try:
                idx = CATEGORIES_LIST.index(event['category_raw'])
            except ValueError:
                idx = 0
            self.category_dropdown.set_selected(idx)
            
            try:
                idx_recur = RECURRENCE_OPTIONS.index(event['freq_raw'])
            except ValueError:
                idx_recur = 0
            self.recur_dropdown.set_selected(idx_recur)

            dt_orig = event['dt_original']
            local_dt = dt_orig.astimezone() if isinstance(dt_orig, datetime) and dt_orig.tzinfo else dt_orig
            
            gdate = GLib.DateTime.new_local(local_dt.year, local_dt.month, local_dt.day, 0, 0, 0)
            self.calendar.select_day(gdate)
            
            if isinstance(dt_orig, datetime):
                self.adj_hour.set_value(local_dt.hour)
                self.adj_min.set_value(local_dt.minute)

            delete_btn = Gtk.Button(label="Delete Series" if event['freq_raw'] != "None" else "Delete Event")
            delete_btn.add_css_class("destructive-action")
            delete_btn.set_margin_top(24)
            delete_btn.connect("clicked", self.on_delete)
            vbox.append(delete_btn)
        else:
            self.adj_hour.set_value(datetime.now().hour)

    def on_cancel(self, button):
        self.close()

    def on_delete(self, button):
        if self.on_delete_cb and self.event:
            self.on_delete_cb(self.event)
        self.close()

    def on_save(self, button):
        title = self.title_entry.get_text()
        category = CATEGORIES_LIST[self.category_dropdown.get_selected()]
        recur_str = RECURRENCE_OPTIONS[self.recur_dropdown.get_selected()]

        gdate = self.calendar.get_date()
        year, month, day = gdate.get_year(), gdate.get_month(), gdate.get_day_of_month()
        hour, minute = self.hour_spin.get_value_as_int(), self.min_spin.get_value_as_int()
        
        local_dt = datetime(year, month, day, hour, minute)
        utc_dt = local_dt.astimezone(timezone.utc)
        
        if self.on_save_cb:
            self.on_save_cb(self.event, title, utc_dt, category, recur_str)
        self.close()


# --- MAIN APPLICATION WINDOW ---
class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Librem Calendar")
        self.set_default_size(360, 720)

        self.all_parsed_events = []

        self.app_id = 'org.example.LibremCalendar'
        self.cache_dir = os.path.join(GLib.get_user_cache_dir(), self.app_id)
        
        self.cache_file = os.path.join(self.cache_dir, 'cached_events.ics')
        self.local_file = os.path.join(self.cache_dir, 'local_events.ics')
        self.completed_file = os.path.join(self.cache_dir, 'completed_ids.json')
        self.config_file = os.path.join(self.cache_dir, 'config.json')
        os.makedirs(self.cache_dir, exist_ok=True)

        self.PROTON_URL, self.past_days_filter = self.load_config()
        self.completed_ids = self.load_completed_ids()

        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        self.add_button = Gtk.Button(icon_name="list-add-symbolic")
        self.add_button.connect("clicked", self.on_add_clicked)
        header_bar.pack_start(self.add_button)

        self.sync_button = Gtk.Button(label="Sync")
        self.sync_button.add_css_class("suggested-action")
        self.sync_button.connect("clicked", self.on_sync_clicked)
        header_bar.pack_end(self.sync_button)
        
        self.settings_button = Gtk.Button(icon_name="preferences-system-symbolic")
        self.settings_button.connect("clicked", self.on_settings_clicked)
        header_bar.pack_end(self.settings_button)

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

        switcher_bar = Adw.ViewSwitcherBar()
        switcher_bar.set_stack(self.view_stack)
        switcher_bar.set_reveal(True)
        toolbar_view.add_bottom_bar(switcher_bar)
        
        self.view_stack.set_visible_child_name("upcoming")

        self.load_all_events()
        GLib.timeout_add_seconds(3600, self.on_sync_timer_tick)
        if self.PROTON_URL:
            self.trigger_sync()

    def setup_box_margins(self, box):
        box.set_margin_top(18)
        box.set_margin_bottom(24)
        box.set_margin_start(12)
        box.set_margin_end(12)

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

    def on_add_clicked(self, button):
        editor = EventEditorWindow(parent=self, event=None, on_save_cb=self.save_or_update_event)
        editor.present()

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
            
        editor = EventEditorWindow(parent=self, event=event, on_save_cb=self.save_or_update_event, on_delete_cb=self.delete_event)
        editor.present()

    def save_or_update_event(self, old_event, title, dt, category, recur_str):
        if not title: return

        if old_event:
            self.update_local_event(old_event, new_title=title, new_dt=dt, new_category=category, new_recur=recur_str, delete=False)
        else:
            self.save_local_event(title, dt, category, recur_str)

    def delete_event(self, old_event):
        self.update_local_event(old_event, delete=True)

    def save_local_event(self, title, event_dt, category_str, recur_str):
        cal = Calendar()
        if os.path.exists(self.local_file):
            with open(self.local_file, 'rb') as f:
                cal = Calendar.from_ical(f.read())
        else:
            cal.add('prodid', '-//Librem Local Calendar//')
            cal.add('version', '2.0')

        event = Event()
        # Add a Universal ID so we can track this event across all its recurrences
        event.add('uid', str(uuid.uuid4()) + '@librem.local')
        event.add('summary', title)
        event.add('dtstart', event_dt) 
        event.add('categories', category_str) 
        
        freq = FREQ_MAP.get(recur_str)
        if freq:
            event.add('rrule', {'freq': freq})
            
        cal.add_component(event)

        with open(self.local_file, 'wb') as f:
            f.write(cal.to_ical())

        self.load_all_events()

    def update_local_event(self, old_event, new_title=None, new_dt=None, new_category=None, new_recur=None, delete=False):
        if not os.path.exists(self.local_file):
            return
            
        try:
            with open(self.local_file, 'rb') as f:
                cal = Calendar.from_ical(f.read())
                
            found_idx = -1
            old_uid = old_event.get('uid')
            
            for i, component in enumerate(cal.subcomponents):
                if component.name == 'VEVENT':
                    c_uid = str(component.get('uid', ''))
                    
                    # Search by exact UID first (New standard)
                    if old_uid and c_uid == old_uid:
                        found_idx = i
                        break
                    # Fallback to fuzzy searching for events created before this update
                    elif not old_uid:
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
                    del comp['summary']
                    del comp['dtstart']
                    if 'categories' in comp:
                        del comp['categories']
                    if 'rrule' in comp:
                        del comp['rrule']
                        
                    comp.add('summary', new_title)
                    comp.add('dtstart', new_dt)
                    comp.add('categories', new_category)
                    
                    freq = FREQ_MAP.get(new_recur)
                    if freq:
                        comp.add('rrule', {'freq': freq})
                    
                with open(self.local_file, 'wb') as f:
                    f.write(cal.to_ical())
                    
                self.load_all_events()
                
        except Exception as e:
            print(f"Error updating local event: {e}")

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
                    uid = str(component.get('uid', ''))
                    
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
                    
                    # Extract RRULE for the editor dropdown
                    freq_raw = "None"
                    rrule = component.get('rrule')
                    if rrule and 'FREQ' in rrule:
                        freq_val = rrule['FREQ'][0] if isinstance(rrule['FREQ'], list) else rrule['FREQ']
                        for k, v in FREQ_MAP.items():
                            if v == freq_val:
                                freq_raw = k
                                break

                    if isinstance(dt_original, datetime):
                        sort_key = dt_original if dt_original.tzinfo else dt_original.astimezone(timezone.utc)
                    else:
                        sort_key = datetime(dt_original.year, dt_original.month, dt_original.day, tzinfo=timezone.utc)
                    
                    event_id = f"{summary}_{sort_key.isoformat()}"
                        
                    self.all_parsed_events.append({
                        'id': event_id,
                        'uid': uid,
                        'summary': summary,
                        'summary_original': summary_original, 
                        'dt': dt_original,
                        'dt_original': dt_original,          
                        'sort_key': sort_key,
                        'icon_name': icon_name,
                        'category_raw': category,
                        'freq_raw': freq_raw,
                        'is_local': is_local                  
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
            # We track completion by the unique combination of name + EXACT timestamp.
            # This elegantly allows you to "Complete" a single day of a recurring event!
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
            day_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
            day_list.add_css_class("boxed-list")
            
            day_list.connect("row-activated", self.on_row_activated)
            
            for event in events_on_day:
                dt = event['dt']
                if isinstance(dt, datetime):
                    local_dt = dt.astimezone() if dt.tzinfo else dt
                    time_str = local_dt.strftime("%H:%M")
                else:
                    time_str = "All Day"
                    
                row = Adw.ActionRow(title=event['summary'], subtitle=time_str)
                row.set_activatable(True) 
                
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
                
                if event['freq_raw'] != "None":
                    recur_icon = Gtk.Image.new_from_icon_name("view-refresh-symbolic")
                    recur_icon.add_css_class("dim-label")
                    prefix_box.append(recur_icon)
                
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
