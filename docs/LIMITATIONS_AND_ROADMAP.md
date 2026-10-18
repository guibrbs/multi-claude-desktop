# Residual limitations and improvement proposal

The [current execution roadmap in Portuguese](ROADMAP_PT_BR.md) supersedes the
historical delivery order below. It reflects the security-first scope, defers
the new native GUI prototype, and separates fixture evidence from the pending
two-account graphical release gate. The numbered review remains the historical
technical baseline described below, with implemented follow-ups recorded here.
The current deployment preference is the unchanged official app for one account
and one managed copy for the other. Reserve the default Desktop/Code pair for
the original and name the copy **Claude Duo**. Plan verified rebuilds after official updates. Automatic
rebuild orchestration and reviewed legacy transition are not implemented.
The explicit `original-copy` parser policy and versioned toolset installer are
now implemented and tested in disposable fixtures; see
[TOOLSET_INSTALLATION.md](TOOLSET_INSTALLATION.md). No installed tools/apps or
profiles were migrated. This follow-up has **137 passing offline tests** locally;
remote results for the implementation commit are recorded in the PR.

## Decision

Keep PR #1 in draft until two-account **graphical Code** login and lifecycle
tests pass. The existing hardening is useful, but fixture tests and a
real signing/rebuild check do not establish account separation end to end.

The largest prospective improvement is a graphical launcher that starts the
**unchanged Anthropic-signed app** with separate profiles. Investigate it before
investing in distributing modified Claude bundles. This is a hypothesis to
validate, not an implemented or officially supported Claude multi-account mode.

The review below concerns commit `c4b8a044e9944302dbe935ce079c3ba087f94af6`
and the local Claude 2.42304.0 signing/rebuild baseline. The numbered review
describes that baseline; the follow-up status
is recorded separately here. Controlled baseline results are in
[evidence/residual-limitations.json](evidence/residual-limitations.json).

## Implemented security follow-up

The environment/path follow-up now implements a subscription-only environment
allowlist, a minimal child environment, rejection of all caller arguments,
proxy detection/refusal, managed/legacy location constraints, a complete
Desktop/Code overlap graph, owner/mode/ACL checks and a non-root requirement.
Icons/locks and watchdog logs also use checked private paths; linked logs are
refused. Status separates version comparison and local signature checks from
account/provenance claims. See [HARDENING.md](../HARDENING.md) for compatibility.

The environment/path milestone passed **41 offline tests** on Apple Silicon.
A separate real
Claude 2.42304.0 scratch build/rebuild and signature check passed, without
opening the vendor executable. The original signature and critical file hashes
were unchanged. Sanitized results are in
[evidence/security-policy-follow-up.json](evidence/security-policy-follow-up.json).
Neither result establishes graphical Code login, SSO, session continuity or
account separation. The native GUI experiment is deferred while security fixes
are prioritized. The PR remains a draft and installed apps are unchanged.

The newly added macOS CI runs the offline suite on Apple Silicon and Intel.
CI does not install Claude, run GUI/account tests, obtain credentials or verify
Anthropic signatures; those remain separate evidence requirements.

## Implemented publication follow-up

Publication now uses a locally compiled C helper with directory descriptors,
no-follow flags and a kernel lock inherited across the worker and children.
An existing bundle is exchanged with `RENAME_SWAP`; a first install uses
`RENAME_EXCL`. Unsupported/failed operations have no delete/move fallback.
An immutable intention journal is written and synced before publication and
the old bundle remains in its private transaction directory after exchange.
`--recover` observes the recorded inode layout and checks a committed
launcher/signature without replaying or undoing the operation.

The publication milestone passed **60 tests**, including 14 native transaction tests.
They exercise actual macOS rename/lock/ACL/sync operations, kill disposable
helpers before/after exchange, check exclusive-publication conflicts, and
refuse malformed/linked journals or uncertain layouts. Failure/stop injection
is enabled only in a test compilation; production builds ignore its variables.
See [ATOMIC_PUBLICATION.md](ATOMIC_PUBLICATION.md) for the protocol and limits.

This addresses the two-rename gap and stale cooperating-process locks. It does
not provide power-loss durability, automatic rollback, compatible profile
restore, automatic retention pruning or isolation from external/same-user
programs. A previous bundle is retained, not certified known-good.

## Implemented checkpoint prerequisite

