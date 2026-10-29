import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
REF_FILE = ROOT / "CONTRACTS_REF"


def fetch(remote: str, destination: pathlib.Path) -> str:
    ref = REF_FILE.read_text(encoding="utf-8").strip() if REF_FILE.exists() else "main"
    shutil.rmtree(destination, ignore_errors=True)
    subprocess.run(["git", "clone", "--quiet", remote, str(destination)], check=True)
    subprocess.run(["git", "-C", str(destination), "checkout", "--quiet", ref], check=True)
    got = subprocess.run(["git", "-C", str(destination), "rev-parse", "HEAD"],
                         check=True, capture_output=True, text=True).stdout.strip()
    print(f"leaflowapis {ref} -> {got[:12]}")
    return got
