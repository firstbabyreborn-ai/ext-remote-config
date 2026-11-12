"""
sync_ytdlp_clients.py
Fetches the latest official `yt-dlp` YouTube extractor (`_base.py`) directly from GitHub,
extracts `INNERTUBE_CLIENTS` (clientName, clientVersion, userAgent, device/OS fields, client ID),
and updates `config.json` with live `ytdlp_innertube_clients` and `innertube_clients`.
"""

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

YTDLP_BASE_URL = "https://raw.githubusercontent.com/yt-dlp/yt-dlp/master/yt_dlp/extractor/youtube/_base.py"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

TARGET_KEYS = [
    ("android", "ANDROID"),
    ("android_vr", "ANDROID_VR"),
    ("ios", "IOS"),
    ("android_testsuite", "ANDROID_TESTSUITE"),
    ("web_embedded", "WEB_EMBEDDED_PLAYER"),
    ("tv_simply", "TVHTML5_SIMPLY_EMBEDDED_PLAYER"),
    ("tv", "TVHTML5"),
]

FALLBACK_TESTSUITE = {
    "name": "ANDROID_TESTSUITE",
    "clientName": "ANDROID_TESTSUITE",
    "clientVersion": "1.9",
    "androidSdkVersion": 30,
    "clientNameHeader": "30",
    "userAgent": "com.google.android.youtube/1.9 (Linux; U; Android 11) gzip",
    "hl": "en",
    "gl": "US",
}

FALLBACK_TV_EMBED = {
    "name": "TVHTML5_SIMPLY_EMBEDDED_PLAYER",
    "clientName": "TVHTML5_SIMPLY_EMBEDDED_PLAYER",
    "clientVersion": "2.0",
    "clientNameHeader": "85",
    "userAgent": "Mozilla/5.0 (ChromiumStylePlatform) Cobalt/25.lts.30.1034943-gold (unlike Gecko), Unknown_TV_Unknown_0/Unknown (Unknown, Unknown)",
    "hl": "en",
    "gl": "US",
}


def _grab_str(block: str, key: str) -> str:
    m = re.search(rf"'{key}'\s*:\s*'([^']*)'", block)
    return m.group(1) if m else ""


def _grab_int(block: str, key: str):
    m = re.search(rf"'{key}'\s*:\s*(\d+)", block)
    return int(m.group(1)) if m else None


def parse_ytdlp_clients(py_text: str) -> list[dict]:
    m = re.search(r"INNERTUBE_CLIENTS\s*=\s*\{", py_text)
    if not m:
        raise RuntimeError("Could not locate INNERTUBE_CLIENTS dict in yt-dlp _base.py")
    start = m.end()
    end_match = re.search(r"\n\}\s*\n", py_text[start:])
    root_block = py_text[start : start + end_match.start()] if end_match else py_text[start : start + 25000]

    parsed: list[dict] = []
    seen_names: set[str] = set()

    for key, display_name in TARGET_KEYS:
        km = re.search(rf"^\s{{4}}'{key}'\s*:\s*\{{", root_block, re.M)
        if not km:
            continue
        sub_start = km.start()
        next_key = re.search(r"^\s{4}'[a-z0-9_]+'\s*:\s*\{", root_block[km.end():], re.M)
        entry_block = root_block[sub_start : km.end() + next_key.start()] if next_key else root_block[sub_start:]
        client_name = _grab_str(entry_block, "clientName") or display_name
        client_ver = _grab_str(entry_block, "clientVersion")
        user_agent = _grab_str(entry_block, "userAgent")
        client_id = _grab_int(entry_block, "INNERTUBE_CONTEXT_CLIENT_NAME")
        if not client_ver:
            continue

        obj = {
            "name": client_name,
            "clientName": client_name,
            "clientVersion": client_ver,
            "hl": "en",
            "gl": "US",
        }
        if client_id is not None:
            obj["clientNameHeader"] = str(client_id)
        if user_agent:
            obj["userAgent"] = user_agent
        for str_field in ("deviceMake", "deviceModel", "osName", "osVersion"):
            val = _grab_str(entry_block, str_field)
            if val:
                obj[str_field] = val
        sdk = _grab_int(entry_block, "androidSdkVersion")
        if sdk is not None:
            obj["androidSdkVersion"] = sdk

        parsed.append(obj)
        seen_names.add(client_name)

    if "ANDROID_TESTSUITE" not in seen_names:
        parsed.append(FALLBACK_TESTSUITE)
    if "TVHTML5_SIMPLY_EMBEDDED_PLAYER" not in seen_names:
        parsed.append(FALLBACK_TV_EMBED)

    return parsed


def main():
    req = urllib.request.Request(YTDLP_BASE_URL, headers={"User-Agent": "Mozilla/5.0 (ext-remote-config-sync)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        source_py = resp.read().decode("utf-8", errors="replace")

    clients = parse_ytdlp_clients(source_py)
    if len(clients) < 3:
        raise RuntimeError(f"Unexpectedly small parsed client list: {clients}")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    rules = config.setdefault("dynamic_engine_rules", {})
    rules["ytdlp_innertube_clients"] = clients
    rules["innertube_clients"] = clients
    rules["ytdlp_synced_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[SYNC] Updated {len(clients)} yt-dlp InnerTube clients -> {CONFIG_PATH.name}")
    for c in clients:
        print(f"  - {c['clientName']} v{c['clientVersion']} (header={c.get('clientNameHeader')}, ua={c.get('userAgent', '')[:48]})")


if __name__ == "__main__":
    main()
