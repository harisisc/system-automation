# Ansible

Configures a workstation after it's been provisioned by `../autoinstall`.
Run all commands from this directory so `ansible.cfg` is picked up.

## Install role/collection dependencies

```sh
ansible-galaxy role install -r roles_external/requirements.yaml -p ./roles_external
ansible-galaxy collection install -r collections/requirements.yaml -p ./collections
```

The `users` role also needs ImageMagick's `convert` on the control machine
(not the target) if you're using avatar images — see below.

```sh
sudo apt install imagemagick
```

## Inventory

`inventory/` isn't tracked in git — it holds real hostnames, IPs, real
names, and avatar photos. `inventory.example/` mirrors its structure
with dummy data; copy it into place before anything else here will work:

```sh
cp -r inventory.example inventory
```

Then edit `inventory/hosts.yaml` and `inventory/group_vars/all.yaml`
with your own machines and users.

`inventory/hosts.yaml` has two groups, reflecting a machine's lifecycle:

- **`bootstrap`** — freshly autoinstalled machines, reachable only by IP,
  still with the template's default hostname and no Tailscale.
  `playbooks/bootstrap.yaml` targets this group.
- **`workstations`** — fully set up machines (real hostname, Tailscale
  connected), identified by hostname instead of IP. `provision.yaml`,
  `update.yaml`, and `site.yaml` all target this group, not `bootstrap`.

Once `bootstrap.yaml` has run against a `bootstrap` entry, move it by
hand: delete its IP-keyed line from `bootstrap.hosts` and add a
hostname-keyed line under `workstations.hosts` instead.

## Bootstrap a Freshly Installed Machine

Run once against a freshly autoinstalled machine, in order: creates
configured user accounts, fully patches the system (apt/snap/flatpak, so
everything after this lands on a current base rather than whatever the
ISO snapshot shipped with), sets a real hostname, and installs Tailscale
(left unauthenticated — run `sudo tailscale up` on the machine yourself
afterward). Deliberately doesn't install the curated apt/snap package
lists (`apt_packages`, `snap_packages`) — that's `provision.yaml`'s job,
once this host is promoted to `workstations`. Targets exactly one host
at a time:

```sh
ansible-playbook playbooks/bootstrap.yaml --limit 192.168.1.91
```

Tagged the same way as `provision.yaml`, by concern (`users`,
`system_update`, `hostname`, `tailscale`), if you want to re-run just one
step.

It prompts for two things each run: the machine's hostname, and a shared
initial password for the configured accounts. That password isn't stored
anywhere — it's typed fresh every run and immediately hashed on the fly —
and each account is forced to change it at first login (`passwd --expire`),
so it only needs to work long enough for someone to log in once and set
their own. Nothing about a user's real password ever lives in this repo.

### Connect to Tailscale

Tailscale itself is installed but left unauthenticated. Generate an auth
key from the [admin console](https://login.tailscale.com/admin/settings/keys) →
**Generate auth key...**, with:

- **Reusable** — off (single-use only)
- **Ephemeral** — off (the machine stays listed when offline, instead of
  being removed from your tailnet automatically)
- **Pre-approved** — on, if shown (skips manual device approval; only
  appears if device approval is enabled on your tailnet)
- **Expiration** — 90 days

Then, on the machine itself:

```sh
sudo tailscale up --accept-routes --auth-key=tskey-auth-XXXXXXXXXXXX-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

## User Avatars

Drop `<username>.png` into `inventory/group_vars/avatars/` (gitignored —
these are real photos, never committed) to give that account a login/profile
picture. Users without a file there are just skipped, no error. The `users`
role resizes it and sets it via AccountsService's own dbus call, since
GNOME's avatar picker enforces a size limit and won't take a raw photo
straight from a phone.

## Secrets (ansible-vault)

Nothing in the repo is currently vaulted (user passwords are handled
above, without ever touching a file). If you add a secret later, encrypt
it in place with:

```sh
ansible-vault encrypt_string --vault-password-file .vault_pass 'the-secret' --name 'var_name'
```

`.vault_pass` (gitignored) holds the vault password — treat it like a
root credential. Generate one if you don't have it yet:

```sh
openssl rand -base64 32 > .vault_pass
chmod 600 .vault_pass
```

Then pass `--vault-password-file .vault_pass` (or `--ask-vault-pass` to
enter it interactively) to any `ansible-playbook` command that touches a
vaulted value.

## Run Playbooks

`playbooks/site.yaml` builds an entire machine: `update.yaml` (apt/snap/flatpak
upgrades — the thing you'd run regularly, e.g. on a cron/timer) then
`provision.yaml` (users, packages, Docker, Syncthing, preferences — the
thing you mostly only need after a fresh install).

Run the full build:

```sh
ansible-playbook playbooks/site.yaml
```

Run just the regular maintenance pass:

```sh
ansible-playbook playbooks/update.yaml
```

Run just provisioning:

```sh
ansible-playbook playbooks/provision.yaml
```

`provision.yaml`'s tasks are tagged by concern (`users`, `apt_packages`,
`snap_packages`, `docker`, `rtcwake`, `syncthing`, `preferences`), so you
can run a slice of it without touching the rest — e.g. to pick up a new
user you just added to `group_vars/all.yaml` without re-running everything
else:

```sh
ansible-playbook playbooks/provision.yaml --tags users
```

Or the inverse, everything except Docker:

```sh
ansible-playbook playbooks/provision.yaml --skip-tags docker
```

For anything not covered by a tag, `run_role.yaml` runs one role standalone:

```sh
ansible-playbook playbooks/run_role.yaml -e role_name=syncthing
```

Add `--vault-password-file .vault_pass` to any of these if the repo has
vaulted values again by the time you're running them (see Secrets above).