An opt-in content checkpoint now copies the configured Desktop/Code pair into
private pending staging, verifies full tree hashes and repeated source metadata
witnesses, binds to the pair/app bytes and publishes exclusively as one directory.
It refuses observed users/unknown observations, verifies the open-file observer's
own visibility probe and rechecks sources before commit. Cache cleanup now shares
the native maintenance lock with rebuilds/checkpoints. Partial staging is retained
and cannot be accepted as a published checkpoint. See
[PROFILE_CHECKPOINTS.md](PROFILE_CHECKPOINTS.md) for the protocol and strict format.

This is a prerequisite for reviewed migration/restore, not completion of that
roadmap item. There is no restore, schema compatibility proof, Keychain/project
backup or point-in-time snapshot. Links, ACLs, extended attributes (other than
the OS-managed `com.apple.provenance`, which is not copied) and other unsupported
metadata cause refusal rather than silent omission. Real accounts
and installed apps/profiles remain untouched.

The current suite passes **85 offline tests**: the earlier 60 plus 18 native
checkpoint tests and 7 checkpoint/maintenance policy tests. A separate synthetic
integration check uses actual `lsof` and a different process holding a fixture
file open: idle creation/verification succeeds and the open handle prevents any
new staging/publication. Signature/Claude process observations remain mocked;
this does not validate real account contents or login. Sanitized results and
tested code hashes are in [evidence/profile-checkpoints.json](evidence/profile-checkpoints.json).

## Implemented integrity and native maintenance follow-up

The new builder authenticates the source and its nested code, checks unchanged
resources, validates the planned plist transformation and creates a private
full-tree record before atomic publication. Verification, watchdog and checkpoint
prerequisites now reject content/structure/mode drift even after local
re-signing. All entry/worker scripts fix PATH before command resolution.
See [APP_INTEGRITY.md](APP_INTEGRITY.md) for the exact allowlist, signed-script
detached metadata and local-record trust boundary. Records remain user-writable;
there is no claim of authenticated provenance against that owner.

Mutating workers now use native PID/path/start-time observations, without
argv/environment reads, and require all observed Desktop apps/helpers closed.
Cache cleanup requires the shared inherited lock, independently validates profile
locations, preflights fixed slots, moves them exclusively into private quarantine
and removes through no-follow descriptors. Uncertainty retains quarantine rather
than replaying/deleting a guessed path. See [NATIVE_MAINTENANCE.md](NATIVE_MAINTENANCE.md).
Read-only textual profile diagnostics and the inability to exclude external
writers remain limitations. No installed app/profile was changed.

This milestone passed **106 offline tests**, including real descriptor cleanup
faults and production PID/path observations on a tiny fixture executable. An
isolated copy of real Claude 2.42304.0 also passed source/nested/Gatekeeper,
build/content checks and an inert-resource re-sign test: the new local signature
passed while content-record verification rejected the drift. Original critical
bytes/signature stayed unchanged; no vendor executable was launched or account
used. See [evidence/integrity-maintenance.json](evidence/integrity-maintenance.json).

## Threat model and evidence limits

We can reduce accidental configuration mixing, unsafe imports, corrupted or
incomplete installs, unnoticed updates, and misleading health reports. We
cannot make two applications running as the same Unix user into mutually
distrustful security compartments. A process with sufficient access as that
user can alter launchers, profiles, scripts, or local manifests. No remote
exploit or active credential theft was demonstrated.

Evidence is separated into: observed fixture behavior, real metadata/signing
checks on a scratch bundle, documented platform capabilities, and unvalidated
design proposals. No login, token extraction, real account traffic interception,
or production profile mutation was performed for this analysis.

## 1. Signing removes capabilities as well as provenance

The original executable has hardened runtime and Anthropic identity. Its
entitlement keys include `allow-jit`, application/team identifiers, Keychain
access groups, Apple Events and virtualization capabilities. The installed
ad-hoc executable has no entitlements in the metadata collected. Values of
non-Boolean entitlements were intentionally not collected. This is stronger
evidence of a compatibility gap than a simple valid/invalid signature test.

The current [signing step](../bin/claude-apps-refresh.sh) intentionally
uses ad-hoc signatures. Consequences can include SSO/Keychain changes and
feature-specific failures. A successful ordinary chat or Code launch would not
validate all these capabilities.

