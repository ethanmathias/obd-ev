# Cloud upload setup (researcher)

**Box is fine. Keep it.** The interactive `rclone config` flow is the easiest
option and there is no reason to abandon it.

There is exactly one rule that makes it work across a fleet:

> **Every kit needs its own authorization.** Authorize once on the master image
> to prove the setup works, then re-authorize each SD card after flashing.

## Why that rule exists

Box and Google Drive both use OAuth **refresh tokens**, and both *rotate* them:
each time a device refreshes, it receives a replacement token and the old one
stops working.

Clone one authorized image onto twenty cards and all twenty hold the same
token. The first kit to reach home WiFi refreshes, gets a new token, and
invalidates the copy the other nineteen are holding. Those nineteen stop
uploading — with no error anyone sees, because the kits are unattended and the
failure happens weeks after imaging.

Giving each kit its own token costs about a minute per card and removes the
problem entirely. Nothing else about Box changes.

## 1. Master image — once

```bash
./scripts/image_setup.sh
```

Choose `box`, name the remote **`obd-ev`**, complete the browser login, and
verify:

```bash
rclone lsd obd-ev:
rclone mkdir obd-ev:obd-ev-uploads
```

Then bake the image. This authorization is a template — every card will replace
it.

## 2. Each SD card — once per kit

After flashing and setting `OBD_EV_DEVICE_ID` in `/etc/default/obd-ev`:

```bash
./scripts/authorize_kit.sh
```

It re-runs the Box login for this kit only, then verifies a real upload. The Pi
has no browser, so rclone prints a command to run on your laptop and you paste
the result back — the same flow you already used, just repeated per card.

The script refuses to pass if the token did not actually change, which is the
one mistake that silently recreates the original problem.

### Confirm no two kits share a credential

Each run records a short fingerprint of that kit's token (never the token
itself):

```bash
cat /var/lib/obd-ev/upload-authorized.json
```

```json
{
 "device_id": "P003",
 "remote": "obd-ev:obd-ev-uploads",
 "token_fingerprint": "06ef1fb86217",
 "authorized_at": "2026-09-04T10:22:41-04:00"
}
```

Note the fingerprint in your build log as you image each card. **Every kit must
show a different one.** Two matching kits means one was cloned after being
authorized, and one of them will stop uploading.

## Two Box caveats to plan around

**Refresh tokens expire after ~60 days without use.** A kit uploads every time
the participant parks at home, so this is a non-issue in normal operation — but
a kit that sits unplugged for two months (participant travelling, study paused)
will need re-authorizing before it works again. Worth confirming the exact
window with UVA Box, and worth a line in your participant instructions asking
them to leave the device powered.

**Re-imaging requires re-authorizing.** Anything that replaces the SD card
contents also replaces the token, so `authorize_kit.sh` runs again.

If either becomes painful — a long study, or many kits — the durable fix is a
**Box JWT app**, which uses a server-side key with no user token and no expiry.
It needs approval from whoever administers UVA's Box enterprise, so it is worth
starting that conversation only if per-kit OAuth proves annoying in the pilot.

## If you ever need to move off Box

`rclone` abstracts the destination, so migrating is one line in
`/etc/default/obd-ev`. Nothing in the logger changes.

**Google service account** — a JSON key file with no expiry. Note that an
**API key** (`AIzaSy...`) is a different thing and cannot do this at all: it
carries no identity and cannot upload. If you created one, delete it. A service
account also requires a Google **Shared Drive**, not a My Drive folder, because
service accounts have no storage quota of their own and uploads into a personal
folder eventually fail with a quota error.

**S3-compatible** (Backblaze B2, AWS, or a university bucket) — the only option
supporting genuinely per-kit credentials that you can revoke individually:

```bash
rclone config create obd-ev b2 account=<keyID> key=<applicationKey>
```

**SFTP to a lab server** — keeps GPS traces on university infrastructure, which
is easier to defend to an IRB, and revoking one kit is deleting one line from
`authorized_keys`. Needs a server reachable from participants' homes, and an
account that is *not* your personal one.

## Fleet hygiene

**Never commit credentials.** `.gitignore` covers `rclone.conf`, `*-sa.json`
and `service-account*.json`, but check before pushing — a key in a public repo
is scraped within minutes.

**Retention and access.** The uploaded data contains continuous GPS traces, so
participants' home addresses are directly inferable. Restrict the Box folder to
the study team and make sure retention matches what your consent documentation
promises.
