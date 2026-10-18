# Profile content checkpoints

This is an opt-in maintenance primitive, not a complete account backup or a
restore/downgrade feature. Normal graphical launching is unchanged. No checkpoint
is made automatically by a rebuild, watchdog or launch, and no current profile is
replaced. Installation and real-account validation remain separate release work.

## Interface and binding

With the complete reviewed `bin/claude-*` set installed, macOS 12+ and Xcode
Command Line Tools, close stock Claude, all configured copies, Claude Code CLI,
editors and other programs using either selected profile. Then:

```sh
claude-profile-checkpoint.sh create Personal
claude-profile-checkpoint.sh verify Personal <printed-checkpoint-UUID>
```

The fixed storage location is
`~/Library/Application Support/Multi Claude Desktop/Checkpoints/<UUID>/`.
It contains `desktop/`, `code/` and a canonical `manifest.txt`. Directories are
0700; files are 0600, or 0700 if the source had its owner-execute bit set.
The source is read only; its access time may change as with other file reads.
Original timestamps and other users' permission bits are not preserved.

The binding is SHA-256 of a versioned, NUL-delimited tuple: configured instance
name, bundle ID, both canonical profile paths, app version and SHA-256 results for
Info.plist, the Claude executable, launcher and CodeResources. Both source roots
must already exist. Local launcher/signature checks are required. Verification
under another instance, path pair or changed app bytes fails. This is an
accidental-mismatch check, not an authenticated manifest or proof of restore
compatibility. The current app/config are needed for this verification interface;
there is no override to accept a different build.

The manifest stores only digests, not tokens, source paths or file names. The
copied data can still contain **credentials, conversations and private code**.
Owner-only permissions do not encrypt it. Keep checkpoints and pending staging
out of Git, logs, support uploads and public artifacts. There is no automatic
retention/deletion; copies consume their full data size and can exhaust storage.
Existing legacy `Claude*.backup-*` directories are not imported or deleted.

## Closed-source observations and publication

1. Compile the two reviewed native helpers privately. Take the same inherited
   kernel lock as app publication and cache cleanup. Reject a legacy refresh
   lock. This serializes these cooperating maintenance tools.
2. Require stock/configured apps stopped and a successful Desktop profile process
   observation. Before each open-file scan, require `lsof` to see a synthetic file
   held open by the observer itself. Lack of visibility fails closed.
3. Run `/usr/sbin/lsof -nP -F p +D` on each source. A match, diagnostic or unexpected
   result refuses the operation. Only exit 1 with empty output/diagnostics is
   accepted as a no-match observation. The upstream [lsof manual](https://lsof.readthedocs.io/en/stable/manpage/)
   documents recursive selection, permission limits and exit semantics. These
   observations cannot establish visibility of every other process.
4. In private `.pending-<UUID>`, open roots/children through descriptors without
   following links. Hash both source trees, copy both, compare copy-pass source
   observations, then read/hash both sources again. A deterministic tree digest
   includes sorted byte names with length prefixes, node types, file lengths,
   owner-execute bits and all file bytes. A separate source witness includes
   device/inode, mode, ownership, link count, size, flags, mtime and ctime for every
   node. Each traversal also checks metadata before/after reading and named-child
   identity. Output is independently read and verified.
5. Sync copied files/directories, write/sync the exclusive 0600 manifest and
   sync private staging/parent metadata. Return from preparation without publishing.
6. Repeat process/open-file observations. Recheck app bytes and local launcher/
   signature under the cooperating lock. Before commit, re-read the manifest,
   output trees and both source trees, comparing all recorded source witnesses.
7. Publish the entire pair with one `renameatx_np(RENAME_EXCL |
   RENAME_NOFOLLOW_ANY)` on the storage volume, then sync the parent. An existing
   UUID is never overwritten. Unsupported/failed atomic operations have no move,
   overwrite or delete fallback.

`verify` accepts only the published UUID name, exact manifest grammar, the three
expected root entries, safe private metadata, matching binding and full output
hashes. A pending directory cannot be supplied as a checkpoint UUID. Corruption,
extra bytes/entries, wrong identity and unknown layouts fail closed. Nothing is
executed from profile contents or interpreted as shell code.

On interruption/failure, `.pending-<UUID>` is retained privately for inspection;
it may contain sensitive partial data. There is no automatic retry, replay,
promotion, resume or pruning. A SIGKILL after publication leaves the published
pair verifiable even if the caller did not receive success. A later sync error
also requires inspection; failure alone does not prove publication did not occur.

## Unsupported metadata and remaining limits

Only user-owned regular files/directories, without group/other write access,
set-ID/sticky bits, file flags, cross-device entries, hardlinked files, symlinks,
special files, ACL entries or extended attributes are accepted. The one exception
is `com.apple.provenance`, which macOS adds to files created by many app-launched
processes; it records the creator, is not file content and is not copied. Any
other attribute, including `com.apple.quarantine`, still fails. The helper does
not skip offending files, dereference links, strip metadata from the source or
silently return an incomplete backup. This stricter checkpoint policy also
rejects deny ACL entries that the normal launcher can allow. Real Code/Cowork
profiles may contain unsupported objects, large VM images or links; refusal is
expected until a separately reviewed metadata-aware format exists. Do not remove
security metadata or links from real profiles just to satisfy this primitive.

Multiple equal observations are **not a point-in-time filesystem snapshot or
an application transaction**. Another program can start/write after a check;
an idle CLI can later resume without keeping a handle open. Observations, inode
witnesses and the cooperating lock reduce accidental races but cannot prevent
external/same-user writers, or prove application-level database consistency.
Root and other administrators are also outside this boundary. The local manifest
is modifiable by its owner and is not a security boundary against that owner.
Fsync and SIGKILL tests do not certify power-loss/hardware-cache durability.

There is deliberately **no restore command** and no import/extraction of arbitrary
archives. A future restore must validate this pair's binding and full contents,
copy into fresh managed UUID paths with exclusive creation, leave live profiles
untouched, validate app/schema compatibility and require a reviewed switch. This
format alone does not preserve all source metadata or make binary rollback safe.
Keychain credentials, macOS/TCC permissions, external projects, external Cowork
locations, system settings and account/SSO validity are not backed up or tested.

## Validation scope

The offline suite tests both native filesystem behavior and worker policy using
invented data only. It covers partial copy/SIGKILL, before/after-publication
states, concurrent destinations, source content/root changes, app/pair mismatch,
malformed manifests, tampering, unsafe objects/metadata, unknown observations and
the shared rebuild/cache/checkpoint lock. Fault/stop injection is compiled only
with `MCD_CHECKPOINT_TESTING`; production builds ignore those variables. No real
profile is copied, no Claude executable is launched and no login is required.
