# System Automation

Two independent, self-contained pieces for bootstrapping and maintaining
local Ubuntu workstations:

| Directory | Purpose |
| --- | --- |
| [`autoinstall/`](autoinstall/README.md) | Generates the Ubuntu `autoinstall.yaml` used by the OS installer. Produces a machine with an `ansible` service account and nothing else. |
| [`ansible/`](ansible/README.md) | Ansible playbooks and roles that configure a booted machine (users, packages, Docker, Syncthing, etc.). |

## Workflow

1. Use `autoinstall/` to generate an installer config and provision the OS.
2. Boot the target machine with that config. It comes up with an `ansible`
   user reachable over SSH.
3. Use `ansible/` to configure the machine.

The two directories don't depend on each other beyond that hand-off — see
each one's own README for setup and usage, or [`Setup.md`](Setup.md) for
the full step-by-step runbook.
