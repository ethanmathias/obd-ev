# Participant quick-start

What's in your kit and how to use it.

## What's in the box

- A small computer (Raspberry Pi) with a card already inside it
- A Bluetooth OBD-II scanner (the small dongle)
- A USB-C car power adapter
- GPS and motion sensors, already wired to the computer
- A label on the device with a **setup password** — you'll need it once

## First-time setup (about a minute)

You only do this once, before your first drive. Do it at home, where the
device can reach your home WiFi.

1. **Plug the device into your car's USB-C power** and wait about a minute.
2. On your phone, **open WiFi settings**. Join the network named
   **`OBD-EV-Setup-…`** using the setup password printed on the device label.
3. A setup page should open by itself. If it doesn't, open a browser and go to
   **http://10.42.0.1**
4. **Choose your home WiFi** from the list and type your WiFi password.
5. Tap **Connect**. The setup network will disappear — that's what should
   happen. If nothing else happens, you're done.

If the password was mistyped, the `OBD-EV-Setup-…` network comes back after
about a minute. Rejoin it and try again.

### About your WiFi password

Your WiFi password is **not** sent to the researchers and is **not** stored on
the device.

When you tap Connect, your phone scrambles the password into a code that works
only for your one network and cannot be turned back into your password. Only
that code is sent to the device. So even if the device were lost or opened up,
your password could not be read off it — which matters most if you use that
password anywhere else.

The one exception: a small number of newer "WPA3-only" networks can't be joined
this way. If yours is one, the setup page says so on screen before you continue,
so the choice is yours.

## Using it

1. Plug the OBD-II scanner into the port under your dashboard (usually below
   the steering wheel).
2. Plug the device into the car's power outlet using the included USB-C adapter.
3. Drive normally. There's nothing to press — it records automatically while
   the car is running.
4. When you park at home, it uploads by itself over your home WiFi. Leaving the
   device powered for a few minutes after parking gives it time to finish.

You can leave everything plugged in between drives.

## Troubleshooting

- **No `OBD-EV-Setup-…` network?** It only appears until setup is finished. If
  you've already set it up, this is normal. If you haven't, unplug the device,
  wait ten seconds, plug it back in, and check again after a minute.
- **Setup page won't open?** Make sure your phone is joined to the
  `OBD-EV-Setup-…` network, then go to http://10.42.0.1 directly. Turning off
  mobile data for a moment can help, as phones sometimes prefer it.
- **Worried it isn't working?** There are no lights or beeps to confirm
  recording. Just drive normally.
- **Changed your WiFi password, or moved?** Contact the researcher. The device
  needs to be put back into setup mode.
- **Light not on?** Check the USB-C adapter is firmly seated.

## Privacy

The device records vehicle data (things like speed, battery state, pedal and
steering position) together with **GPS location**, so your routes and the
places you park — including your home — are part of the recorded data. It does
not record audio, video, or anything from your phone.

Your WiFi password is never recorded, in any form that could be read back.

If you have questions about how the location data is stored, retained, or
shared, ask the researcher for the study's consent documentation.
