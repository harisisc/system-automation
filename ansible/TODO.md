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