Two possible improvements:

- Preferred investigation: keep the Claude bundle unchanged and sign/notarize
  only our own graphical launcher with our own developer identity.
- Optional clone experiment: restore hardened runtime with a narrowly reviewed
  entitlement set where technically possible. Apple's library validation
  normally requires Apple or matching-team libraries, so mixed-team frameworks
  must be tested and may require a limited exception. Do not copy team-bound
  entitlements blindly. This cannot recover Anthropic's Team ID, private
  Keychain groups or approval of the modified app. See [Apple's hardened runtime
  guide](https://help.apple.com/xcode/mac/current/en.lproj/devf87a2ac8f.html) and
  [library validation documentation](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.cs.disable-library-validation).

Acceptance: compare executable flags, entitlement keys, original signature,
runtime behavior, login/SSO and local Code operations. Internal `codesign`
success alone is insufficient.

## 2. A verified launcher does not authenticate every resource

Current [verification](../bin/claude-instances-common.sh) checks
identity, the complete expected launcher, and the bundle's own signature. In a
new disposable real clone, adding an inert JS resource and re-signing locally
still produced a successful `--verify`. The marker was never executed. This
demonstrates the distinction between local signature consistency and provenance;
it does not demonstrate a remote attacker modifying the app.

Proposal: separate status into **source authenticity**, **copy content integrity**,
**GUI compatibility**, and **version freshness**. Store a build record with the
source identity/CDHash, app/build versions, generator version, non-secret config
digest and expected resource hashes. Detect unexplained resources and code
changes. Protect records with owner-only permissions and validate releases.

A user-writable manifest detects drift and accidental replacement, not a
malicious process that can rewrite both app and manifest. Preserving the
vendor-signed app provides a stronger provenance check against local ad-hoc
re-signing. Never present one generic green “safe” state.

## 3. Code configuration isolation is not complete account isolation

The parent launcher can set `CLAUDE_CONFIG_DIR`, but GUI Code may also obtain
configuration from shell initialization, its local environment editor, shared
files, project hooks/MCP definitions and managed settings. The current README's
former blanket statement that shell initialization has no effect was too broad
for the Code subprocess. The official [Desktop configuration reference](https://code.claude.com/docs/en/desktop#shared-configuration)
documents shared configuration; its [local environment section](https://code.claude.com/docs/en/desktop#local-sessions)
also describes selected shell-variable loading. Therefore parent environment
inspection alone is not an end-to-end test.

The [authentication documentation](https://code.claude.com/docs/en/authentication#log-in-with-multiple-accounts)
supports separate Code configuration directories but explicitly excludes
keyless Console sign-ins from that separation. Those CLI rules do not prove all
GUI/SSO flows are independent.

Proposal: define supported login types and verify effective Code subprocess
behavior using harmless per-profile canaries in isolated test workspaces. Do
not implement our own OAuth client, scrape tokens or copy account sessions to
make a failing mode appear to work. Show a profile label as a label, not as proof
of the account that will receive a request. Have users confirm the actual GUI
account after login. Use separate repositories/worktrees to avoid accidental
edits crossing accounts, while clearly stating that worktrees are not security
sandboxes.

Required GUI matrix: first login A/B; restart in both launch orders; resume
sessions; start local Code tasks concurrently; logout/re-authenticate B while A
continues; refresh credentials; receive login callbacks; update/rebuild; revoke
permissions; and test any supported enterprise SSO. Record app version,
architecture and macOS version without recording tokens or private transcripts.

## 4. Baseline environment gaps (launcher restrictions now implemented)

The baseline parser validated keys and blocked
several loader/shell overrides, but controlled checks still accepted
`ELECTRON_RUN_AS_NODE`, `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY`. A fixture
child inherited a synthetic API-key value from the parent, and the launcher
forwarded `--no-sandbox`. These are local configuration/launch conditions, not
proven credential leakage from GUI Claude.

Implemented for the launcher: subscription-account mode allows only the
profile and Code directory configuration. The child has a minimal
environment, every caller argument is rejected, and endpoint/provider/credential
overrides in the config are refused. An inherited proxy causes refusal instead
of silent removal. No advanced provider/proxy mode is implemented. Never store
tokens in the plain instance-definition file or log env values.

The GUI Code shell/environment layers must also be checked: sanitizing only the
launcher's initial environment may be insufficient. Preserve required toolchain
paths and enterprise policy; do not suppress managed settings or break an
approved corporate proxy under the label of hardening.

## 5. Baseline path gaps (managed/legacy restrictions now implemented)

The baseline directory policy rejected a few dangerous roots and compared
Desktop directories with Desktop directories and Code directories with Code
directories. Controlled checks accepted nested Desktop profiles, a Code
directory equal to another Desktop profile, and `/etc` as a profile in `--list`.
No system directory was modified. Normal user permissions limit actual writes,
but accepting the configuration is still an avoidable hazard, particularly if
someone runs the builder elevated.

Implemented: managed UUID directories and the existing flat Claude legacy
layout are the only accepted locations. Root execution, foreign ownership,
group/other write permissions and custom allow ACLs are refused. Every
Desktop/Code pair is checked for equality/nesting with physical paths and case
folding; printable-ASCII legacy suffixes avoid Unicode normalization aliases.
The config must be inside home with checked ownership and ancestors. Arbitrary
existing paths have no automatic exception. Paths are rechecked before mutation
and launch, but these observations cannot defeat a same-user racing process.
Per-user app destinations and descriptor-based lifecycle coordination remain
follow-ups.

For legacy Personal, offer a closed-app, explicit backup-and-clone migration to
a new managed directory. Do not move/delete the old profile or silently change
bundle IDs. Test history, login and Code continuity before committing migration.

## 6. Process snapshots do not lock the application lifecycle

[Process observation](../bin/claude-instances-common.sh) now fails
closed, which helps, but `ps` command text is not a lossless argv representation.
Repeated snapshots and a rebuild lock cannot stop an external program or stock
Claude from starting after a check. Personal still shares stock Claude's default
profile. Owner-only modes do not constrain another process of the same user.

Proposal: a small native lifecycle helper should track PID plus start time,
executable identity and requested profile, and coordinate managed launch/update
operations with profile locks. Read structured argument boundaries where
necessary, discard environment data and never log it. Detect externally launched
instances and refuse destructive maintenance on uncertain state. Native locks
coordinate cooperating processes only; they cannot enforce exclusivity against
all same-user launches. Strong confidentiality still requires separate OS
users, separate appropriately configured machines, or similarly real boundaries.

## 7. Baseline rename gap (atomic publication now implemented)

The baseline used two publication renames, leaving a gap. Its cleanup traps
could not run after SIGKILL/power loss, the lock lacked a recovery journal and
the prior bundle was deleted after success. Most importantly, an older executable
may not understand a profile migrated by a newer version: binary rollback alone
does not restore data compatibility.

Implemented: a native same-filesystem helper exchanges an existing target with
`RENAME_SWAP` or publishes a first install with `RENAME_EXCL`, using directory
descriptors, no-follow policies and an owner-only intention journal. The actual
operation fails closed if unsupported; no weaker replacement is attempted.
The old bundle is retained and a kernel lock replaces the stale directory-lock
protocol for new runs. Legacy directory locks remain subject to inspection.
The [Apple rename manual](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/man/man2/rename.2)
and [header](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h)
define these facilities. Native tests now cover real exchanges/exclusive
publication, SIGKILL on both sides of exchange and lock release.

Atomic namespace exchange is not proof of durable storage after power failure.
The journal and parent directory metadata are synced, but the helper does not
recursively sync all app data or guarantee hardware cache flush. Recovery only
classifies known inode layouts; unknown/partial/superseded records are never
replayed or deleted. A consistent closed-profile backup/checkpoint and reviewed
retention limits remain follow-ups. Treat Keychain state and project files as
outside a simple bundle backup. Never promise safe downgrade after a schema
migration without testing the matching profile restore path.

## 8. Updating a modified app remains fragile

The original updater does not become a profile manager because a launcher was
added. A copied app may try to update its own path, lose its custom identity,
or change credentials/permissions. Updating stock Claude while it shares the
Personal profile also remains a collision risk. Version equality with the
source is not evidence that either is the vendor's latest supported release.

Proposal: a graphical maintenance flow should detect drift, present which
profiles/apps are affected, ask users to close them, validate the official
source and stage a rebuild. Do not auto-quit active tasks. Do not patch private
updater internals or strip quarantine to bypass failures. Keep a tested-version
compatibility record and represent freshness as unknown when not established.

Prefer the unchanged-app mode if it passes the GUI matrix: this eliminates
duplicated modified bundles, but still requires testing updates while multiple
profiles are open. Install our own related scripts/helper as a versioned set so
an interrupted copy cannot combine incompatible components.

## Architecture candidate: graphical manager + unchanged Claude

The manager owns labels, managed profile directories, lifecycle metadata and
non-secret diagnostics. A small native helper authenticates the exact selected
Claude bundle and invokes `NSWorkspace` with a new application instance,
per-profile arguments and a configured environment. No vendor executable,
Info.plist, updater or resource is changed.

Apple documents [new-instance creation](https://developer.apple.com/documentation/appkit/nsworkspace/openconfiguration/createsnewapplicationinstance),
[arguments](https://developer.apple.com/documentation/appkit/nsworkspace/openconfiguration/arguments)
and [environment](https://developer.apple.com/documentation/appkit/nsworkspace/openconfiguration/environment).
The installed SDK additionally warns that the system may add environment
variables and that sandboxed callers' custom argument property is ignored.
Design and test the helper's entitlement/sandbox model accordingly. There is no
claim that setting an environment dictionary erases all inherited or later
shell-derived values.

The unchanged app retains one vendor bundle identity. Separate Dock colors,
Keychain namespaces, login callback routing, Electron singleton behavior and
multi-process account behavior therefore cannot be assumed. Electron's own
[single-instance API](https://www.electronjs.org/docs/latest/api/app#apprequestsingleinstancelockadditionaldata)
is another application-level policy beyond the OS launch request. Use stable
labels in the manager if the running Dock tiles stay identical.

**Go/no-go:** promote this mode only if both GUI accounts and Code sessions stay
independent across the full lifecycle matrix without modifying Claude or
copying/extracting credentials. If Keychain or callback routing cannot be made
reliable through supported launch behavior, keep the mode experimental and
retain a clearly labeled clone fallback or recommend OS-user separation.

## Prioritized delivery proposal

Priority is release order, not a claim of a remotely exploitable CVSS severity.
S/M/L is relative scope, not a calendar estimate.

| Order | Deliverable | Scope | Completion criterion |
|---|---|---|---|
| P0 | GUI account/authentication evidence | M, manual component | Two-account lifecycle matrix passes; supported login types listed |
| P0 | Explicit env/argv policy and managed path graph | M | Inherited sentinel, unsafe flag, nested/cross-type/system path cases blocked or explicitly approved by mode |
| P0 | Accurate trust reporting and documented threat model | S | Signature consistency is never presented as account/provenance certification |
| P1 | Unchanged signed-app launch spike | M/L | Native helper proof plus GUI go/no-go decision; no credential copying |
| P1 | Atomic publication and journaled recovery for clone fallback | M | Tested swap/exclusive publish, injected failures, killed-process recovery and retained previous release |
| P1 | Consistent migration/backup and restore protocol | M/L | Closed-profile backups; documented Keychain exclusions; matched version/profile restore test |
| P1 | macOS CI and compatibility record | M | Fixture tests and syntax checks in CI; real app/GUI checks explicitly reported separately |
| P2 | Versioned installer and signed/notarized manager distribution | L | Install our own components transactionally; verify provenance without impersonating Anthropic |
| P2 | Graphical profile/update/recovery controls | M/L | Daily operation requires no CLI; no silent task termination; diagnostics contain no secrets |

Suggested follow-up PRs: (1) environment/path policy, (2) lifecycle evidence and
truthful status, (3) unchanged-app experiment, (4) native transaction/recovery,
(5) distribution/GUI. Gate each architectural switch on observed behavior.
The regression tests remain behavior coverage, not a security percentage.

## What cannot be fixed solely in this repository

- Anthropic's signing identity and team-scoped permissions cannot be recreated
  with our certificate or a stronger shell script.
- Same-UID file permissions cannot create mutual confidentiality between two
  fully capable local agents. Permission prompts remain relevant within each
  Code session; profile folders do not replace them.
- Private authentication, updater and profile-schema behavior may change with
  Claude releases. Only vendor-supported account profiles could remove that
  dependency completely.
- A universal safety guarantee cannot be inferred from passing finite tests,
  a clean static review or a local signature. The proposal reduces specific
  measured risks and records what remains unknown.
