#!/usr/bin/env python3
"""deploy/monitoring/.env dan Alertmanager sozlamasini yaratish.

    python3 deploy/monitoring/render_alertmanager.py deploy/monitoring/.env \\
        deploy/monitoring/alertmanager/alertmanager.generated.yml

Alertmanager o'z sozlamasida muhit o'zgaruvchilarini qo'llab-quvvatlamaydi,
Telegram chat_id esa butun son bo'lishi shart — shuning uchun fayl shu
skript bilan yaratiladi (up.sh chaqiradi). Natija gitignore'da: unda bot
tokeni bor. Faqat standart kutubxona (serverdagi python3 yetarli).

TELEGRAM_BOT_TOKEN yoki TELEGRAM_CHAT_ID bo'sh bo'lsa — ogohlantirishlar
faqat Alertmanager/Grafana'da ko'rinadi, hech qayerga yuborilmaydi.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
_CHAT_ID_RE = re.compile(r"^-?\d+$")

# Server "o'chdi" bo'lsa uning oqibatlari haqida alohida xabar kerak emas.
_API_DOWN_SUPPRESSES = "MetrikaBazadanOlinmayapti|IshVaqtidaDavomatYozilmayapti|AiSweepKechikmoqda"


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _q(value: str) -> str:
    # JSON satri — to'g'ri YAML satri ham (maxsus belgilar xavfsiz).
    return json.dumps(value, ensure_ascii=False)


def render(values: dict[str, str]) -> str:
    token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = values.get("TELEGRAM_CHAT_ID", "").strip()
    thread_id = values.get("TELEGRAM_MESSAGE_THREAD_ID", "").strip()
    if bool(token) != bool(chat_id):
        raise ValueError("TELEGRAM_BOT_TOKEN va TELEGRAM_CHAT_ID ikkalasi birga beriladi (yoki ikkalasi bo'sh)")
    if token and not _TOKEN_RE.match(token):
        raise ValueError("TELEGRAM_BOT_TOKEN formati noto'g'ri (masalan 123456:ABC...)")
    if chat_id and not _CHAT_ID_RE.match(chat_id):
        raise ValueError("TELEGRAM_CHAT_ID butun son bo'lishi kerak (guruh uchun manfiy, masalan -1001234567890)")
    if thread_id and not thread_id.isdigit():
        raise ValueError("TELEGRAM_MESSAGE_THREAD_ID butun son bo'lishi kerak")
    repeat = values.get("ALERT_REPEAT_INTERVAL", "").strip() or "4h"
    if not re.match(r"^\d+[smhd]$", repeat):
        raise ValueError("ALERT_REPEAT_INTERVAL masalan 4h yoki 30m bo'lishi kerak")

    lines = [
        "# up.sh / render_alertmanager.py yaratgan — qo'lda tahrirlamang (gitignore'da).",
        "global:",
        "  resolve_timeout: 5m",
        "templates:",
        "  - /etc/alertmanager/telegram.tmpl",
        "route:",
        "  receiver: telegram",
        "  group_by: [alertname]",
        "  group_wait: 30s",
        "  group_interval: 5m",
        f"  repeat_interval: {repeat}",
        "  routes:",
        "    - matchers: ['severity=\"critical\"']",
        "      receiver: telegram",
        "      repeat_interval: 1h",
        "inhibit_rules:",
        "  - source_matchers: ['alertname=\"ApiIshlamayapti\"']",
        f"    target_matchers: ['alertname=~\"{_API_DOWN_SUPPRESSES}\"']",
        "  - source_matchers: ['alertname=\"KameralarOflaynYarmidan\"']",
        "    target_matchers: ['alertname=~\"KameralarOflayn20Foizdan|KameralarTasvirsiz\"']",
        "  - source_matchers: ['alertname=\"DiskToldi95Foiz\"']",
        "    target_matchers: ['alertname=\"DiskToldi85Foiz\"']",
        "    equal: [mountpoint]",
        "receivers:",
        "  - name: telegram",
    ]
    if token:
        lines += [
            "    telegram_configs:",
            f"      - bot_token: {_q(token)}",
            f"        chat_id: {int(chat_id)}",
        ]
        if thread_id:
            lines.append(f"        message_thread_id: {int(thread_id)}")
        lines += [
            "        parse_mode: HTML",
            "        send_resolved: true",
            "        message: '{{ template \"sm.telegram.message\" . }}'",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    env_path, out_path = Path(argv[1]), Path(argv[2])
    values = parse_env(env_path.read_text(encoding="utf-8"))
    # Muhitdagi qiymat fayldagidan ustun (CI yoki bir martalik sinov uchun).
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_MESSAGE_THREAD_ID", "ALERT_REPEAT_INTERVAL"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    try:
        content = render(values)
    except ValueError as exc:
        print(f"XATO: {exc}", file=sys.stderr)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_path.parent, prefix=".alertmanager.")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.chmod(tmp, 0o600)
    os.replace(tmp, out_path)
    telegram = "Telegram yoqilgan" if values.get("TELEGRAM_BOT_TOKEN") else "Telegram o'chiq (token yo'q)"
    print(f"    {out_path} yozildi — {telegram}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
