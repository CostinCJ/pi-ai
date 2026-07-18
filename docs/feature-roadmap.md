# Lache Feature Roadmap

Updated 2026-07-18. Everything from the original Tier 1/Tier 3 list shipped except richer presence sensing.

## Shipped

1. **Image analysis via Telegram** — `bot.handle_photo()` → Groq vision (`llama-4-scout`) via `brain._generate_vision_reply()`
2. **Desktop notifications (reverse channel)** — `desktop_push.py` POSTs to laptop at `DESKTOP_PUSH_URL`
3. **pattern_log** — populated by `consolidation.py` (daily, deduped against last 20); feeds `free_reasoning` trigger
4. **League of Legends integration** — `riot_client.py`: `is_in_game()` suppresses proactive messages; post-game match stats trigger → `riot_match_log`
5. **Voice messages** — `bot.handle_voice()` → Groq Whisper (`whisper-large-v3-turbo`) → normal reply path
6. **Dashboard** — Homepage (Docker, :3000) with `lache_status_api.py` (:8770, `lache-status.service`); Uptime Kuma (:3001)
7. **Offsite backups** — nightly DB dump (3:30am) + weekly restic → Backblaze B2 (Sun 5am) + monthly `restic check`; Telegram alerts on failure. See "Backups & alerting" in the master briefing.

## Remaining

### Richer presence sensing (partially built)
- `current_ssid()` and `nearby_ble_devices()` already exist in `network_radar.py` — **not wired into any trigger yet**
- Wire SSID into vibe/context (uni WiFi vs home WiFi)
- BLE scan for room-level presence
- Phone battery level (Tailscale iOS client or iOS Shortcut → session_server)

### Other ideas (from memory / older notes)
- MiniMax music generation (not started; non-personal audio data only)
- Semester schedule reset — when the new semester starts, re-verify săpt parity (`is_sapt1()` anchor) and update the hardcoded timetable in `schedule.py`
- SSH key + `PasswordAuthentication no` before ever exposing port 22 beyond LAN/Tailscale
