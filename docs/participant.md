# Participant quick-start

What's in your kit and how to use it.

## What's in the box

- Raspberry Pi (the small computer) with SD card pre-installed
- Bluetooth OBD-II scanner (the small dongle)
- USB-C car power adapter
- GPS antenna and IMU sensor (already wired to the Pi)

## First-time setup (one minute)

You only need to do this once, before the first drive:

1. **Pop the SD card out of the Pi.** It's the small card sticking out of
   the side. Push it in to release.
2. **Plug the SD card into your computer** with the included adapter. A
   drive named `bootfs` will appear.
3. **Open the file `obd-ev-wifi.conf`** on that drive in any text editor
   (Notepad, TextEdit, anything).
4. Replace the example values with your home WiFi:
   ```
   ssid=YourHomeWiFiName
   psk=YourWiFiPassword
   ```
5. Save the file, eject the drive, and put the SD card back in the Pi.

## Using it

1. Plug the OBD-II scanner into the port under your dashboard (usually below
   the steering wheel).
2. Plug the Pi into the car's power outlet using the included USB-C adapter.
3. Drive normally. There's nothing to press or check — the device records
   automatically while the car is running.
4. When you park at home, the device automatically uploads its data over your
   home WiFi.

You can leave everything plugged in between drives. The device only records
when the car is running.

## Troubleshooting

- **Light not on?** Check the USB-C adapter is firmly seated.
- **Worried it's not working?** It is — there are no lights or beeps to confirm
  recording. Just drive normally and the data uploads when you get home.
- **Switching WiFi networks?** Contact the researcher. Don't try to reconfigure
  yourself — easier to swap the SD card.

## Privacy

This device records vehicle telemetry (speed, RPM, GPS) only. It does not
record audio, video, or anything from your phone.
