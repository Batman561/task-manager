from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
import venv
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(command: list[str]) -> None:
    print("> " + " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def ensure_venv() -> Path:
    python = venv_python()
    if not python.exists():
        print("ساخت محیط مجازی در .venv …")
        try:
            venv.EnvBuilder(with_pip=True, clear=False).create(VENV_DIR)
        except Exception as error:
            raise SystemExit(f"ساخت .venv ناموفق بود: {error}") from error
    if not python.exists():
        raise SystemExit("مفسر پایتون داخل .venv پیدا نشد. پوشهٔ .venv را پاک کن و دوباره تلاش کن.")
    return python


def install_requirements(python: Path) -> None:
    if not (ROOT / "requirements.txt").exists():
        raise SystemExit("فایل requirements.txt پیدا نشد.")
    run([str(python), "-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check"])
    run([str(python), "-m", "pip", "install", "-r", "requirements.txt", "--disable-pip-version-check"])


def ensure_env_file() -> None:
    if ENV_FILE.exists():
        return
    if ENV_EXAMPLE.exists():
        ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        ENV_FILE.write_text("BOT_TOKEN=\nTIMEZONE=Asia/Tehran\n", encoding="utf-8")
    print("فایل .env ساخته شد.")


def read_env(name: str) -> str:
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return ""


def write_env(name: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{name}="):
            output.append(f"{name}={value}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f"{name}={value}")
    ENV_FILE.write_text("\n".join(output).strip("\n") + "\n", encoding="utf-8")


def ask_token(explicit: str | None) -> str:
    token = (explicit or os.getenv("BOT_TOKEN") or read_env("BOT_TOKEN")).strip()
    if token:
        return token
    if not sys.stdin or not sys.stdin.isatty():
        print("توکنی وارد نشد؛ بعداً مقدار BOT_TOKEN را در فایل .env بگذار.")
        return ""
    print("توکن ربات را از @BotFather بگیر (شبیه 123456789:AA...).")
    while True:
        try:
            token = getpass.getpass("BOT_TOKEN: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nبدون توکن ادامه می‌دهم؛ بعداً در .env پرش کن.")
            return ""
        if token:
            return token
        print("خالی بود، دوباره وارد کن.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="نصب ربات تلگرام مدیریت تسک",
    )
    parser.add_argument("--token", help="توکن ربات؛ اگر داده نشود پرسیده می‌شود")
    parser.add_argument("--start", action="store_true", help="بعد از نصب، ربات را اجرا کن")
    args = parser.parse_args(argv)

    if sys.version_info < (3, 10):
        print("پایتون ۳.۱۰ یا جدیدتر لازم است.")
        return 1

    python = ensure_venv()
    install_requirements(python)
    ensure_env_file()

    token = ask_token(args.token)
    if token:
        write_env("BOT_TOKEN", token)
        print("توکن در .env ذخیره شد.")

    print("\n✅ نصب تمام شد.")
    print(f"برای اجرا: {os.path.relpath(python, ROOT)} bot.py")

    if args.start:
        if not token:
            print("بدون توکن نمی‌شود ربات را اجرا کرد.")
            return 1
        print("در حال اجرای ربات…")
        return subprocess.call([str(python), "bot.py"], cwd=ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
