#!/usr/bin/env python3
import getpass
import os
import pathlib
import subprocess
import sys


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


def hash_password(password: str) -> str:
    result = subprocess.run(
        ["openssl", "passwd", "-6", "-stdin"],
        input=password,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def prompt_matching(prompt: str) -> str:
    while True:
        first = getpass.getpass(f"{prompt}: ")
        second = getpass.getpass("Confirm: ")
        if first and first == second:
            return first
        print("Empty or mismatched input, try again.", file=sys.stderr)


def prompt_luks_password() -> str:
    return prompt_matching("LUKS disk encryption passphrase")


def prompt_install_password_hash() -> str:
    return hash_password(prompt_matching("Install-time user password"))


def prompt_ssh_public_key() -> str:
    default = pathlib.Path.home() / ".ssh" / "ansible_ed25519.pub"
    while True:
        raw = input(f"Path to Ansible SSH public key [{default}]: ").strip()
        path = pathlib.Path(raw).expanduser() if raw else default
        try:
            return path.read_text().strip()
        except FileNotFoundError:
            print(f"No such file: {path}", file=sys.stderr)


PROMPTS = {
    "__ANSIBLE_SSH_PUBLIC_KEY__": prompt_ssh_public_key,
    "__INSTALL_PASSWORD_HASH__": prompt_install_password_hash,
    "__LUKS_PASSWORD__": prompt_luks_password,
}


def main() -> int:
    template_path = pathlib.Path(
        os.environ.get("AUTOINSTALL_TEMPLATE", "autoinstall.yaml.template")
    )
    output_path = pathlib.Path(os.environ.get("AUTOINSTALL_OUTPUT", "build/autoinstall.yaml"))

    values = {
        "__ANSIBLE_SSH_PUBLIC_KEY__": read_value("ANSIBLE_SSH_PUBLIC_KEY"),
        "__INSTALL_PASSWORD_HASH__": read_value("INSTALL_PASSWORD_HASH"),
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

    text = template_path.read_text()
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text)
    print(f"Generated {output_path} from {template_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
