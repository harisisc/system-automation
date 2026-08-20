#!/usr/bin/env python3
import getpass
import glob
import os
import pathlib
import readline
import sys


def _complete_path(text, state):
    expanded = os.path.expanduser(text)
    matches = [m + "/" if os.path.isdir(m) else m for m in glob.glob(expanded + "*")]
    if text.startswith("~") and expanded != text:
        home = os.path.expanduser("~")
        matches = [
            "~" + m[len(home):] if m.startswith(home) else m for m in matches
        ]
    matches.append(None)
    return matches[state]


def _enable_path_completion() -> None:
    readline.set_completer_delims(" \t\n")
    readline.set_completer(_complete_path)
    readline.parse_and_bind("tab: complete")


def read_value(name: str) -> str:
    value = os.environ.get(name)
    file_value = os.environ.get(f"{name}_FILE")

    if value:
        return value.strip()

    if file_value:
        try:
            return pathlib.Path(file_value).read_text().strip()
        except FileNotFoundError:
            return ""

    return ""


def prompt_matching(prompt: str) -> str:
    while True:
        first = getpass.getpass(f"{prompt}: ")
        second = getpass.getpass("Confirm: ")
        if first and first == second:
            return first
        print("Empty or mismatched input, try again.", file=sys.stderr)


def prompt_luks_password() -> str:
    return prompt_matching("LUKS disk encryption passphrase")


PUBLIC_KEY_PREFIXES = (
    "ssh-rsa",
    "ssh-ed25519",
    "ssh-dss",
    "ecdsa-sha2-",
    "sk-ssh-ed25519@openssh.com",
    "sk-ecdsa-sha2-nistp256@openssh.com",
)


def ssh_key_error(text: str) -> str:
    """Return a description of what's wrong with text as an SSH public
    key, or "" if it looks fine."""
    if text.lstrip().startswith("-----BEGIN"):
        return "that's a PRIVATE key (starts with -----BEGIN...), not a public key"
    first_token = text.split(None, 1)[0] if text.split() else ""
    if not first_token.startswith(PUBLIC_KEY_PREFIXES):
        return "doesn't look like an SSH public key (expected it to start with ssh-ed25519, ssh-rsa, etc.)"
    return ""


def prompt_ssh_public_key() -> str:
    default = pathlib.Path.home() / ".ssh" / "ansible_ed25519.pub"
    _enable_path_completion()
    while True:
        raw = input(f"Path to Ansible SSH public key [{default}]: ").strip()
        path = pathlib.Path(raw).expanduser() if raw else default
        try:
            key = path.read_text().strip()
        except FileNotFoundError:
            print(f"No such file: {path}", file=sys.stderr)
            continue
        error = ssh_key_error(key)
        if error:
            print(f"{path}: {error}", file=sys.stderr)
            continue
        return key


PROMPTS = {
    "__ANSIBLE_SSH_PUBLIC_KEY__": prompt_ssh_public_key,
    "__LUKS_PASSWORD__": prompt_luks_password,
}


def main() -> int:
    template_path = pathlib.Path(
        os.environ.get("AUTOINSTALL_TEMPLATE", "autoinstall.yaml.template")
    )
    output_path = pathlib.Path(os.environ.get("AUTOINSTALL_OUTPUT", "build/autoinstall.yaml"))

    values = {
        "__ANSIBLE_SSH_PUBLIC_KEY__": read_value("ANSIBLE_SSH_PUBLIC_KEY"),
        "__LUKS_PASSWORD__": read_value("LUKS_PASSWORD"),
    }

    # Only prompt when attached to a real terminal, so non-interactive runs
    # (CI, scripts) still fail fast on missing values instead of hanging.
    if sys.stdin.isatty():
        for placeholder, value in values.items():
            if not value:
                values[placeholder] = PROMPTS[placeholder]()

    missing = [key.strip("_") for key, value in values.items() if not value]
    if missing:
        print(f"Missing required value(s): {', '.join(missing)}", file=sys.stderr)
        return 1

    # Catches ANSIBLE_SSH_PUBLIC_KEY(_FILE) pointing at a private key too -
    # the interactive prompt already checks this itself, but env-var input
    # has no human looking at it before it lands in a generated file.
    ssh_key = values["__ANSIBLE_SSH_PUBLIC_KEY__"]
    error = ssh_key_error(ssh_key)
    if error:
        print(f"ANSIBLE_SSH_PUBLIC_KEY: {error}", file=sys.stderr)
        return 1

    text = template_path.read_text()
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text)
    print(f"Generated {output_path} from {template_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
