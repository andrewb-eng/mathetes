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

## Two things that will bite you

**The repo lives in `~/Desktop`, which macOS protects (TCC).** A background
LaunchAgent gets no GUI permission prompt, so if macOS decides to block it the
job fails with a permissions error in the log rather than asking. If that
happens, either grant Full Disk Access to `/bin/bash` in System Settings →
Privacy & Security → Full Disk Access, or move the repo somewhere unprotected
(`~/mathetes`) and update the three absolute paths in the plist. Verified
working under a stripped environment at install time, but TCC behaviour can
change after an OS update — check the log if runs go quiet.

**The log is appended, never rotated.** It grows slowly (a few KB per run), but
if it ever gets unwieldy: `: > ~/Library/Logs/mathetes/daily.log`.

## Cost

`run_daily.sh` caps each tier at `--limit 60`, so one unattended run can spend at
most 180 Haiku calls even if the 2027 cycle opens with a surge. Anything past the
cap stays queued for the next day. Typical delta right now is well under 10 calls.
