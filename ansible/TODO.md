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

## 2. [IN TESTING] Daily 20:00 wake from suspend (rtcwake)

**Old problem:** `set-wake.sh` ran from `set-wake.service` at boot only,
so a machine that was suspended rather than rebooted woke on the first
night and never armed another alarm.

**New approach:** a systemd timer instead of a script.
`daily-wake.timer` has `OnCalendar=*-*-* {{ rtcwake_wake_time }}:00`
(default 20:00, in the system timezone) and `WakeSystem=true`, so the
kernel programs the RTC alarm for the next run every time the machine
suspends. The alarm can't get lost between nights. `daily-wake.service`
only logs "Woke for daily sync". Syncthing is already running and picks
up once the network is back. Wakes from suspend only, never from
power-off (fine: laptops are shut down for travel). The role also
removes the old `set-wake` files and clears the alarm they armed.

**Status:**

- [x] Role rewritten and run on `testbox` (timer enabled, next run
  20:00, old units gone) and on `arnold` (provisioned 2026-11-24 15:22).
- [x] Timer fires: on `arnold`, "Woke for daily sync" at 20:00:12 on
  2026-11-24. But `arnold` was awake then (it never suspended, see #7),
  so this didn't test waking.
- [ ] **Wake from suspend.** Running now: `arnold` was left at the login
  screen at 20:09 on 2026-11-24, so it should idle-suspend around 21:10
  and wake at 20:00 on 2026-11-25. Expect a `suspend entry` around
  21:10, a `suspend exit` at 20:00:0x, then "Woke for daily sync".
- [ ] **Second night.** Let it suspend again after the wake and check it
  wakes the following 20:00 too (the case the old setup failed).

If idle suspend doesn't kick in, test the wake on its own: run
`sudo systemctl suspend` before 20:00 and leave it. A quicker check:
set `rtcwake_wake_time` a few minutes ahead, re-run the role, and
suspend.

To re-run just this role on one machine:

```sh
ansible-playbook playbooks/provision.yaml --tags rtcwake --limit <host>
```

To see exactly when it slept, woke and ran (`-o short-iso` for full
timestamps):

```sh
# when the timer's service ran (one line per run)
journalctl -t daily-wake -o short-iso

# when the machine suspended and resumed, this boot
journalctl -b -o short-iso -g 'PM: suspend (entry|exit)'

# both, in order, since yesterday (across reboots)
journalctl -o short-iso --since yesterday -g 'PM: suspend (entry|exit)|Woke for daily sync'

# last and next run of the timer
systemctl list-timers daily-wake.timer
```

"Woke for daily sync" without a `suspend exit` just before it means the
machine was already awake.

## 3. syncthing role follow-ups

The role currently does a basic install: package, generated config with
no default folder, GUI port/HTTPS, device name, and the
`syncthing@<user>` service. Folders (`Home-<user>`) are shared in from
another device and accepted by hand. Still to sort out:

- **Two users' instances both want port 22000.** Each user's
  `syncthing@<user>` uses the default listen address
  (`tcp://0.0.0.0:22000` + QUIC), so on a machine with two Syncthing
  users only one can bind it. The other fails to listen on it or picks
  something else, and with ufw on, anything other than 22000 is
  blocked from the LAN, so it falls back to relays. Confirmed on
  `testbox`: `charisis` got 22000, `aharisis` a random port (34569),
  which ufw blocks from the LAN. Check with
  `sudo ss -tulnp | grep syncthing`. Fix: a per-user sync port in
  `group_vars` (like `syncthing.port` for the GUI), written to
  `config.xml`'s listen address, and opened by
  `roles/syncthing/tasks/firewall.yaml` instead of the fixed 22000.
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

## 4. preferences role: editor and gitconfig tasks aren't wired in

`roles/preferences/tasks/main.yaml` only imports `location.yaml`.
`editor.yaml` (vim as default editor, `EDITOR`/`VISUAL` in
`/etc/profile.d`) and `git.yaml` (a `~/.gitconfig` from each user's
`git:` entry in `group_vars`, needs `user`, `git_user_name` and
`git_user_email`) are in the role but not imported from `main.yaml`
yet. Decide whether to import them (git per user), fold them into other
roles, or drop them. Things to look at first:

- **It overwrites `~/.gitconfig` completely**, from a template holding
  only `user.name` and `user.email`, so any other git settings a user
  has are lost on every run. `community.general.git_config` would set
  just those two keys.
- **`vim` is installed twice.** It's already in `apt_packages_list`.
- **`editor.yaml` is machine-wide** and doesn't need a user, so it can
  be imported unconditionally, like `location.yaml`. `git.yaml` has to
  run once per user.

## 5. Disk usage warnings

Get warned when `/` or `/home` fills up past a threshold. Not quotas:
those block writes, and count per user by file owner, which isn't the
goal. Done through node_exporter (#6) and an alert rule on the existing
Prometheus, e.g.:

```promql
# over 85% full for 15 minutes
(1 - node_filesystem_avail_bytes{mountpoint=~"/|/home", fstype="ext4"}
   / node_filesystem_size_bytes{mountpoint=~"/|/home", fstype="ext4"}) * 100 > 85

# on track to fill within 7 days, based on the last 6 hours
predict_linear(node_filesystem_avail_bytes{mountpoint=~"/|/home", fstype="ext4"}[6h], 7*24*3600) < 0
```

A sleeping machine sends no data, so these don't fire while it's
suspended. Machines installed before the 100G / + 300G /home layout only
have `/`.

## 6. [IN TESTING] Install node_exporter

Done: `roles/node_exporter`, opt-in per host (`node_exporter_enabled:
true` in `host_vars`). It installs Ubuntu's `prometheus-node-exporter`
without recommends (no `prometheus-node-exporter-collectors` timers
running `smartctl`/apt checks as root), and adds a ufw rule allowing
9100/tcp only from `node_exporter_allow_from` (default: the Tailscale
range). Setting it back to false removes the rule and the package.
Tested on `testbox`: metrics served locally, 9100 blocked from the LAN,
second run unchanged, disabling cleans up.

Still to do:

- **Scrape it from Prometheus on `conglomerate`.** Needs the host on
  Tailscale (`sudo tailscale up`), then the host's Tailscale name/IP and
  port 9100 added as a target in Prometheus.
- **Narrow `node_exporter_allow_from`** to conglomerate's Tailscale IP
  instead of the whole tailnet range.
- **Disk usage alerts (#5)** build on this.
- Machines suspend nightly (#7 power settings), so a "host down" alert
  has to allow for expected sleep.

Security notes, for reference: node_exporter has no auth and listens on
all interfaces, so the ufw rule is the only thing limiting access. The
metrics reveal hostname, kernel and package versions, filesystems,
network interfaces and running units. Binding it to the Tailscale
address instead is fragile (it can start before Tailscale and fail).

## 7. [IN TESTING] System-wide settings: timezone, location, power

Timezone is the first task in `provision.yaml` (tag `timezone`,
`system_timezone` in `group_vars`) and `timezone:` in the autoinstall
templates. Location and power are dconf system defaults (not locked)
from the `preferences` role (`location.yaml`, `power.yaml`). A timezone
change restarts the daily wake timer (#2).

Done:

- [x] Timezone set to `America/New_York`: verified on `testbox` and on
  `arnold` (times shown in EST).
- [x] dconf profile and `local.d` keyfiles installed and compiled
  (`dconf update`) on `testbox` and `arnold`.
- [x] Power defaults take effect: on `arnold`, `gsettings` for
  charisis, aharisis **and the GDM login screen** shows suspend after
  3600s on AC / 900s on battery, screen off after 300s. (The login
  screen does pick these up, contrary to what was assumed earlier.)
- [x] Screen blanks and locks after 5 min idle (`arnold`, 2026-11-24).
- [x] Second provision run reports no changes for these tasks.

Still to do:

- [ ] **Idle suspend didn't happen.** On 2026-11-24, `arnold` sat in
  charisis's desktop session idle from about 15:30 to 20:09 and never
  suspended. Likely cause: that session started at 15:10, before
  provision wrote the defaults at 15:22, and `gsd-power` kept the
  values it read at login. Not provable after the fact; an app holding
  a sleep inhibitor is the other possibility (`systemd-inhibit --list`
  while it happens). Being re-tested at the login screen (see #2). If
  confirmed, note in Setup.md that a session open during provisioning
  needs a log out and back in.
- [ ] **Users' own values shadow the defaults.** charisis's and
  aharisis's user dconf on `arnold` hold the same power keys
  (`dconf dump /org/gnome/settings-daemon/plugins/power/`). They match
  today, but a later change to `power.yaml` wouldn't reach them. Decide
  whether to `dconf reset` those keys, lock them (`locks/`), or leave
  them.
- [ ] Location services: check `gsettings get org.gnome.system.location
  enabled` is `true` as a user.
- [ ] Fresh install from a rebuilt ISO comes up in `America/New_York`.
- [ ] Left for later: regional formats (`locale`), lid behaviour,
  automatic timezone on laptops only, and moving the timezone task into
  the `preferences` role.

To re-run on one machine:

```sh
ansible-playbook playbooks/provision.yaml --tags timezone,preferences --limit <host>
```

## 8. Syncthing exporter proxy

Expose each user's Syncthing metrics to Prometheus, alongside
node_exporter (#6). Notes for when this is picked up:

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
