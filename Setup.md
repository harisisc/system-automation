# Clean Install Runbook

Step-by-step process for taking a new machine from bare hardware to a
fully provisioned workstation, using [`autoinstall/`](autoinstall/README.md)
and [`ansible/`](ansible/README.md). Each step links back to the fuller
docs for that piece; this page is just the order to run them in.

Not covered here — deliberately out of scope for a clean install:

- **`kvmhosts`** (libvirt/QEMU/GNOME Boxes) — opt-in, bare-metal only
  (nested virtualization makes it pointless to test in a VM), run by hand
  afterward with `ansible-playbook playbooks/run_role.yaml -e role_name=kvmhosts`.
- **`preferences`** — still being tweaked, commented out in
  `provision.yaml`.

## 0. One-time prerequisites (skip if already done)

These aren't per-machine — do them once, ever, on your own workstation.

**Generate the Ansible SSH keypair.** Every autoinstalled machine gets
this key's public half baked in for the `ansible` account; `ansible/`
uses the private half to connect.

```sh
ssh-keygen -t ed25519 -f ~/.ssh/ansible_ed25519 -C ansible
```

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
sudo) and locks out the `ubuntu` user. LUKS disk encryption is enabled
with a shared placeholder passphrase (`changeme`) — that gets replaced
in step 6.

Once it reboots, note the machine's LAN IP (check your router's DHCP
client list, or `ping ubuntu.local`).

## 3. Add the machine to inventory and configure its users

Add the new machine under the `bootstrap` group in
[`ansible/inventory/hosts.yaml`](ansible/inventory/hosts.yaml), keyed by
its IP:

```yaml
bootstrap:
  hosts:
    192.168.1.91: {}
```

If this machine needs a user account that isn't already in
[`ansible/inventory/group_vars/all.yaml`](ansible/inventory/group_vars/all.yaml)'s
`users:` list, add them there now (and drop an optional
`<username>.png` avatar into `inventory/group_vars/avatars/` — see
[`ansible/README.md`](ansible/README.md#user-avatars)).

## 4. Run bootstrap.yaml

Creates the configured user accounts, fully patches the system, sets a
real hostname, and installs (but doesn't authenticate) Tailscale:

```sh
cd ansible
ansible-playbook playbooks/bootstrap.yaml --limit 192.168.1.91
```

Prompts for the machine's hostname and a shared initial password for the
configured accounts. That password isn't stored anywhere and each
account is forced to change it at first login. See
[`ansible/README.md`](ansible/README.md#bootstrap-a-freshly-installed-machine)
for the full explanation.

> **Known issue:** SSH password auth isn't disabled yet, so the forced
> password-change window is technically a race over the network (see
> [`ansible/TODO.md`](ansible/TODO.md#1-ssh-password-auth-is-a-race-condition-against-the-shared-bootstrap-password)).
> Until that's fixed, do steps 5–6 at the physical console, not over SSH.

## 5. Log in and set your real password

At the machine's console, log in as your username with the shared
initial password from step 4. Linux will immediately prompt you to set a
real password (that's `passwd --expire` from bootstrap.yaml kicking in) —
set it there.

## 6. Set the real LUKS passphrase

Still at the console (or over SSH, this part has no race-condition
concern):

```sh
lsblk -f   # find the crypto_LUKS partition, e.g. /dev/nvme0n1p3
sudo cryptsetup luksChangeKey /dev/nvme0n1p3
```

See [`autoinstall/README.md`](autoinstall/README.md#update-a-luks-passphrase)
for the optional unlock-test step.

## 7. Connect Tailscale

Generate a single-use auth key from the
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

Installs the curated apt/snap package lists, rtcwake, Syncthing, Docker
(engine + group membership), and sets avatars/group membership for
configured users:

```sh
ansible-playbook playbooks/provision.yaml --limit the-new-hostname
```

See [`ansible/README.md`](ansible/README.md#run-playbooks) for running a
slice of it by tag (`--tags users`, `--skip-tags docker`, etc).

The machine is now fully provisioned. Ongoing maintenance after this is
just `ansible-playbook playbooks/update.yaml` (or `site.yaml`, which
chains update + provision), on whatever cadence you like.
