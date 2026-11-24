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

## 3. syncthing role follow-ups

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

## 6. Install node_exporter

Install Prometheus `node_exporter` for monitoring. Ubuntu packages it as
`prometheus-node-exporter`; installing it enables and starts the
service, so adding it to `apt_packages_list` alone would work, but
leaves it open (see below). The `prometheus.prometheus` collection also
has a `node_exporter` role, if more control over version and flags is
needed.

**Security concerns:**

- **Open to the whole network, no auth.** By default it listens on port
  9100 on every interface. Anyone on the same LAN, or on any network a
  laptop joins (hotel or café Wi-Fi), can read `/metrics`.
- **What it reveals.** Not secrets, but useful reconnaissance: hostname,
  kernel and package versions, mounted filesystems, network interfaces
  and addresses, running systemd units.
- **Binding to the Tailscale address is fragile.** node_exporter can
  start before Tailscale is connected, and then fails to start. Prefer
  a firewall rule.
- **Extra collectors come with it.** apt installs recommends, so
  `prometheus-node-exporter-collectors` is pulled in, with systemd
  timers running things like `smartctl` and apt checks as root. Use
  `install_recommends: false` unless those metrics are wanted.
- **Every host running it is another listening service** to keep
  patched and firewalled.

**Plan:**

- A small `node_exporter` role, opt-in per host
  (`node_exporter_enabled: true` in `host_vars`).
- ufw rule allowing 9100 only from Tailscale (`100.64.0.0/10`), and
  scrape over Tailscale, so it doesn't matter which network a machine
  is on.
- Start with always-on machines (desktops, KVM hosts). Leave laptops
  out until there's a reason.

Prometheus and Grafana already run elsewhere. Disk usage alerts (#5)
build on this. Machines suspend nightly (#7 power settings), so a "host
down" alert has to allow for expected sleep.

## 7. [IN TESTING] System-wide settings: timezone, location, power

Implemented, not yet tested on a real machine:

- **Timezone.** Fixed `America/New_York` everywhere: `system_timezone`
  in `group_vars`, set by the first task in `provision.yaml` (tag
  `timezone`), and `timezone:` in the autoinstall template. A change
  re-runs rtcwake's `Run set-wake` handler so the armed alarm moves.
- **Location services.** Enabled by default (not locked) via dconf in
  the `preferences` role (`location.yaml`).
- **Power.** Via dconf in the `preferences` role (`power.yaml`): screen
  off after 5 min, suspend after 15 min idle on battery and 1 hour on
  AC. After rtcwake's 20:00 wake (#2), Syncthing gets about an hour on
  AC before the machine sleeps again.

To test on one machine:

```sh
ansible-playbook playbooks/provision.yaml --tags timezone,preferences --limit <host>
```

- `timedatectl` shows `America/New_York`, and
  `date -d @$(cat /sys/class/rtc/rtc0/wakealarm)` shows 20:00 local.
- As a user on that machine, `gsettings get org.gnome.system.location
  enabled` is `true`, and `gsettings get
  org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout` is
  `3600`.
- A fresh install from a rebuilt ISO comes up in `America/New_York`.

Left for later: regional formats (`locale`), lid behaviour, the login
screen's own power settings (GDM has its own dconf profile, so these
defaults don't apply there), automatic timezone on laptops only, and
moving the timezone task into the `preferences` role.

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

## 9. Avatar tasks report "changed" on every run

The avatar part of the `users` role resizes each user's picture on the
control machine, uploads it, and calls AccountsService's `SetIconFile`
on every run, all marked changed (`changed_when: true` / temp files). So
a provision run with nothing to do still shows 5 changed tasks
(confirmed on `testbox`). Only set the icon when it actually differs,
e.g. compare a checksum of the resized image with the one recorded last
time, or with the file AccountsService already holds under
`/var/lib/AccountsService/icons/<user>`.
