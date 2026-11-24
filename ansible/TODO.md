# Known issues

## 1. SSH password auth is a race condition against the shared bootstrap password

`bootstrap.yaml` sets the same typed-in password on every configured
account, then runs `passwd --expire` to force a change at next login.
That doesn't close the window it looks like it closes: PAM still accepts
the shared password over SSH, it just forces a password-change prompt
*after* authenticating - so anyone who knows the shared password (the
same one on every bootstrapped machine, until each account's real owner
gets to it) could SSH in and be the one who sets the account's real
password, before its intended owner does.

The fix is disabling SSH password authentication entirely, so the first
login (and forced password change) has to happen at the console instead
of over the network - real accounts should end up using SSH keys anyway.
Tried adding this to the `users` role as a drop-in at
`/etc/ssh/sshd_config.d/00-disable-password-auth.conf` (named to sort
before any other drop-in, e.g. cloud-init's, since sshd processes
`Include`d files before the rest of sshd_config and keeps the *first*
value it sees per directive - confirmed that ordering on a real
sshd_config: `Include` is on line 24, well before any inline
`PasswordAuthentication`).

What's unresolved: the task used `validate: /usr/sbin/sshd -t -f %s`,
which is broken for a minimal drop-in - `sshd -t -f` treats the file as
a *complete* standalone config, and a fragment with just
`PasswordAuthentication no` has no `HostKey` directives, so validation
fails immediately (confirmed: `sshd: no hostkeys available -- exiting`).
Needs either a different validation approach (e.g. validate against the
real merged config, not the fragment alone) or dropping `validate`
entirely and relying on the restart handler failing loudly if the config
is actually bad.

## 2. rtcwake only wakes a suspended machine once per boot

All workstations are meant to wake at 20:00 every day so Syncthing can
sync. `set-wake.sh` works out the next 20:00 correctly, but it only runs
from `set-wake.service` at boot (`WantedBy=multi-user.target`). Resuming
from suspend doesn't re-run it, and `After=network.target` only orders
it at boot; it doesn't trigger it when the network comes back. So a
machine that's suspended instead of rebooted wakes on the first night,
then never sets another alarm and stays asleep every night after, until
it's rebooted.

Fix options:

- **A.** Keep `set-wake.sh` and add a hook in
  `/usr/lib/systemd/system-sleep/` that runs it before every suspend.
- **B.** Replace the script and service with a systemd timer
  (`OnCalendar=*-*-* 20:00`, `WakeSystem=true`). systemd re-arms the
  wake on every suspend itself. It only wakes from suspend, never from
  power-off. Preferred: less code, and nothing is left armed at shutdown.

Not yet confirmed on a real machine. To check, suspend for a minute
(`sudo rtcwake -m mem -s 60`), then `journalctl -u set-wake.service`
should show no new run after resume.

Once fixed, also drop the `util-linux` task (always installed on Ubuntu)
and `After=network.target` from the role.

## 3. Machines run in UTC, so "20:00" is 20:00 UTC

The autoinstall template doesn't set a timezone, so installed machines
default to UTC, and `rtcwake_wake_time` is read in UTC. Arnold's alarm
was confirmed set for `20:00 UTC`. Set `timezone:` in
`../autoinstall/autoinstall.yaml.template` for new installs, and add an
Ansible task to set it on existing machines.

## 4. syncthing role follow-ups

The role currently does a basic install: package, generated config with
no default folder, GUI port/HTTPS, device name, and the
`syncthing@<user>` service. Folders (`Home-<user>`) are shared in from
another device and accepted by hand. Still to sort out:

- **`.stignore` is manual.** Each user's `~/.stignore` is written by
  hand and copied to each machine. Syncthing never syncs it. It's what
  keeps `~/.local/state/syncthing` (private key, config, database) and
  other dotfiles out of the `Home-<user>` share, so it must be in place
  **before** accepting that share on a new machine. Decide how the role
  should manage it.
- **Restarts on every run.** "Stop Syncthing before changing config"
  runs unconditionally and `service.yaml` starts it again, which
  interrupts syncing and always reports "changed". Replace with a
  restart that only fires when `config.xml` actually changes. Handlers
  run once per play, not per loop iteration, so it needs to track which
  users changed.
