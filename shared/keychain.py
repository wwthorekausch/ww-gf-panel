"""Liest Secrets aus der macOS Keychain (security CLI). Gibt Token nie aus."""
import subprocess


def keychain_token(service: str) -> str:
    result = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                            capture_output=True, text=True)
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise RuntimeError(
            f"Kein Keychain-Eintrag '{service}'. Anlegen: "
            f"security add-generic-password -s {service} -a sevdesk -w"
        )
    return token
