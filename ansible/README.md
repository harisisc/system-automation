# Ansible

Configures a workstation after it's been provisioned by `../autoinstall`.
Run all commands from this directory so `ansible.cfg` is picked up.

## Install role/collection dependencies

```sh
ansible-galaxy role install -r roles_external/requirements.yaml -p ./roles_external
ansible-galaxy collection install -r collections/requirements.yaml -p ./collections
```

## Configure Login Passwords

`password_hash` values in `inventory/group_vars/all.yaml` are encrypted
in-place with `ansible-vault` — they're SHA-512 crypt hashes, but still not
something to commit in plaintext.

Generate a new hash and encrypt it as a `!vault` block:

```sh
mkpasswd --method=sha-512
ansible-vault encrypt_string --vault-password-file .vault_pass 'the-hash-from-above' --name 'password_hash'
```

Paste the output (the `password_hash: !vault |` block and its indented
body) in place of the user's existing `password_hash` entry, keeping it
indented to match the surrounding YAML.

`.vault_pass` holds the vault password and is gitignored — it decrypts
every vaulted value in this repo, so treat it like a root credential. If
you don't already have one, generate a strong one and keep a backup
somewhere safe (a password manager, not this repo):

```sh
openssl rand -base64 32 > .vault_pass
chmod 600 .vault_pass
```

Without `.vault_pass` on a machine, use `--ask-vault-pass` instead to enter
it interactively.

## Run Playbooks

`playbooks/site.yaml` builds an entire machine: `update.yaml` (apt/snap/flatpak
upgrades — the thing you'd run regularly, e.g. on a cron/timer) then
`provision.yaml` (users, packages, Docker, Syncthing, preferences — the
thing you mostly only need after a fresh install).

Run the full build:

```sh
ansible-playbook playbooks/site.yaml --vault-password-file .vault_pass
```

Run just the regular maintenance pass:

```sh
ansible-playbook playbooks/update.yaml --vault-password-file .vault_pass
```

Run just provisioning:

```sh
ansible-playbook playbooks/provision.yaml --vault-password-file .vault_pass
```

`provision.yaml`'s tasks are tagged by concern (`users`, `base`,
`snap_packages`, `docker`, `rtcwake`, `syncthing`, `preferences`), so you
can run a slice of it without touching the rest — e.g. to pick up a new
user you just added to `group_vars/all.yaml` without re-running everything
else:

```sh
ansible-playbook playbooks/provision.yaml --vault-password-file .vault_pass --tags users
```

Or the inverse, everything except Docker:

```sh
ansible-playbook playbooks/provision.yaml --vault-password-file .vault_pass --skip-tags docker
```

For anything not covered by a tag, `run_role.yaml` runs one role standalone:

```sh
ansible-playbook playbooks/run_role.yaml --vault-password-file .vault_pass -e role_name=syncthing
```
