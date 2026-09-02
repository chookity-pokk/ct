import os
import stat

def create_desktop_entry():
    # 1. Define paths
    current_dir = os.path.abspath(os.path.dirname(__file__))
    app_script_path = os.path.join(current_dir, "app.py")
    
    # Check if app.py actually exists here
    if not os.path.exists(app_script_path):
        print("Error: Could not find app.py in this directory.")
        return

    # 2. Define the target directory for the shortcut
    applications_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(applications_dir, exist_ok=True)
    
    desktop_file_path = os.path.join(applications_dir, "org.example.LibremCalendar.desktop")

    # 3. Define the .desktop file contents
    # We use the standard calendar icon and explicitly call python3
    desktop_entry = f"""[Desktop Entry]
Name=Librem Calendar
Comment=Custom Calendar App for Phosh
Exec=/usr/bin/python3 {app_script_path}
Icon=x-office-calendar-symbolic
Terminal=false
Type=Application
Categories=Office;Calendar;GTK;
StartupNotify=true
"""

    # 4. Write the file
    with open(desktop_file_path, "w") as f:
        f.write(desktop_entry)

    # 5. Make the .desktop file executable (required by some Linux environments)
    st = os.stat(desktop_file_path)
    os.chmod(desktop_file_path, st.st_mode | stat.S_IEXEC)

    print(f"Success! Launcher created at: {desktop_file_path}")
    print("You should now see 'Librem Calendar' in your Phosh app drawer.")

if __name__ == "__main__":
    create_desktop_entry()
