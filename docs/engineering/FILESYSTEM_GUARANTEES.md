# Transfer guarantees per filesystem (measured 2026-11-23, macOS, Phase 1b)

Measured on freshly created disk images (APFS, HFS+, FAT32, exFAT) mounted in a temporary folder — never on a
physical drive. exFAT and FAT32 are served by macOS's user-space FSKit drivers on this system. The same measurements
run on every test pass (`tests/test_phase1b_transfer_service.py::TestFilesystems`).

| Primitive | APFS | HFS+ | FAT32 (msdos) | exFAT |
|---|---|---|---|---|
| `renamex_np(RENAME_EXCL)` to a free name | ✔ | ✔ | ✔ | **ENOTSUP** |
| `renamex_np(RENAME_EXCL)` onto an existing file | EEXIST (file kept) | EEXIST | EEXIST | EEXIST |
| `link()` to a free name | ✔ | ✔ | ENOTSUP | **ENOTSUP** |
| `open(O_CREAT\|O_EXCL)` | ✔ | ✔ | ✔ | ✔ |
| plain `rename()` onto an existing file | overwrites | overwrites | overwrites | overwrites |
| `F_FULLFSYNC` | ✔ | ✔ | ✔ | ✔ |
| directory `fsync` | ✔ | ✔ | ✔ | ✔ |
| case-insensitive names (default format) | yes | yes | yes | yes |
| `statfs` type name | `apfs` | `hfs` | `msdos` | `exfat` |

## What Percival guarantees
Every file is published with an **exclusive commit**: `renamex_np(RENAME_EXCL)`, or `link()`+`unlink()` when the
former is unavailable. Both are atomic and fail if the name exists, so **no existing file can be overwritten — including
a file created by another process between Percival's checks and its commit**. There is no check-then-rename fallback.

| Destination filesystem | Writing (archive, sync, stage, copy, move, restore) | Reading (source) |
|---|---|---|
| APFS, HFS+, FAT32 | allowed — exclusive commit guaranteed | allowed |
| **exFAT** | **refused** with a clear error before any data is copied; also refused at commit if the preflight is bypassed | allowed |
| unknown type | attempted; refused at commit if neither primitive works (the `.part` is removed, nothing published) | allowed |

## Limitations (stated, not hidden)
- **exFAT cannot be a write target.** It offers no atomic "create this name only if free" for a finished file, so the
  never-overwrite guarantee cannot be met. An exFAT Vault can be staged *from*, but Percival will not archive *to* it.
  The user decides whether a Vault should be reformatted (Percival never formats or reorganises a drive).
- FAT32 and exFAT have no journal: a power loss during a commit may need a filesystem repair. Percival's journal records
  every committed file, so recovery (milestone 1c) can tell what is where.
- The uncached read-back (`F_NOCACHE`) proves what macOS reads back from the device. It cannot prove that a drive's
  own internal cache has reached the platters.
- Replacing a file (stage over an existing local copy, File Manager "replace") moves the old version aside first with
  an exclusive rename, and publishes the new file exclusively. The old version is removed only after the whole job
  is verified, and it is moved back if any commit of the job fails. Files inside the Vault are never replaced.
