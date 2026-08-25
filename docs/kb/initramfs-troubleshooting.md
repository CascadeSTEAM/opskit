# Fixing initramfs Boot Failures on Zorin (Ubuntu-based)

## The Problem

Laptop boots to an `initramfs>` prompt instead of loading the full system.
You'll see something like:

```
initramfs: BusyBox v1.36.1 ...
(initramfs) #
```

This may mean that the kernel loaded but couldn't mount the main filesystem.  The cause of that may be that the file system for your `root`partition is corrupted.

## The Fix (one step at a time)

### Step 1 — Type `exit`

At the `initramfs>` prompt, type `exit` and press Enter.
Sometimes the system will show you the actual error (look for `failed`, `missing`, or `error`).

### Step 2 — Find your root partition

Type:

```
blkid
```

This lists all partitions and their UUIDs. Find the one with a matching UUID to
the one shown in the boot line (`root=UUID=...`). That's your root partition
(e.g. `/dev/sda2`).

### Step 3 — Run filesystem repair

Type:

```
fsck /dev/sda2
```

Replace `/dev/sda2` with your actual root partition if it's different.

**What to expect:**
- fsck will ask you questions like `(... could be shorter. Fix?)` or
  `(... block bitmap differences. Fix?)` or `(... inode bitmap differences. Fix?)`
- Type `Y` for each one and press Enter
- fsck will fix filesystem tracking errors on the disk

When it finishes, you'll see:

```
FILE SYSTEM WAS MODIFIED
```

That's **good** — it means it fixed the problems.

### Step 4 — Reboot

Type:

```
reboot
```

The system should boot normally.

## Why This Happens

- Improper shutdown (power loss, forced power-off)
- Disk errors developing
- System crash or kernel panic during write

## If It Keeps Happening

If the initramfs prompt returns after the fix:

1. Your disk may be failing — back up data immediately
2. Try `fsck` with the `-y` flag to auto-fix everything:
   ```
   fsck -y /dev/sda2
   ```
3. Check SMART status:
   ```
   smartctl -a /dev/sda
   ```
   (requires `smartmontools` package — you'll need to boot from a Live USB first)

## Quick Reference

| Step | Command | Answer to questions |
|------|---------|-------------------|
| Find disk | `blkid` | — |
| Repair | `fsck /dev/sda2` | `Y` for each |
| Reboot | `reboot` | — |
