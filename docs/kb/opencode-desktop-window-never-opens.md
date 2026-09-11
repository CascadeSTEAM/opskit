# OpenCode Desktop: process "running" but the window never appears

## The Problem

The OpenCode desktop app (Electron build, `/opt/OpenCode/ai.opencode.desktop`)
launches — the process is alive, the log says the sidecar loaded — but no window
ever appears, and every further launch attempt silently does nothing. `ps` shows
a main process plus `--type=gpu-process` and `--type=utility` children, a
`SingletonLock` in `~/.config/ai.opencode.desktop`, and **no
`--type=renderer` process at all** (that absence is the tell).

Symptom to match against: "launched it again, everything seems stable, but it
did not show up", with no crash dialog and no error on screen.

## The Fix

1. Kill the wedged instance and clear its single-instance lock:
   ```
   pkill -x ai.opencode.des   # great than 15 chars, use: pkill -f '/opt/OpenCode/ai.opencode.desktop'
   ```
   Confirm `ls ~/.config/ai.opencode.desktop/SingletonLock` no longer exists.
2. Relaunch. If a window still does not appear, the app is in the
   deterministic-wedge state and one of the diagnostic launches below is the
   next step — do not just relaunch again.

Nothing else "fixes" it; the app must be killed first or every relaunch hands
off to the frozen instance.

## Why This Happens

The Electron desktop app's child-process bootstrap deadlocks: after the main
process configures the sidecar and the auto-updater, its GPU process and
network-service process park forever on futex waits, the Wayland surface /
renderer is never created, and no window exists. Because the app is
single-instance, every later launch connects to the frozen process and exits
after "app starting" — so it looks "running but open-less".

Key findings from the diagnosis that narrow this down:

- **Not a code/driver regression:** the failure began while the app binary
  (`1.18.29`), the kernel (`7.0.0-31-generic`) and the drivers were all
  unchanged from the last healthy run.
- **The VAAPI/Vulkan stderr lines are red herrings.** Both
  `vaInitialize failed: unknown libva error` and `'--ozone-platform=wayland' is
  not compatible with Vulkan` appear in journals of *healthy* runs where the
  window opened 9 seconds later and ran for 22 hours.
- **The compositor is healthy:** Chrome and Discord render fine in the same
  Wayland session while OpenCode is wedged.
- **Ruled out:** `/tmp` on `noexec` (Bun temp-dir hang), small `/dev/shm`,
  crashpad (no crash dumps — it deadlocks, it does not crash), GNOME
  extensions (the Sep 9 batch is not enabled), mangohud's implicit Vulkan
  layer (needs an explicit `MANGOHUD=1`).
- **Correlation only:** the failure streak began with the first launch after a
  day of apt churn + repeated reboots (kernel image, wazuh-agent, a codium
  update, a GNOME-shell-extension batch). No single package was proven to
  cause it.
- **Matches an upstream bug family:** opencode issues #8400 (Ubuntu: futex +
  "UI fails to load") and the Electron GPU/blank-window-on-Linux family
  (#23952, #27289, #31148). Upstream's documented Linux/Wayland escape hatch
  is launching with `OC_ALLOW_WAYLAND=1` (unset on this host).

## If It Keeps Happening / Prevention

- Before anything else: `ps -ef | grep ai.opencode.desktop | grep -c renderer`
  — if it is `0`, the window genuinely was never created (as opposed to being
  off-screen). Then kill the wedged tree; a single-instance app cannot recover
  on its own.
- Diagnostic launches, one at a time, each a fresh launch after a kill:
  - `OC_ALLOW_WAYLAND=1 /opt/OpenCode/ai.opencode.desktop` — the documented
    Wayland workaround.
  - `/opt/OpenCode/ai.opencode.desktop --disable-gpu` — if a window appears,
    the GPU-process handshake is the blocker.
- Workaround that always works: `opencode serve` (or `opencode web`) and use
  the browser UI — the full app is available there.

## Quick Reference

| Step | Command | Expected / Note |
|------|---------|-----------------|
| Diagnose | `ps -ef \| grep ai.opencode.desktop \| grep -c -- --type=renderer` | `0` ⇒ window was never created |
| Kill wedge | `pkill -f '/opt/OpenCode/ai.opencode.desktop'` | `SingletonLock` disappears from `~/.config/ai.opencode.desktop/` |
| Relaunch | `OC_ALLOW_WAYLAND=1 /opt/OpenCode/ai.opencode.desktop` | Window appears ⇒ Wayland/Ozone init issue |
| Bisect GPU | `... --disable-gpu` | Window appears ⇒ GPU-process handshake is the blocker |
| Fallback | `opencode serve` + browser | Full UI without the desktop shell |