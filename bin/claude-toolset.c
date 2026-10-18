// Versioned maintenance tools, macOS 12+. No app/profile/credential access.
// Package identity comes from a separately trusted manifest SHA-256.
// User-owned files/verifiers do not resist a malicious process of that user.
#include <CommonCrypto/CommonDigest.h>
#include <sys/acl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <sys/xattr.h>
#include <mach-o/dyld.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pwd.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef MCD_TOOLSET_SOURCE_SHA
#define MCD_TOOLSET_SOURCE_SHA "unbound"
#endif

struct item { const char *name; mode_t mode; bool public; };
static const struct item items[] = {
    {"claude-apps-refresh.sh", 0700, true},
    {"claude-build-worker.sh", 0700, false},
    {"claude-cache-worker.sh", 0700, false},
    {"claude-checkpoint-worker.sh", 0700, false},
    {"claude-checkpoint.c", 0600, false},
    {"claude-clear-caches.sh", 0700, true},
    {"claude-instance-check.sh", 0700, true},
    {"claude-instances-common.sh", 0600, false},
    {"claude-integrity.c", 0600, false},
    {"claude-maintenance.h", 0600, false},
    {"claude-profile-checkpoint.sh", 0700, true},
    {"claude-recolor-icon.sh", 0700, true},
    {"claude-recolor-icon.swift", 0600, false},
    {"claude-stale-check.sh", 0700, true},
    {"claude-toolset.c", 0600, false},
    {"claude-toolset.sh", 0700, false},
    {"claude-transaction.c", 0600, false},
};
#define COUNT (sizeof(items) / sizeof(items[0]))
#define MANIFEST_MAX 4096
#define FILE_MAX (16 * 1024 * 1024)
struct manifest { char bytes[MANIFEST_MAX + 1], commit[41], hashes[COUNT][65]; size_t size; };
struct operation { char previous[65], requested[65], boot_previous[65], boot_requested[65]; };
static char home_path[PATH_MAX], root_path[PATH_MAX];
static dev_t root_device;

