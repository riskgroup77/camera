#!/usr/bin/env python3
"""deploy/env.production.scale dagi kalitlarni serverdagi camera-api/.env ga yozish.

    python3 deploy/merge_env.py deploy/env.production.scale camera-api/.env

Faqat manba fayldagi kalitlar o'zgaradi; qolgan qatorlar (maxfiy kalitlar,
izohlar, tartib) joyida qoladi. sed'dan farqli ravishda qiymatdagi `/`, `|`,
`&` belgilari muammo tug'dirmaydi.
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path


def parse(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value
    return values


def merge(source: dict[str, str], target_lines: list[str]) -> tuple[list[str], list[str]]:
    pending = dict(source)
    changed: list[str] = []
    out: list[str] = []
    for line in target_lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else None
        if key in pending:
            value = pending.pop(key)
            new_line = f"{key}={value}\n"
            if line.rstrip("\n") != new_line.rstrip("\n"):
                # Bu kalitlar ochiq repodagi profil fayldan — sir emas, eski
                # qiymatni ko'rsatish mumkin (qo'lda sozlangan qiymat
                # ustidan yozilganini sezish uchun).
                changed.append(f"{key}: {stripped.split('=', 1)[1]} -> {value}")
            out.append(new_line)
        elif key is not None and key in source:
            # Takroriy qator — birinchisi yangilandi, qolganlari chalkashtirmasin.
            changed.append(f"{key} (takror olib tashlandi)")
        else:
            out.append(line if line.endswith("\n") else line + "\n")
    if pending:
        out.append("\n# deploy/env.production.scale\n")
        for key, value in pending.items():
            out.append(f"{key}={value}\n")
            changed.append(f"{key}: (yo'q edi) -> {value}")
    return out, changed


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    source_path, target_path = Path(sys.argv[1]), Path(sys.argv[2])
    source = parse(source_path.read_text().splitlines())
    target_lines = target_path.read_text().splitlines(keepends=True) if target_path.exists() else []
    out, changed = merge(source, target_lines)
    if not changed:
        print("[merge-env] o'zgarish yo'q")
        return 0
    if target_path.exists():
        # Qo'lda sozlangan qiymat ustidan yozilgan bo'lsa, qaytarish oson bo'lsin.
        backup = target_path.with_name(f"{target_path.name}.bak.{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(target_path, backup)
        os.chmod(backup, 0o600)
        print(f"[merge-env] zaxira: {backup}")
    fd, tmp = tempfile.mkstemp(dir=target_path.parent, prefix=".env.")
    with os.fdopen(fd, "w") as handle:
        handle.writelines(out)
    os.chmod(tmp, 0o600)
    os.replace(tmp, target_path)
    # Faqat profil fayldagi kalitlar chiqariladi — maxfiy kalitlar emas.
    print("[merge-env] yangilandi:")
    for line in changed:
        print(f"    {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
