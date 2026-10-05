#!/bin/bash

echo "Installing Librem Calendar Notification Daemon..."

# 1. Define paths
DAEMON_SOURCE="daemon.py"
BIN_DIR="$HOME/.local/bin"
DAEMON_DEST="$BIN_DIR/librem_calendar_daemon.py"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_DIR/librem-calendar-daemon.service"

# 2. Check if daemon.py actually exists in the folder
if [ ! -f "$DAEMON_SOURCE" ]; then
    echo "Error: '$DAEMON_SOURCE' not found."
    echo "Please run this script from the folder containing daemon.py"
    exit 1
fi

# 3. Create the necessary hidden system directories
mkdir -p "$BIN_DIR"
mkdir -p "$SYSTEMD_DIR"

# 4. Copy the Python script into the user's bin folder
cp "$DAEMON_SOURCE" "$DAEMON_DEST"
chmod +x "$DAEMON_DEST"
echo "  -> Copied daemon.py to $BIN_DIR"

# 5. Generate the systemd service file
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
echo "  -> Created systemd service file at $SERVICE_FILE"

# 6. Register, enable, and start the systemd service
echo "  -> Registering daemon with systemd..."
systemctl --user daemon-reload
systemctl --user enable librem-calendar-daemon.service
systemctl --user restart librem-calendar-daemon.service

echo ""
echo "✅ Installation complete! Systemd is now running the daemon."