- **Device-name task can rename the wrong device.** It targets
  `device[1]`, which is only the local device in a freshly generated
  config. A check-mode run showed it would change a name in
  `aharisis`'s config on arnold, likely another device. Match on the
  local device ID instead (`syncthing --device-id --home=...`).
- **Lingering isn't needed.** `syncthing@<user>` is a system unit
  (`/usr/lib/systemd/system/syncthing@.service`), so it starts at boot
  without `loginctl enable-linger`. Drop the task.
- **`syncthing_directory` is now mostly unused.** It only feeds
  "Ensure configured Syncthing directory exists" (the home directory,
  `0750`). Remove it from the role, `provision.yaml` and `group_vars`.
- **Minor:** the install task refreshes the apt cache every run; add
  `cache_valid_time`.

## 5. preferences role isn't wired in

`roles/preferences` (vim as default editor, `EDITOR`/`VISUAL` in
`/etc/profile.d`, and a per-user `~/.gitconfig` from each user's `git:`
entry in `group_vars`) isn't called from any playbook. Its commented-out
block was removed from `provision.yaml`. Decide whether to wire it back
in, fold it into other roles, or delete it. Things to look at first:

- **It overwrites `~/.gitconfig` completely**, from a template holding
  only `user.name` and `user.email`, so any other git settings a user
  has are lost on every run. `community.general.git_config` would set
  just those two keys.
- **`vim` is installed twice.** It's already in `apt_packages_list`.
- **Editor settings are machine-wide**, not per user, even though the
  role is run once per user.

## 6. Disk quotas on home directories

Add per-user disk quotas on `/home`. Notes for when this is picked up:

- Only machines installed with the current autoinstall layout have a
  separate `/home` LV (300G). Older installs have `/home` on `/`, where
  quotas would cover the whole root filesystem.
- ext4 options: enable the built-in quota feature on the filesystem
  (`tune2fs -O quota`, needs it unmounted), or mount with `usrquota`.
  Then set limits per user with `setquota` (from the `quota` package).
- Decide where limits live, e.g. a `quota:` entry per user in
  `group_vars`, alongside `syncthing:`.

## 7. Install node_exporter

Install Prometheus `node_exporter` on the workstations for monitoring.
Notes for when this is picked up:

- Ubuntu packages it as `prometheus-node-exporter`. The
  `prometheus.prometheus` collection also has a `node_exporter` role, if
  more control over version and flags is needed.
- It listens on port 9100 on all interfaces by default, with no auth.
  Consider binding it to the Tailscale address only, or firewalling it.

## 8. System-wide settings: timezone, location, power

Set machine-wide defaults from Ansible instead of by hand on each
machine. Probably a new role (e.g. `system_settings`) in `provision.yaml`.

- **Timezone.** `community.general.timezone`. Fixes #3 on existing
  machines. Also set `timezone:` in the autoinstall template for new
  installs.
- **Location.** GNOME location services on/off, and regional formats
  (`locale`, e.g. date and number formats). Decide which of these is
  meant.
- **Power.** GNOME auto-suspend timeouts (on AC / on battery), screen
  blank, and lid behaviour. These interact with rtcwake (#2): after the
  20:00 wake, auto-suspend decides how long Syncthing gets before the
  machine sleeps again.

The GNOME settings are per user by default. To set them machine-wide,
use dconf system defaults (`/etc/dconf/db/local.d/` plus `dconf
update`), with locks in `locks/` for anything users shouldn't change.

## 9. Syncthing exporter proxy

Expose each user's Syncthing metrics to Prometheus, alongside
node_exporter (#7). Notes for when this is picked up:

- Syncthing's GUI/API is bound to `127.0.0.1` on a per-user port
  (`syncthing.port` in `group_vars`, e.g. 8384, 8385) with HTTPS, and
  requires the API key. So Prometheus can't scrape it directly. That's
  what the proxy is for.
- Options: a small reverse proxy per user that listens on a reachable
  address and adds the `X-API-Key` header, or a standalone Syncthing
  exporter that queries the REST API and serves its own `/metrics`.
  Check which metrics recent Syncthing serves natively (`/metrics`)
  before picking one.
- The API key lives in each user's `config.xml` (`<gui><apikey>`), so
  the role would read it from there or set a known one.
- Same exposure concern as node_exporter: bind to the Tailscale
  address or firewall it, since the API key grants full control of
  that user's Syncthing.
