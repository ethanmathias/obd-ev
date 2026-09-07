# Cloud upload setup (researcher)

**Box is fine. Keep it.** The interactive `rclone config` flow is the easiest
option and there is no reason to abandon it.

There is exactly one rule that makes it work across a fleet:

> **Every kit needs its own authorization.** Building each card from scratch
> with `scripts/setup_kit.sh` does this automatically.

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

## You get this for free

`scripts/setup_kit.sh` builds each SD card from scratch, and step 4 of that
script runs `rclone config` on that card. So each kit ends up with its own
credential without you doing anything extra, and the failure above cannot
happen. The script also runs a real test upload before declaring the kit ready.

Name the remote exactly **`obd-ev`** when it prompts, and pick `box`. The Pi
has no browser, so answer **n** to "Use auto config?" and run the command it
prints on your laptop.

## The one case that still needs care

If you *clone* a finished card instead of building a new one, both copies hold
the same token and one will stop uploading. Give the copy its own:

```bash
./scripts/authorize_kit.sh
```

It re-runs the login for that kit only, refuses to pass if the token did not
actually change, and verifies a real upload.

### Confirming no two kits share a credential

Each kit records a short fingerprint of its token — never the token itself:

```bash
cat /var/lib/obd-ev/upload-authorized.json
```

```json
{
 "device_id": "P003",
 "token_fingerprint": "06ef1fb86217",
 "authorized_at": "2026-09-07T10:22:41-04:00"
}
```

Note it in your build log per card. **Every kit must show a different one.**

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
