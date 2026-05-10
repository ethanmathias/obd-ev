# Deployment guide (researcher)

This describes how to build a master SD card image, then customize it for each
participant kit.

## One-time master image

Do this once. The result is a Pi with all software installed, the OBD adapter
paired, and rclone authenticated against your shared cloud folder.

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

3. **Pair the OBD adapter and configure rclone.**
   ```bash
   cd obd-ev
   ./scripts/image_setup.sh
   ```
   - Follow prompts. The OBD adapter must be powered (plugged into a car or a
     12V bench supply) and in pairing mode.
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
3. `obd-ev-pair.service` binds the (already-paired) ELM327 to `/dev/rfcomm0`.
4. `obd-ev.service` starts logging. Retries OBD connection every 15s if the
   car isn't running yet.
5. `obd-ev-upload.timer` fires every minute. When the Pi is in WiFi range
   at home, pending CSVs upload to the configured rclone remote.

## When a kit comes back

```bash
ssh <username>@<device>
cd ~/obd-ev/logs/uploaded
rm *.csv         # already in the cloud
sudo journalctl --vacuum-time=1d
```

Then re-flash the SD card and re-personalize for the next participant.
