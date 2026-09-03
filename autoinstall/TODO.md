# Known issues

## 1. ubuntu account password and LUKS passphrase are both shared, hardcoded placeholders

`autoinstall.yaml.template`'s `identity.password` (a crypt hash of
`changeme`) and `storage.layout.password` (`"changeme"` in plaintext,
since that field isn't hashed) are both the same on every ISO, not
treated as real secrets. README.md documents rotating each by hand after
first boot
([ubuntu password](README.md#change-the-ubuntu-accounts-password),
[LUKS passphrase](README.md#update-a-luks-passphrase)), but nothing
enforces or automates either, so a machine can be left running
indefinitely on the shared defaults.

An earlier attempt at fixing this properly (dummy passphrase + a
`first-boot-setup.service` systemd unit that force-prompts for a real,
unique-per-machine passphrase before the rest of boot proceeds — script
written, base64-embedded into `late-commands`, logic tested) was shelved
in favor of shipping something simpler first. Revisit that approach, or
another one, so no real machine is left on the shared placeholder.

## 2. No hostname-at-first-boot

Every install gets `hostname: ubuntu` from the template, unchanged —
multiple machines installed from the same ISO will collide on the network
(DHCP/mDNS name clashes, etc.) until manually renamed
(`hostnamectl set-hostname ...` post-install).

Was going to be handled by the same first-boot-setup mechanism as issue 1
(prompt for a real hostname alongside the LUKS passphrase), also shelved.

## 3. No transparent way to discover a freshly installed machine

Right now, finding a newly autoinstalled machine to run the first
playbook against means checking the router's DHCP client list, `nmap`
scanning the LAN, or relying on mDNS (`ubuntu.local`) — which only stays
unambiguous for one machine at a time, since every install currently
shares the same default hostname (see issue 2).

The plan: wire Tailscale auth into `autoinstall.yaml.template`'s
`late-commands` (using a vaulted, ideally ephemeral/single-use auth key),
so a machine joins the tailnet — with a stable address and a real
MagicDNS name — during install, before you'd ever need to know its LAN
IP at all. Fixes this and issue 2 together, since you'd presumably set a
real hostname at the same time. Tradeoff: an auth key baked into the
ISO, similar territory to issue 1, though meaningfully lower-stakes since
Tailscale auth keys are revocable and can be scoped ephemeral/single-use.

## 4. Ansible ssh private and public key