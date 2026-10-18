# Atomic bundle publication and interruption inspection

The clone fallback now preserves the destination name during replacement. It
does not implement account migration or promise a safe downgrade of data.

## Protocol

The entry script validates config and compiles `claude-transaction.c` with the
system compiler in an owner-only temporary directory. It starts a Bash worker
under a nonblocking kernel `flock` on the application's volume. The lock is
held on inherited descriptor 9 across the worker and children; it is not tied
to a PID file or a directory that becomes stale. The named lock file remains
after exit and must not be removed to bypass an active lock.

The worker checks the original identity/nested signature/Gatekeeper, copies into
a private
`.claude-txn.XXXXXXXX` directory on the destination volume, edits/signs/verifies
the candidate and checks that the destination app is stopped. The worker
also checks planned source changes and persists a private full-tree build
record selected by the app's UUID marker before publication. See
[APP_INTEGRITY.md](APP_INTEGRITY.md). The native helper opens root/stage
directories without symlinks, checks ownership/modes
and ACLs, and writes the immutable `transaction.txt` with exclusive creation.
The file is 0600, the directory 0700. Its versioned, canonical text records an
ASCII instance name and root/stage/old/new device and inode identities. It
contains no account tokens, environment values or profile contents.
Numeric fields use checked unsigned conversions and canonical serialization;
overflow, signs, extra bytes and noncanonical records are refused.

The journal file and parent metadata are synced before the namespace operation.
The helper verifies the prepared layout, then performs one
`renameatx_np(..., RENAME_SWAP | RENAME_NOFOLLOW_ANY)` for an existing target,
or `RENAME_EXCL | RENAME_NOFOLLOW_ANY` for a first install. It syncs parent
metadata and checks the resulting layout. The worker checks the published
launcher/signature again. The original app is never a destination.

There is no `rm`/`mv` fallback. An unsupported atomic operation leaves the
recorded old layout and prepared candidate for inspection. A partial journal
or failure after exchange is also retained rather than triggering a blind
second swap. Ordinary failures before a journal exists clean up their own
unprepared staging directory. SIGKILL may leave such staging/compile files;
restart does not guess ownership of an unfinished operation and delete them.

## Inspection after interruption

Use the transaction identifier printed by the builder with
`claude-apps-refresh.sh --recover .claude-txn.XXXXXXXX`. This acquires the same
kernel lock and checks the exact record/current-layout correspondence:

| Observed state | Destination | Transaction's `instance.app` slot |
|---|---|---|
| PREPARED replacement | Recorded old inode | Recorded new inode |
| PREPARED first install | Absent | Recorded new inode |
| COMMITTED replacement | Recorded new inode | Recorded old inode |
| COMMITTED first install | Recorded new inode | Absent |

Any other layout fails closed. Committed inspection additionally verifies the
current configured launcher and local signature. It never executes the app,
replays the rename, swaps back, restores data or deletes files. It can run even
if the original source app is unavailable, but needs valid current config and
the local compiler. Changed config or a later rebuild/updater can make an
older journal's layout unknown/superseded; inspection does not infer history
from a filename, timestamp or version string.

## Guarantees and limits

- Tests use actual Darwin namespace/lock/ACL/sync calls, including SIGKILL before
  and after exchange. Fault points exist only with a test compilation macro.
- Atomic namespace exchange is not a power-loss durability guarantee. The
  helper does not recursively sync every app resource or promise a hardware
  cache flush. See Apple's [rename manual](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/man/man2/rename.2)
  and [fsync manual](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/man/man2/fsync.2).
- The lock coordinates these tools. It cannot prevent Finder, an updater,
  another capable process of the same user, root, or another administrator
  with write access to `/Applications` from changing files or launching apps.
- Inode fingerprints and a user-owned journal are not authenticated provenance
  or an adversarial tamper-proof store. Bundle checks retain the documented
  limitations of ad-hoc signatures and expected-launcher comparison.
- Previous bundles/journals are retained without automatic pruning. This costs
  disk space, particularly across updates. Reviewed retention and cleanup are
  separate work; an old copy must not be treated as current merely because it
  remains on disk.
- A retained bundle keeps its existing bundle identifier. LaunchServices/Dock
  routing with retained copies needs graphical validation; do not open archived
  bundles as an improvised restore. The scratch signing check does not register
  or launch them.
- A retained bundle is not necessarily known-good, a profile backup, a project
  checkpoint or a Keychain export. Opening a newer app may migrate profiles.
  Compatible closed-profile backup/restore and rollback gates remain pending.
- Rebuild/recovery and full verification require macOS 12+, Xcode Command Line Tools and filesystem
  support for the requested operations. Daily graphical app launch is unchanged.