static void fail(const char *message) { fprintf(stderr, "toolset: %s\n", message); exit(1); }
static void syserr(const char *message) { fprintf(stderr, "toolset: %s: %s\n", message, strerror(errno)); exit(1); }
static bool hex(const char *s, size_t length) {
    if (strlen(s) != length) return false;
    for (size_t i = 0; i < length; i++) if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f'))) return false;
    return true;
}
static struct stat info(int fd) { struct stat s; if (fstat(fd, &s)) syserr("cannot inspect descriptor"); return s; }
static bool same(struct stat a, struct stat b) {
    return a.st_dev == b.st_dev && a.st_ino == b.st_ino && a.st_mode == b.st_mode && a.st_uid == b.st_uid &&
        a.st_gid == b.st_gid && a.st_nlink == b.st_nlink && a.st_size == b.st_size && a.st_flags == b.st_flags &&
        a.st_mtimespec.tv_sec == b.st_mtimespec.tv_sec && a.st_mtimespec.tv_nsec == b.st_mtimespec.tv_nsec &&
        a.st_ctimespec.tv_sec == b.st_ctimespec.tv_sec && a.st_ctimespec.tv_nsec == b.st_ctimespec.tv_nsec;
}
static void acl_check(int fd) {
    acl_t acl = acl_get_fd_np(fd, ACL_TYPE_EXTENDED);
    if (!acl) { if (errno == ENOENT) return; syserr("cannot inspect ACL"); }
    acl_entry_t entry; int rc = acl_get_entry(acl, ACL_FIRST_ENTRY, &entry);
    while (rc == 0) {
        acl_tag_t tag;
        if (acl_get_tag_type(entry, &tag) || tag != ACL_EXTENDED_DENY) fail("custom allow/unknown ACL");
        rc = acl_get_entry(acl, ACL_NEXT_ENTRY, &entry);
    }
    int saved = errno; acl_free(acl);
    if (rc != -1 || saved != EINVAL) fail("unknown ACL enumeration result");
}
// macOS adds com.apple.provenance to files created by many app-launched
// processes; it records the creator for Gatekeeper and is not file content.
// It is the only attribute tolerated (and not copied); any other one fails.
static bool only_provenance_attribute(int fd) {
    ssize_t length = flistxattr(fd, NULL, 0, 0);
    if (length < 0) return false;
    if (length == 0) return true;
    if (length > 64 * 1024) return false;
    char buffer[64 * 1024 + 1];
    if (flistxattr(fd, buffer, (size_t)length, 0) != length) return false;
    for (size_t offset = 0; offset < (size_t)length;) {
        size_t size = strnlen(buffer + offset, (size_t)length - offset);
        if (!size || size == (size_t)length - offset || strcmp(buffer + offset, "com.apple.provenance")) return false;
        offset += size + 1;
    }
    return true;
}
static void check(int fd, bool directory, bool private, mode_t mode, dev_t device) {
    struct stat s = info(fd);
    if ((directory ? !S_ISDIR(s.st_mode) : !S_ISREG(s.st_mode)) || s.st_uid != getuid() ||
        (s.st_mode & 07022) || s.st_flags || (!directory && s.st_nlink != 1) ||
        (device && device != s.st_dev) || (private && (s.st_mode & 07777) != mode))
        fail("unsafe type, owner, permissions, links, flags or volume");
    acl_check(fd);
    if (!directory && !only_provenance_attribute(fd)) fail("file attributes are unsupported");
}
static int open_dir(int parent, const char *name, bool private, bool create, dev_t device) {
    if (create && mkdirat(parent, name, 0700) && errno != EEXIST) syserr("cannot create private directory");
    int fd = openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW_ANY | O_CLOEXEC);
    if (fd < 0) syserr("cannot open directory without symlinks");
    check(fd, true, private, 0700, device);
    return fd;
}
static int open_file(int parent, const char *name, bool private, mode_t mode, dev_t device) {
    int fd = openat(parent, name, O_RDONLY | O_NOFOLLOW_ANY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) syserr("cannot open regular file without symlinks");
    check(fd, false, private, mode, device);
    return fd;
}
static void named(int parent, const char *name, struct stat opened) {
    struct stat s;
    if (fstatat(parent, name, &s, AT_SYMLINK_NOFOLLOW) || !same(s, opened)) fail("named entry changed");
}
static void sync_fd(int fd) {
    int rc; do { rc = fsync(fd); } while (rc && errno == EINTR);
    if (rc) syserr("sync failed; inspect retained operation");
}
static void write_all(int fd, const void *bytes, size_t size) {
#ifdef MCD_TOOLSET_TESTING
    if (getenv("MCD_TOOLSET_ENOSPC")) { errno = ENOSPC; syserr("injected write failure"); }
#endif
    size_t offset = 0;
    while (offset < size) {
        ssize_t n = write(fd, (const char *)bytes + offset, size - offset);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) syserr("cannot write file");
        offset += (size_t)n;
    }
}
static size_t read_text(int parent, const char *name, char *out, size_t capacity, bool private, dev_t device) {
    int fd = open_file(parent, name, private, 0600, device);
    struct stat before = info(fd);
    if (before.st_size < 0 || (uint64_t)before.st_size >= capacity) fail("text record too large");
    size_t size = 0;
    while (size < capacity) {
        ssize_t n = read(fd, out + size, capacity - size);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) syserr("cannot read text record");
        if (!n) break;
        size += (size_t)n;
    }
    if (size >= capacity || size != (size_t)before.st_size || memchr(out, 0, size) || !same(before, info(fd)))
        fail("partial, changed or malformed text record");
    named(parent, name, before); close(fd); out[size] = 0;
    return size;
}
static void create_text(int parent, const char *name, const char *bytes, size_t size) {
    int fd = openat(parent, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) syserr("cannot create exclusive text record");
#ifdef MCD_TOOLSET_TESTING
    const char *fault = getenv("MCD_TOOLSET_FAIL");
    if (fault && !strcmp(fault, "partial-journal") && !strcmp(name, "operation.txt")) {
        write_all(fd, bytes, 8); sync_fd(fd); errno = ENOSPC; syserr("injected partial operation record");
    }
#endif
    write_all(fd, bytes, size); sync_fd(fd);
    if (close(fd)) syserr("cannot close text record");
}
static void digest_bytes(const void *bytes, size_t size, char out[65]) {
    unsigned char hash[CC_SHA256_DIGEST_LENGTH];
    if (size > UINT32_MAX || !CC_SHA256(bytes, (CC_LONG)size, hash)) fail("hash failed");
    for (size_t i = 0; i < sizeof(hash); i++) snprintf(out + i * 2, 3, "%02x", hash[i]);
}
static void hash_copy(int parent, const char *name, char out[65], bool private, mode_t mode, dev_t device, int destination) {
    int fd = open_file(parent, name, private, mode, device);
    struct stat before = info(fd);
    if (before.st_size < 0 || before.st_size > FILE_MAX) fail("file exceeds supported size");
    CC_SHA256_CTX ctx; unsigned char hash[32]; char buffer[65536]; off_t total = 0;
    if (!CC_SHA256_Init(&ctx)) fail("hash init failed");
    for (;;) {
        ssize_t n = read(fd, buffer, sizeof(buffer));
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) syserr("cannot read source file");
        if (!n) break;
        total += n; if (total > FILE_MAX) fail("growing file exceeds bound");
        if (!CC_SHA256_Update(&ctx, buffer, (CC_LONG)n)) fail("hash update failed");
        if (destination >= 0) write_all(destination, buffer, (size_t)n);
    }
    if (total != before.st_size || !same(before, info(fd))) fail("source changed while reading");
    check(fd, false, private, mode, device); named(parent, name, before); close(fd);
    if (!CC_SHA256_Final(hash, &ctx)) fail("hash final failed");
    for (size_t i = 0; i < sizeof(hash); i++) snprintf(out + i * 2, 3, "%02x", hash[i]);
}
static void exact_entries(int fd, const char *const *allowed, size_t count) {
    int fresh = openat(fd, ".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fresh < 0) syserr("cannot enumerate directory");
    DIR *dir = fdopendir(fresh); if (!dir) syserr("cannot create directory observer");
    size_t seen = 0; struct dirent *entry; errno = 0;
    while ((entry = readdir(dir))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        bool accepted = false;
        for (size_t i = 0; i < count; i++) if (!strcmp(entry->d_name, allowed[i])) accepted = true;
        if (!accepted || ++seen > count) fail("unexpected package entry");
        errno = 0;
    }
    if (errno || seen != count) fail("missing entry or unknown enumeration result");
    if (closedir(dir)) syserr("cannot close directory observer");
}
static void consume(const char **p, const char *text) {
    size_t n = strlen(text); if (strncmp(*p, text, n)) fail("malformed canonical record"); *p += n;
}
static void take_hash(const char **p, char out[65], bool optional) {
    if (optional && !strncmp(*p, "none\n", 5)) { strcpy(out, "none"); *p += 5; return; }
    if (strlen(*p) < 65) fail("truncated digest");
    memcpy(out, *p, 64); out[64] = 0;
    if (!hex(out, 64) || (*p)[64] != '\n') fail("invalid digest");
    *p += 65;
}
static struct manifest manifest_read(int root, const char *expected, bool private) {
    struct manifest m = {0}; char hash[65];
    if (!hex(expected, 64)) fail("expected manifest SHA-256 must be lowercase hex");
    m.size = read_text(root, "manifest.txt", m.bytes, sizeof(m.bytes), private, info(root).st_dev);
    digest_bytes(m.bytes, m.size, hash);
    if (strcmp(hash, expected)) fail("manifest does not match the separately trusted digest");
    const char *p = m.bytes; consume(&p, "MCD_TOOLSET 1\nprotocol 1\ncommit ");
    if (strlen(p) < 41) fail("truncated commit");
    memcpy(m.commit, p, 40); m.commit[40] = 0;
    if (!hex(m.commit, 40) || p[40] != '\n') fail("invalid commit identifier");
    p += 41;
    for (size_t i = 0; i < COUNT; i++) {
        char prefix[128];
        snprintf(prefix, sizeof(prefix), "file %s %04o ", items[i].name, items[i].mode);
        consume(&p, prefix); take_hash(&p, m.hashes[i], false);
    }
    if (*p) fail("extra manifest bytes");
    return m;
}
static struct manifest verify_package(int release, const char *hash, bool private) {
    const char *roots[] = {"bin", "manifest.txt"}; exact_entries(release, roots, 2);
    struct manifest m = manifest_read(release, hash, private);
    int bin = open_dir(release, "bin", private, false, info(release).st_dev);
    const char *names[COUNT]; for (size_t i = 0; i < COUNT; i++) names[i] = items[i].name;
    exact_entries(bin, names, COUNT);
    for (size_t i = 0; i < COUNT; i++) {
        char actual[65]; hash_copy(bin, items[i].name, actual, private, items[i].mode, info(release).st_dev, -1);
        if (strcmp(actual, m.hashes[i])) fail("payload file does not match manifest");
    }
    exact_entries(bin, names, COUNT); exact_entries(release, roots, 2);
    close(bin); return m;
}
static void paths(void) {
    struct passwd *pw = getpwuid(getuid()); if (!pw || !pw->pw_dir) fail("cannot establish user home");
    const char *selected = pw->pw_dir;
#ifdef MCD_TOOLSET_TESTING
    if (getenv("MCD_TOOLSET_TEST_HOME")) selected = getenv("MCD_TOOLSET_TEST_HOME");
#endif
    if (selected[0] != '/' || !realpath(selected, home_path) || strcmp(selected, home_path)) fail("home must be physical and absolute");
    if (snprintf(root_path, sizeof(root_path), "%s/.local/share/claude-instances/toolsets", home_path) >= (int)sizeof(root_path))
        fail("home path too long");
}
static int root_open(bool create) {
    int fd = open_dir(AT_FDCWD, home_path, false, false, 0);
    const char *parts[] = {".local", "share", "claude-instances", "toolsets"};
    for (size_t i = 0; i < 4; i++) {
        int next = open_dir(fd, parts[i], i >= 2, create, info(fd).st_dev);
        close(fd); fd = next;
    }
    root_device = info(fd).st_dev; return fd;
}
static int lock_root(int root, bool exclusive) {
    int fd = openat(root, ".toolset.lock", O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC, 0600);
    if (fd < 0) syserr("cannot open installation lock");
    check(fd, false, true, 0600, root_device);
    if (flock(fd, (exclusive ? LOCK_EX : LOCK_SH) | LOCK_NB)) syserr("another toolset operation holds the lock");
    named(root, ".toolset.lock", info(fd)); return fd;
}
static bool exists(int parent, const char *name) {
    struct stat s; if (!fstatat(parent, name, &s, AT_SYMLINK_NOFOLLOW)) return true;
    if (errno != ENOENT) syserr("cannot inspect entry"); return false;
}
static void current_read(int root, char out[65]) {
    if (!exists(root, "current")) { strcpy(out, "none"); return; }
    char bytes[66]; size_t n = read_text(root, "current", bytes, sizeof(bytes), true, root_device);
    if (n != 65 || bytes[64] != '\n') fail("malformed current pointer");
    bytes[64] = 0; if (!hex(bytes, 64)) fail("invalid current pointer"); strcpy(out, bytes);
}
static int release_open(int root, const char *hash) {
    if (!hex(hash, 64)) fail("invalid release identifier");
    int versions = open_dir(root, "releases", true, false, root_device);
    int release = open_dir(versions, hash, true, false, root_device); close(versions);
    verify_package(release, hash, true); return release;
}
static void stop_at(const char *point) {
#ifdef MCD_TOOLSET_TESTING
    const char *wanted = getenv("MCD_TOOLSET_STOP");
    if (wanted && !strcmp(wanted, point)) raise(SIGSTOP);
    const char *failure = getenv("MCD_TOOLSET_FAIL");
    if (failure && !strcmp(failure, point)) fail("injected fixture failure");
#else
    (void)point;
#endif
}
static void rename_exact(int from, const char *name, int to, const char *target, unsigned flags) {
#ifdef MCD_TOOLSET_TESTING
    if (getenv("MCD_TOOLSET_RENAME_UNSUPPORTED")) { errno = ENOTSUP; syserr("atomic rename unavailable; no fallback"); }
#endif
    if (renameatx_np(from, name, to, target, flags | RENAME_NOFOLLOW_ANY)) syserr("atomic rename failed; no fallback");
    sync_fd(from); sync_fd(to);
}
static void run_checked(char *const arguments[], const char *temporary) {
    pid_t pid = fork(); if (pid < 0) syserr("cannot fork compiler/parser");
    if (!pid) {
        char temporary_env[PATH_MAX + 8]; snprintf(temporary_env, sizeof(temporary_env), "TMPDIR=%s", temporary);
        char *environment[] = {"PATH=/usr/bin:/bin:/usr/sbin:/sbin", "LANG=C", temporary_env, NULL};
        execve(arguments[0], arguments, environment); _exit(127);
    }
    int status; pid_t result;
    do { result = waitpid(pid, &status, 0); } while (result < 0 && errno == EINTR);
    if (result != pid || !WIFEXITED(status) || WEXITSTATUS(status)) fail("syntax/compilation preflight failed; candidate retained");
}
static void preflight(const char *release_path, const char *stage_path) {
    for (size_t i = 0; i < COUNT; i++) {
        char path[PATH_MAX], output[PATH_MAX];
        if (snprintf(path, sizeof(path), "%s/bin/%s", release_path, items[i].name) >= (int)sizeof(path) ||
            snprintf(output, sizeof(output), "%s/check-%zu", stage_path, i) >= (int)sizeof(output)) fail("preflight path too long");
        size_t length = strlen(items[i].name);
        if (!strcmp(items[i].name + length - 3, ".sh")) {
            char *args[] = {"/bin/bash", "-p", "-n", path, NULL}; run_checked(args, stage_path);
        } else if (!strcmp(items[i].name + length - 2, ".c")) {
            char *plain[] = {"/usr/bin/clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-mmacosx-version-min=12.0", path, "-o", output, NULL};
            char *cf[] = {"/usr/bin/clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-mmacosx-version-min=12.0", "-framework", "CoreFoundation", path, "-o", output, NULL};
            run_checked(!strcmp(items[i].name, "claude-integrity.c") ? cf : plain, stage_path);
        }
    }
}
static void make_stage(int root, char name[42], char path[PATH_MAX]) {
    unsigned char random[16]; arc4random_buf(random, sizeof(random)); strcpy(name, ".install-");
    for (size_t i = 0; i < sizeof(random); i++) snprintf(name + 9 + i * 2, 3, "%02x", random[i]);
    if (mkdirat(root, name, 0700)) syserr("cannot create exclusive operation directory");
    if (snprintf(path, PATH_MAX, "%s/%s", root_path, name) >= PATH_MAX) fail("operation path too long");
    fprintf(stderr, "toolset: retained operation %s\n", name);
}
static size_t operation_text(struct operation *op, char bytes[512]) {
    int n = snprintf(bytes, 512, "MCD_TOOLSET_OPERATION 1\nprevious %s\nrequested %s\nbootstrap_previous %s\nbootstrap_requested %s\n",
        op->previous, op->requested, op->boot_previous, op->boot_requested);
    if (n < 0 || n >= 512) fail("operation record too large"); return (size_t)n;
}
static struct operation operation_read(int stage) {
    char bytes[512], canonical[512]; struct operation op = {0};
    size_t size = read_text(stage, "operation.txt", bytes, sizeof(bytes), true, root_device);
    const char *p = bytes; consume(&p, "MCD_TOOLSET_OPERATION 1\nprevious "); take_hash(&p, op.previous, true);
    consume(&p, "requested "); take_hash(&p, op.requested, false);
    consume(&p, "bootstrap_previous "); take_hash(&p, op.boot_previous, true);
    consume(&p, "bootstrap_requested "); take_hash(&p, op.boot_requested, false);
    if (*p || operation_text(&op, canonical) != size || memcmp(bytes, canonical, size)) fail("noncanonical operation record");
    return op;
}
static void bootstrap_hash(int root, char out[65]) {
    if (!exists(root, "dispatcher")) { strcpy(out, "none"); return; }
    hash_copy(root, "dispatcher", out, true, 0700, root_device, -1);
}
static void switch_release(int root, int stage, const char *hash, bool bootstrap) {
    struct operation op = {0}; char bytes[512], current[65], boot[65];
    current_read(root, op.previous); strcpy(op.requested, hash); bootstrap_hash(root, op.boot_previous);
    if (bootstrap) hash_copy(stage, "dispatcher", op.boot_requested, true, 0700, root_device, -1);
    else strcpy(op.boot_requested, op.boot_previous);
    if (!hex(op.boot_requested, 64)) fail("dispatcher missing; install a reviewed package first");
    snprintf(bytes, sizeof(bytes), "%s\n", hash); create_text(stage, "current", bytes, 65);
    size_t length = operation_text(&op, bytes); create_text(stage, "operation.txt", bytes, length);
    sync_fd(stage); sync_fd(root); stop_at("journal-synced");
    current_read(root, current); bootstrap_hash(root, boot);
    if (strcmp(current, op.previous) || strcmp(boot, op.boot_previous)) fail("activation layout changed");
    if (bootstrap) {
        rename_exact(stage, "dispatcher", root, "dispatcher", !strcmp(boot, "none") ? RENAME_EXCL : RENAME_SWAP);
        stop_at("bootstrap-published");
    }
    current_read(root, current); bootstrap_hash(root, boot);
    if (strcmp(current, op.previous) || strcmp(boot, op.boot_requested)) fail("activation layout changed after dispatcher publication");
    rename_exact(stage, "current", root, "current", !strcmp(current, "none") ? RENAME_EXCL : RENAME_SWAP);
    stop_at("pointer-published");
    current_read(root, current); if (strcmp(current, hash)) fail("activation could not be confirmed");
    int release = release_open(root, current); close(release);
    printf("ACTIVE %s\n", current);
}
static void install(int root, const char *source_path, const char *hash) {
    int source = open_dir(AT_FDCWD, source_path, false, false, 0);
    struct manifest m = verify_package(source, hash, false); stop_at("package-verified");
    size_t self_index = 0;
    while (self_index < COUNT && strcmp(items[self_index].name, "claude-toolset.c")) self_index++;
    if (self_index == COUNT || strcmp(m.hashes[self_index], MCD_TOOLSET_SOURCE_SHA))
        fail("package installer source differs; use its matching reviewed installer");
    char stage_name[42], stage_path[PATH_MAX], release_path[PATH_MAX]; make_stage(root, stage_name, stage_path);
    int stage = open_dir(root, stage_name, true, false, root_device);
    int candidate = open_dir(stage, "release", true, true, root_device);
    int bin = open_dir(candidate, "bin", true, true, root_device);
    int source_bin = open_dir(source, "bin", false, false, info(source).st_dev);
    for (size_t i = 0; i < COUNT; i++) {
        int out = openat(bin, items[i].name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, items[i].mode);
        if (out < 0) syserr("cannot create payload file");
        char actual[65]; hash_copy(source_bin, items[i].name, actual, false, items[i].mode, info(source).st_dev, out);
        sync_fd(out); close(out);
        if (strcmp(actual, m.hashes[i])) fail("payload changed during copy");
        stop_at("file-copied");
    }
    close(source_bin); close(source); create_text(candidate, "manifest.txt", m.bytes, m.size);
    sync_fd(bin); sync_fd(candidate); close(bin);
    verify_package(candidate, hash, true); close(candidate);
    if (snprintf(release_path, sizeof(release_path), "%s/release", stage_path) >= (int)sizeof(release_path)) fail("release path too long");
    preflight(release_path, stage_path); stop_at("preflight-passed");
    uint32_t length = PATH_MAX; char executable[PATH_MAX], physical[PATH_MAX];
    if (_NSGetExecutablePath(executable, &length) || !realpath(executable, physical)) fail("cannot locate running installer");
    int image = openat(stage, "dispatcher", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0700);
    if (image < 0) syserr("cannot create dispatcher candidate");
    char image_hash[65]; hash_copy(AT_FDCWD, physical, image_hash, false, 0700, 0, image); sync_fd(image); close(image);
    int versions = open_dir(root, "releases", true, true, root_device);
    if (exists(versions, hash)) {
        int existing = release_open(root, hash); close(existing);
    } else rename_exact(stage, "release", versions, hash, RENAME_EXCL);
    close(versions); stop_at("release-published");
    switch_release(root, stage, hash, true); close(stage);
}
static void activate(int root, const char *hash) {
    int release = release_open(root, hash); close(release);
    char name[42], path[PATH_MAX]; make_stage(root, name, path);
    int stage = open_dir(root, name, true, false, root_device);
    switch_release(root, stage, hash, false); close(stage);
}
static void inspect(int root, const char *name) {
    if (strlen(name) != 41 || strncmp(name, ".install-", 9) || !hex(name + 9, 32)) fail("invalid operation name");
    int stage = open_dir(root, name, true, false, root_device); struct operation op = operation_read(stage); close(stage);
    char current[65], boot[65]; current_read(root, current); bootstrap_hash(root, boot);
    if ((strcmp(current, op.previous) && strcmp(current, op.requested)) ||
        (strcmp(boot, op.boot_previous) && strcmp(boot, op.boot_requested))) fail("UNKNOWN; layout differs from operation");
    if (strcmp(op.previous, op.requested) && !strcmp(current, op.requested) && strcmp(boot, op.boot_requested))
        fail("UNKNOWN; requested pointer without requested dispatcher");
    int requested = release_open(root, op.requested); close(requested);
    if (strcmp(current, "none")) { int release = release_open(root, current); close(release); }
    const char *state = !strcmp(current, "none") ? "NO_ACTIVE_RELEASE" :
        (!strcmp(current, op.requested) ? "REQUESTED_RELEASE_ACTIVE" : "PREVIOUS_RELEASE_ACTIVE");
    printf("%s dispatcher=%s\n", state,
        !strcmp(boot, op.boot_requested) ? "requested" : "previous");
}
int main(int argc, char **argv) {
    umask(077);
    if (!getuid() || getuid() != geteuid()) fail("use the ordinary user, without sudo/setuid");
    if (argc == 2 && !strcmp(argv[1], "protocol")) { printf("protocol 1\nsource %s\n", MCD_TOOLSET_SOURCE_SHA); return 0; }
    paths();
    if (argc == 2 && !strcmp(argv[1], "where")) { puts(root_path); return 0; }
    if (argc == 4 && !strcmp(argv[1], "package-check")) {
        int source = open_dir(AT_FDCWD, argv[2], false, false, 0); verify_package(source, argv[3], false);
        stop_at("package-verified"); puts("PACKAGE_VERIFIED"); close(source); return 0;
    }
    bool installing = argc == 4 && !strcmp(argv[1], "install");
    bool activating = argc == 3 && !strcmp(argv[1], "activate");
    bool inspecting = argc == 3 && !strcmp(argv[1], "inspect");
    bool status = argc == 2 && !strcmp(argv[1], "status"), verify = argc == 2 && !strcmp(argv[1], "verify");
    bool run = argc >= 3 && !strcmp(argv[1], "run");
    if (!installing && !activating && !inspecting && !status && !verify && !run)
        fail("use install PACKAGE TRUSTED_SHA256 | activate SHA256 | inspect OPERATION | status | verify | run ENTRY [ARGS]");
    if (installing && !hex(argv[3], 64)) fail("invalid trusted package digest");
    int root = root_open(installing), lock = lock_root(root, installing || activating);
    if (installing) install(root, argv[2], argv[3]);
    else if (activating) activate(root, argv[2]);
    else if (inspecting) inspect(root, argv[2]);
    else {
        char current[65]; current_read(root, current);
        if (!strcmp(current, "none")) fail("no active tool release");
        int release = release_open(root, current); close(release);
        if (run) {
            bool allowed = false; for (size_t i = 0; i < COUNT; i++) if (items[i].public && !strcmp(argv[2], items[i].name)) allowed = true;
            if (!allowed) fail("entry is not a public tool");
            char script[PATH_MAX];
            if (snprintf(script, sizeof(script), "%s/releases/%s/bin/%s", root_path, current, argv[2]) >= (int)sizeof(script)) fail("entry path too long");
            char **args = calloc((size_t)argc + 1, sizeof(char *)); if (!args) syserr("cannot allocate entry arguments");
            args[0] = "/bin/bash"; args[1] = "-p"; args[2] = script;
            for (int i = 3; i < argc; i++) args[i] = argv[i];
            close(lock); close(root); execv(args[0], args); syserr("cannot execute pinned entry");
        }
        printf("VERIFIED_ACTIVE %s (owner-writable local installation; account behavior not verified)\n", current);
    }
    close(lock); close(root); return 0;
}
