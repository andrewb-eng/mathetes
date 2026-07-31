# Scheduling the daily run (macOS launchd)

`run_daily.sh` pulls the feeds, expires vanished listings, and scores the three
tiers. Nothing scheduled it before, so it only ran when invoked by hand.

A LaunchAgent is used rather than cron because launchd survives reboots and,
with `StartCalendarInterval`, runs a missed job shortly after the Mac wakes
instead of skipping the day.

## Install

```bash
mkdir -p ~/Library/Logs/mathetes && cp ~/Desktop/mathetes/deploy/com.andrewbrown.mathetes.daily.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.andrewbrown.mathetes.daily.plist
```

## Verify it is registered

```bash
launchctl print gui/$(id -u)/com.andrewbrown.mathetes.daily | head -20
```

## Force a run now (does not wait for 07:30)

```bash
launchctl kickstart -p gui/$(id -u)/com.andrewbrown.mathetes.daily
```

## Read the log

```bash
tail -n 80 ~/Library/Logs/mathetes/daily.log
```

## Uninstall

```bash
launchctl bootout gui/$(id -u)/com.andrewbrown.mathetes.daily && rm ~/Library/LaunchAgents/com.andrewbrown.mathetes.daily.plist
```

## Why the agent does not run `run_daily.sh`

The repo lives under `~/Desktop`, which macOS protects with TCC. **A LaunchAgent
running `/bin/bash` is denied read access to files there.** The obvious plist —
`ProgramArguments = [/bin/bash, .../run_daily.sh]` — fails before the script ever
starts:

```
shell-init: error retrieving current directory: getcwd: cannot access parent directories: Operation not permitted
/bin/bash: /Users/andrewbrown/Desktop/mathetes/run_daily.sh: Operation not permitted
```

This was isolated with a control agent run from an unprotected directory. The
denial is specific, not blanket — from a LaunchAgent context:

| Action | Result |
|---|---|
| `cd` into the repo | works |
| run `venv/bin/python` | works |
| python reads `.env`, `db.py`, the DB | works |
| `bash`/`head` read `run_daily.sh` | **Operation not permitted** |

So the interpreter is fine; `/bin/bash` is the thing being denied. The plist
therefore invokes `venv/bin/python daily.py` directly and omits
`WorkingDirectory` (launchd chdir-ing into the protected path is what produces
the `getcwd` error). `daily.py` holds the actual steps and `run_daily.sh` is a
one-line `exec` into it, so the manual and scheduled paths cannot drift.

If you ever move the repo somewhere unprotected (`~/mathetes`), none of this
applies — but update the two absolute paths in the plist, and rebuild the venv,
which has its original path baked in.

## The log is appended, never rotated

It grows slowly (a few KB per run). If it gets unwieldy:
`: > ~/Library/Logs/mathetes/daily.log`.

## Cost

`run_daily.sh` caps each tier at `--limit 60`, so one unattended run can spend at
most 180 Haiku calls even if the 2027 cycle opens with a surge. Anything past the
cap stays queued for the next day. Typical delta right now is well under 10 calls.
