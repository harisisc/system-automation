# Clean Install Runbook

Step-by-step process for taking a new machine from bare hardware to a
fully provisioned workstation, using [`autoinstall/`](autoinstall/README.md)
and [`ansible/`](ansible/README.md). Each step links back to the fuller
docs for that piece; this page is just the order to run them in.

Not covered here — deliberately out of scope for a clean install:

- **`preferences`' per-user editor/gitconfig tasks** — provision only
  runs its machine-wide part (location services) so far (see
  [`ansible/TODO.md`](ansible/TODO.md#2-preferences-role-editor-and-gitconfig-tasks-arent-wired-in)).

## 0. One-time prerequisites (skip if already done)

These aren't per-machine — do them once, ever, on your own workstation.
From here on, everything in this runbook — every command below, and
every `ansible-playbook` run in the steps that follow — happens while
logged in as a dedicated local `ansible` account, not your personal
login. Keeps automation credentials (this account's SSH key, and
anything vaulted later) separate from your own.

**Create the local `ansible` account.** Mirrors what
`autoinstall.yaml.template` gives the `ansible` account on every machine
it provisions: passwordless sudo, key-only login (no password auth at
all).

```sh
sudo useradd --create-home --shell /bin/bash --comment "Ansible Service Account" ansible
sudo usermod -aG sudo ansible
echo "ansible ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/ansible
sudo chmod 440 /etc/sudoers.d/ansible
sudo passwd -l ansible
```

**Switch into it and generate its SSH keypair.** Every autoinstalled
machine gets this key's public half baked in for its own `ansible`
account; this key's private half, held here, is what actually connects
to them.

```sh
sudo su - ansible
ssh-keygen -t ed25519 -f ~/.ssh/ansible_ed25519 -C ansible
```

Run interactively, this prompts for a passphrase — enter one; an
unencrypted private key means anyone who reads that file off disk can
use it to reach every machine you manage. Load it into your SSH agent
so `ansible-playbook` doesn't stop and ask for it on every run:

```sh
ssh-add ~/.ssh/ansible_ed25519
```

**Back it up.** This key only ever exists in one place - if this
machine dies without a backup, you lose SSH access to every machine you
manage at once, since only the *public* half was ever copied anywhere
(baked into each machine's `authorized_keys` at install time). Copy the
private key's contents into your password manager as a secure note
(along with its passphrase):

```sh
cat ~/.ssh/ansible_ed25519
```

**Get a copy of this repo here too** — everything from here on runs out
of this account's checkout, not your personal one:

```sh
git clone https://github.com/harisisc/system-automation.git
cd system-automation
```

**Set up your real inventory** — `ansible/inventory/` isn't tracked in
git (real hostnames, IPs, names, avatar photos); copy the dummy example
and fill in your own:

```sh
cp -r ansible/inventory.example ansible/inventory
```

Edit `ansible/inventory/hosts.yaml` and
`ansible/inventory/group_vars/all.yaml` with your own machines and users
now, or as you go — steps 3 and 8 below point back here each time you add
one.

**Install role/collection dependencies** (see
[`ansible/README.md`](ansible/README.md#install-rolecollection-dependencies)):

```sh
cd ansible
ansible-galaxy role install -r roles_external/requirements.yaml -p ./roles_external
ansible-galaxy collection install -r collections/requirements.yaml -p ./collections
```

**Install build tools** for the ISO (`xorriso`) and avatar resizing
(`imagemagick`, only needed if you're using avatar images):

```sh
sudo apt install xorriso imagemagick
```

## 1. Build the ISO

Download an [Ubuntu live ISO](https://ubuntu.com/download) (server or
desktop), then bake your `autoinstall.yaml` into it:

```sh
cd autoinstall
SOURCE_ISO=~/Downloads/ubuntu-24.04.1-live-server-amd64.iso make iso
```

Output: `autoinstall/build/ubuntu-autoinstall.iso`. Write it to a USB
drive:

```sh
sudo dd if=build/ubuntu-autoinstall.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

See [`autoinstall/README.md`](autoinstall/README.md#build-a-bootable-iso)
for details (public key prompting, requirements, etc).

## 2. Install the OS

Boot the target machine from the USB drive. The install is fully
unattended — it creates an `ansible` user (key-only SSH, passwordless
sudo) and a `ubuntu` user with a shared placeholder password
(`changeme`), which works at the console and over SSH. The disk is fully
encrypted (LUKS, same `changeme` placeholder passphrase) with LVM inside:
100G `/` and 300G `/home`. It wipes the **largest** attached disk, which
must be at least ~410GB; see
[`autoinstall/README.md`](autoinstall/README.md#what-the-installer-sets-up).
Both placeholders get replaced in step 6.

Once it reboots, note the machine's LAN IP (check your router's DHCP
client list, or `ping ubuntu.local`).

## 3. Add the machine to inventory and configure its users

Add the new machine under the `bootstrap` group in your local
`ansible/inventory/hosts.yaml` (not tracked in git — see step 0), keyed
by its IP:

```yaml
bootstrap:
  hosts:
    192.168.1.91: {}
```

If this machine needs a user account that isn't already in your local
`ansible/inventory/group_vars/all.yaml`'s `users:` list, add them there
now (and drop an optional `<username>.png` avatar into
`inventory/group_vars/avatars/` — see
[`ansible/README.md`](ansible/README.md#user-avatars)).

## 4. Run bootstrap.yaml

Creates the configured user accounts, fully patches the system, sets a
real hostname, and installs Tailscale (and connects it, if you give it an
auth key):

```sh
cd ansible
ansible-playbook playbooks/bootstrap.yaml --limit 192.168.1.91
```

Prompts for the machine's hostname, a shared initial password for the
configured accounts, and an optional Tailscale auth key (generate one as
in step 7 first if you want to connect it now; press Enter to skip). That
password isn't stored anywhere and each
account is forced to change it at first login. It then shows the target
and asks you to type the new hostname again before changing anything,
and refuses any machine that isn't freshly installed. See
[`ansible/README.md`](ansible/README.md#bootstrap-a-freshly-installed-machine)
for the full explanation.

> **Note:** SSH password auth is left on, so do steps 5–6 at the
> physical console, not over SSH. Otherwise anyone who knows the shared
> initial password could log in first and set the account's real
> password themselves.

## 5. Log in and set your real password

At the machine's console, log in as your username with the shared
initial password from step 4. Linux will immediately prompt you to set a
real password (that's `passwd --expire` from bootstrap.yaml kicking in) —
set it there.

## 6. Set the real LUKS passphrase

Still at the console (or over SSH, this part has no race-condition
concern):

```sh
lsblk -f
```

Search the output for a device with type `crypto_LUKS` — that's the raw
partition (e.g. `/dev/vda3` on a VM, `/dev/nvme0n1p3` on an NVMe laptop),
not the `dm_crypt-0`-style mapper device
nested underneath it. See
[`autoinstall/README.md`](autoinstall/README.md#update-a-luks-passphrase)
for an example.

```sh
sudo cryptsetup luksChangeKey /dev/vda3
```

There's no `ubuntu` password to change: bootstrap (step 4) already
deleted that account.

See [`autoinstall/README.md`](autoinstall/README.md#update-a-luks-passphrase)
for the optional unlock-test step.

## 7. Connect Tailscale

Skip this if you gave bootstrap an auth key in step 4 (check with
`tailscale status`). Otherwise, generate a single-use auth key from the
[admin console](https://login.tailscale.com/admin/settings/keys) →
**Generate auth key...**, with **Reusable** off, **Ephemeral** off,
**Pre-approved** on (if shown), **Expiration** 90 days. Then on the
machine:

```sh
sudo tailscale up --accept-routes --auth-key=tskey-auth-XXXXXXXXXXXX-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

## 8. Promote the machine to workstations

Now that it has a real hostname and Tailscale, move its inventory entry
in `ansible/inventory/hosts.yaml`: delete the IP-keyed line from
`bootstrap.hosts`, add a hostname-keyed line under `workstations.hosts`:

```yaml
workstations:
  hosts:
    the-new-hostname: {}
```

## 9. Run provision.yaml

Sets the system timezone (`system_timezone` in `group_vars`), turns on
the ufw firewall (incoming denied except SSH from LAN and Tailscale, and
Syncthing and mDNS from LAN), enables
location services and sets power defaults (screen off after 5 min;
suspend after 15 min on battery, 1 hour on AC), installs
the curated apt/snap package lists, rtcwake, Syncthing, Docker
(engine + group membership), node_exporter (only on hosts with
`node_exporter_enabled: true`), KVM/libvirt (skipped when the machine is
itself a VM), and sets avatars/group membership for
configured users:

```sh
ansible-playbook playbooks/provision.yaml --limit the-new-hostname
```

See [`ansible/README.md`](ansible/README.md#run-playbooks) for running a
slice of it by tag (`--tags users`, `--skip-tags docker`, etc).

The machine is now fully provisioned. Ongoing maintenance after this is
just `ansible-playbook playbooks/run_role.yaml -e role_name=system_update
--limit workstations`, on whatever cadence you like.
