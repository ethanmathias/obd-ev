# Deployment guide (researcher)

This describes how to build a master SD card image, then customize it for each
participant kit.

## One-time master image

Do this once. The result is a Pi with all software installed, BLE OBD adapter
settings in `config.yaml`, and rclone authenticated against your shared cloud
folder.

1. **Flash Raspberry Pi OS Lite (64-bit).** Use `rpi-imager`. Set any
   username, enable SSH, and configure your *own* WiFi (not the
   participant's) so you can finish setup over the network. The setup script
   installs services for whichever user runs it.

2. **Clone and provision.**
   ```bash
   ssh <username>@raspberrypi.local
   git clone https://github.com/ethanmathias/obd-ev
   cd obd-ev
   ./scripts/setup_pi.sh
   sudo reboot
   ```

3. **Configure the BLE OBD adapter and rclone.**
   Copy the example config and set the adapter address if you know it:
   ```bash
   cp -n config.yaml.example config.yaml
   nano config.yaml
   ```
   In `config.yaml`, set:
   ```yaml
   obd:
     ble_address: 8C:DE:52:DD:FD:37   # your adapter MAC, or null to discover by name
     ble_name: VEEPEAK
   ```
   Then configure cloud upload:
   ```bash
   ./scripts/image_setup.sh
   ```
   - For `rclone config`, name the remote **`obd-ev`** and pick `box` or
     `drive`. The OAuth flow will give you a URL — open it in a browser on
     your laptop and paste back the auth code.
   - Verify with `rclone lsd obd-ev:`.

4. **Test the full pipeline.**
   ```bash
   sudo systemctl start obd-ev
   journalctl -u obd-ev -f
   ```
   Confirm a CSV appears in `~/obd-ev/logs/`. Then:
   ```bash
   sudo systemctl start obd-ev-upload
   ```
   Confirm the file shows up in your cloud folder and is moved to
   `logs/uploaded/` locally.

5. **Shut down and clone the SD card.** Use `dd`, Pi Imager, or
   [PiShrink](https://github.com/Drewsif/PiShrink) to capture the image.

## Per-participant customization

For each kit:

1. Flash the master image to a fresh SD card.
2. Mount the SD card on your laptop. The boot partition will be visible.
3. Copy `obd-ev-wifi.conf.example` from the repo into the boot partition,
   rename to **`obd-ev-wifi.conf`**, and fill in the participant's home WiFi
   SSID and password. Multiple networks are supported — see the file.
4. (Optional) Edit `/etc/default/obd-ev` on the rootfs to set
   `OBD_EV_DEVICE_ID=P003` (or however you tag participants). This shows up
   in every CSV row and in the uploaded filename, so logs from many kits
   don't get confused.
5. Eject and ship.

## What the Pi does on first power-up

1. Boots, NetworkManager starts.
2. `obd-ev-firstboot.service` reads `/boot/firmware/obd-ev-wifi.conf`,
   creates connection profiles, renames the file to `.applied` so it doesn't
   re-process.
3. `obd-ev.service` starts logging. Retries BLE OBD connection every 15s if the
   car isn't running yet.
4. `obd-ev-upload.timer` fires every minute. When the Pi is in WiFi range
   at home, pending CSVs upload to the configured rclone remote.

## When a kit comes back

```bash
ssh <username>@<device>
cd ~/obd-ev/logs/uploaded
rm *.csv         # already in the cloud
sudo journalctl --vacuum-time=1d
```

Then re-flash the SD card and re-personalize for the next participant.
