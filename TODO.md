# Known issues

## 1. [IN TESTING] Daily 20:00 wake from suspend (rtcwake)

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
  2026-11-24. But `arnold` was awake then (it never suspended, see #4),
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
cd ansible
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

## 2. preferences role: editor and gitconfig tasks aren't wired in

`ansible/roles/preferences/tasks/main.yaml` only imports `location.yaml`.
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

## 3. Prometheus: scrape node_exporter and alert on disk usage

node_exporter is installed by `ansible/roles/node_exporter` on hosts with
`node_exporter_enabled: true` in `host_vars` (running on `testbox`). The
rest happens on the Prometheus side, on `conglomerate`:

- **Scrape it.** The host needs to be on Tailscale, then add its
  Tailscale name/IP and port 9100 as a target in Prometheus.
- **Narrow `node_exporter_allow_from`** to conglomerate's Tailscale IP
  instead of the whole tailnet range, once scraping works (`host_vars` or
  `group_vars`).
- **Disk usage alerts.** Get warned when `/` or `/home` fills up past a
  threshold. Not quotas: those block writes, and count per user by file
  owner, which isn't the goal. Alert rules, e.g.:

  ```promql
  # over 85% full for 15 minutes
  (1 - node_filesystem_avail_bytes{mountpoint=~"/|/home", fstype="ext4"}
     / node_filesystem_size_bytes{mountpoint=~"/|/home", fstype="ext4"}) * 100 > 85

  # on track to fill within 7 days, based on the last 6 hours
  predict_linear(node_filesystem_avail_bytes{mountpoint=~"/|/home", fstype="ext4"}[6h], 7*24*3600) < 0
  ```

  Machines installed before the 100G / + 300G /home layout only have
  `/`.
- **Expect nightly sleep.** A suspended machine sends no data, so alerts
  don't fire while it sleeps, and a "host down" alert has to allow for
  it (see #4 power settings).

## 4. [IN TESTING] System-wide settings: timezone, location, power

Timezone is the first task in `provision.yaml` (tag `timezone`,
`system_timezone` in `group_vars`) and `timezone:` in the autoinstall
templates. Location and power are dconf system defaults (not locked)
from the `preferences` role (`location.yaml`, `power.yaml`). A timezone
change restarts the daily wake timer (#1).

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
  while it happens). Being re-tested at the login screen (see #1). If
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
cd ansible
ansible-playbook playbooks/provision.yaml --tags timezone,preferences --limit <host>
```

## 5. Syncthing exporter proxy

Expose each user's Syncthing metrics to Prometheus, alongside
node_exporter (#3). Notes for when this is picked up:

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

## 6. SSH key management

- **Manage user keys.** Nothing in the playbooks manages users' SSH
  keys (`~/.ssh/authorized_keys`) today. Decide whether the
  `users` role should manage them from the inventory (e.g. an
  `ssh_keys:` list per user in `group_vars`), and whether it should
  only add keys or also remove ones that aren't listed.
- **Back up the Ansible key.** Every machine's `ansible` account only
  accepts `~/.ssh/ansible_ed25519` from the control machine
  (`ansible_ssh_private_key_file` in `group_vars`). If that key is lost,
  nothing can be provisioned until a new key is put on each machine by
  hand. Decide where a backup copy lives (e.g. a password manager or an
  encrypted offline copy) and how to replace the key if it's ever
  exposed.
