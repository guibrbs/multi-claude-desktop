// macOS-only publication, process metadata and cache-only maintenance.
// Never reads profile credentials or process argv/environment.
// The immutable journal records inode identities; it is not a trust certificate.
#include <sys/acl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define LOCK_NAME ".claude-instances.lock"
#define LOCK_ENV "MCD_TRANSACTION_LOCK_FD"
#define JOURNAL "transaction.txt"
#define BUNDLE "instance.app"

struct identity { uint64_t device, inode; };
struct record {
    char instance[65];
    struct identity root, stage, old, next;
    unsigned old_present;
};

static void fail(const char *message) {
    fprintf(stderr, "transaction: %s\n", message);
    exit(1);
}
static void system_fail(const char *message) {
    fprintf(stderr, "transaction: %s: %s\n", message, strerror(errno));
    exit(1);
}
static bool ascii_letter(unsigned char ch) {
    return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z');
}
static bool valid_instance(const char *name) {
    size_t length = strlen(name);
    if (!length || length > 64 || !ascii_letter((unsigned char)name[0])) return false;
    for (size_t i = 1; i < length; i++) {
        unsigned char ch = (unsigned char)name[i];
        if (!ascii_letter(ch) && !(ch >= '0' && ch <= '9') && ch != '-' && ch != '_') return false;
    }
    return true;
}
static bool valid_stage(const char *name) {
    if (strlen(name) != 20 || strncmp(name, ".claude-txn.", 12)) return false;
    for (size_t i = 12; i < 20; i++) {
        unsigned char ch = (unsigned char)name[i];
        if (!ascii_letter(ch) && !(ch >= '0' && ch <= '9')) return false;
    }
    return true;
}
static void check_acl(int fd) {
    acl_t acl = acl_get_fd_np(fd, ACL_TYPE_EXTENDED);
    if (!acl) {
        if (errno == ENOENT) return; // Darwin: the descriptor has no extended ACL.
        system_fail("cannot inspect ACL");
    }
    acl_entry_t entry;
    int result = acl_get_entry(acl, ACL_FIRST_ENTRY, &entry);
    while (result == 0) {
        acl_tag_t tag;
        if (acl_get_tag_type(entry, &tag)) system_fail("cannot inspect ACL entry");
        if (tag != ACL_EXTENDED_DENY) fail("custom allow ACL or unknown ACL entry");
        result = acl_get_entry(acl, ACL_NEXT_ENTRY, &entry);
    }
    // Darwin returns -1 with errno=EINVAL at the end, unlike POSIX's 0.
    if (result != -1 || errno != EINVAL) system_fail("cannot enumerate ACL");
    acl_free(acl);
}
static struct stat descriptor_stat(int fd) {
    struct stat value;
    if (fstat(fd, &value)) system_fail("cannot inspect descriptor");
    return value;
}
static struct identity identify(struct stat value) {
    return (struct identity){(uint64_t)value.st_dev, (uint64_t)value.st_ino};
}
static bool same(struct identity left, struct identity right) {
    return left.device == right.device && left.inode == right.inode;
}
static void sync_descriptor(int fd) {
    int result;
    do { result = fsync(fd); } while (result && errno == EINTR);
    if (result) system_fail("metadata sync failed; inspect retained transaction");
}
static int open_root(const char *path) {
    if (path[0] != '/') fail("application directory must be absolute");
    int fd = open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW_ANY | O_CLOEXEC);
    if (fd < 0) system_fail("cannot open application directory without symlinks");
    struct stat value = descriptor_stat(fd);
    // /Applications may be root:admin and group-writable. Other administrators
    // and root remain outside this tool's filesystem security boundary.
    if (!S_ISDIR(value.st_mode) || (value.st_uid != getuid() && value.st_uid != 0) || (value.st_mode & S_IWOTH))
        fail("unsafe application directory");
    check_acl(fd);
    return fd;
}
static void check_lock_file(struct stat value) {
    if (!S_ISREG(value.st_mode) || value.st_uid != getuid() || value.st_nlink != 1 || (value.st_mode & 07777) != 0600)
        fail("lock must be an owned, private regular file with one link");
}
static int lock_root(int root, bool inherited_only) {
    const char *inherited = getenv(LOCK_ENV);
    if (inherited) {
        if (strcmp(inherited, "9")) fail("invalid inherited lock descriptor");
        struct stat held = descriptor_stat(9), named;
        if (fstatat(root, LOCK_NAME, &named, AT_SYMLINK_NOFOLLOW)) system_fail("cannot inspect named lock");
        check_lock_file(held);
        check_lock_file(named);
        if (!same(identify(held), identify(named))) fail("inherited lock does not match this application directory");
        check_acl(9);
        if (flock(9, LOCK_EX | LOCK_NB)) system_fail("inherited lock unavailable");
        return 9;
    }
    if (inherited_only) fail("worker requires an inherited transaction lock");
    int fd = openat(root, LOCK_NAME, O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK, 0600);
    if (fd < 0) system_fail("cannot open transaction lock");
    check_lock_file(descriptor_stat(fd));
    check_acl(fd);
    if (flock(fd, LOCK_EX | LOCK_NB)) system_fail("another rebuild/recovery holds the lock");
    if (fd != 9) {
        if (dup2(fd, 9) < 0) system_fail("cannot retain transaction lock");
        close(fd);
    }
    if (fcntl(9, F_SETFD, 0)) system_fail("cannot inherit transaction lock");
    if (setenv(LOCK_ENV, "9", 1)) system_fail("cannot set lock descriptor");
    return 9;
}
static int open_stage(int root, const char *name) {
    if (!valid_stage(name)) fail("invalid transaction directory name");
    int fd = openat(root, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) system_fail("cannot open transaction directory");
    struct stat value = descriptor_stat(fd);
    if (!S_ISDIR(value.st_mode) || value.st_uid != getuid() || (value.st_mode & 07777) != 0700 || value.st_dev != descriptor_stat(root).st_dev)
        fail("transaction must be private, owned and on the application volume");
    check_acl(fd);
    return fd;
}
static bool directory_at(int parent, const char *name, struct identity *identity) {
    int fd = openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) {
        if (errno == ENOENT) return false;
        system_fail("cannot open bundle directory without following links");
    }
    struct stat value = descriptor_stat(fd);
    if (!S_ISDIR(value.st_mode) || value.st_uid != getuid() || (value.st_mode & 0022))
        fail("bundle must be owned, without group/other write access");
    check_acl(fd);
    *identity = identify(value);
    close(fd);
    return true;
}
static size_t serialize(const struct record *record, char *buffer, size_t size) {
    int length = snprintf(buffer, size,
        "MCD_TRANSACTION 1\ninstance %s\nroot %" PRIu64 " %" PRIu64 "\nstage %" PRIu64 " %" PRIu64
        "\nold %u %" PRIu64 " %" PRIu64 "\nnew %" PRIu64 " %" PRIu64 "\n",
        record->instance, record->root.device, record->root.inode, record->stage.device, record->stage.inode,
        record->old_present, record->old.device, record->old.inode, record->next.device, record->next.inode);
    if (length < 0 || (size_t)length >= size) fail("journal too large");
    return (size_t)length;
}
static void write_journal(int root, int stage, const struct record *record) {
    char buffer[512];
    size_t length = serialize(record, buffer, sizeof(buffer)), written = 0;
    int fd = openat(stage, JOURNAL, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) system_fail("journal already exists or cannot be created");
    while (written < length) {
        ssize_t count = write(fd, buffer + written, length - written);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) system_fail("cannot write journal");
        written += (size_t)count;
    }
    sync_descriptor(fd);
    if (close(fd)) system_fail("cannot close journal");
    sync_descriptor(stage);
    sync_descriptor(root);
}
static void consume(const char **cursor, const char *literal) {
    size_t length = strlen(literal);
    if (strncmp(*cursor, literal, length)) fail("malformed journal");
    *cursor += length;
}
static uint64_t number(const char **cursor) {
    if (**cursor < '0' || **cursor > '9') fail("journal requires unsigned decimal integers");
    errno = 0;
    char *end;
    uintmax_t value = strtoumax(*cursor, &end, 10);
    if (errno == ERANGE || end == *cursor || value > UINT64_MAX) fail("journal integer out of range");
    *cursor = end;
    return (uint64_t)value;
}
static struct identity parse_identity(const char **cursor) {
    struct identity value;
    value.device = number(cursor);
    consume(cursor, " ");
    value.inode = number(cursor);
    consume(cursor, "\n");
    return value;
}
static struct record read_journal(int root, int stage) {
    int fd = openat(stage, JOURNAL, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) system_fail("journal missing or unreadable; no automatic repair");
    struct stat value = descriptor_stat(fd);
    check_lock_file(value); // Same owner/mode/link policy as the lock.
    check_acl(fd);
    if (value.st_size <= 0 || value.st_size >= 512) fail("invalid journal size");
    char buffer[512] = {0}, canonical[512];
    size_t length = 0;
    while (length < sizeof(buffer) - 1) {
        ssize_t count = read(fd, buffer + length, sizeof(buffer) - 1 - length);
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) system_fail("cannot read journal");
        if (!count) break;
        length += (size_t)count;
    }
    close(fd);
    struct record record = {0};
    const char *cursor = buffer;
    consume(&cursor, "MCD_TRANSACTION 1\ninstance ");
    const char *line_end = strchr(cursor, '\n');
    if (!line_end || line_end - cursor < 1 || line_end - cursor > 64) fail("malformed journal instance");
    memcpy(record.instance, cursor, (size_t)(line_end - cursor));
    cursor = line_end + 1;
    consume(&cursor, "root "); record.root = parse_identity(&cursor);
    consume(&cursor, "stage "); record.stage = parse_identity(&cursor);
    consume(&cursor, "old ");
    uint64_t present = number(&cursor);
    if (present > 1) fail("invalid old-bundle presence flag");
    record.old_present = (unsigned)present;
    consume(&cursor, " "); record.old = parse_identity(&cursor);
    consume(&cursor, "new "); record.next = parse_identity(&cursor);
    if (cursor != buffer + length || !valid_instance(record.instance) || !record.next.inode ||
        (record.old_present ? !record.old.inode : (record.old.device || record.old.inode))) fail("malformed journal");
    size_t expected = serialize(&record, canonical, sizeof(canonical));
    if (expected != length || memcmp(buffer, canonical, length)) fail("noncanonical journal");
    if (!same(record.root, identify(descriptor_stat(root))) || !same(record.stage, identify(descriptor_stat(stage))))
        fail("journal belongs to another directory");
    return record;
}
static const char *state(int root, int stage, const struct record *record) {
    char target[80];
    snprintf(target, sizeof(target), "Claude %s.app", record->instance);
    struct identity live = {0}, candidate = {0};
    bool has_live = directory_at(root, target, &live), has_candidate = directory_at(stage, BUNDLE, &candidate);
    if (has_candidate && same(candidate, record->next) &&
        (record->old_present ? (has_live && same(live, record->old)) : !has_live)) return "PREPARED";
    if (has_live && same(live, record->next) &&
        (record->old_present ? (has_candidate && same(candidate, record->old)) : !has_candidate)) return "COMMITTED";
    fail("bundle identities changed; state unknown, nothing repaired or deleted");
    return NULL;
}
static void checkpoint(const char *name) {
#ifdef MCD_TRANSACTION_TESTING
    const char *requested = getenv("MCD_TEST_STOP");
    if (requested && !strcmp(requested, name)) raise(SIGSTOP);
#else
    (void)name;
#endif
}
static void publish(int root, int stage, const char *instance) {
    if (!valid_instance(instance)) fail("invalid instance name");
    struct record record = {0};
    memcpy(record.instance, instance, strlen(instance) + 1);
    record.root = identify(descriptor_stat(root));
    record.stage = identify(descriptor_stat(stage));
    char target[80];
    snprintf(target, sizeof(target), "Claude %s.app", instance);
    record.old_present = directory_at(root, target, &record.old);
    if (!directory_at(stage, BUNDLE, &record.next) || record.next.device != record.root.device ||
        (record.old_present && same(record.old, record.next))) fail("invalid staged bundle");
    write_journal(root, stage, &record);
    checkpoint("journal-synced");
    if (strcmp(state(root, stage, &record), "PREPARED")) fail("transaction already published");
    checkpoint("before-rename");
    unsigned flags = (record.old_present ? RENAME_SWAP : RENAME_EXCL) | RENAME_NOFOLLOW_ANY;
#ifdef MCD_TRANSACTION_TESTING
    if (getenv("MCD_TEST_RENAME_UNSUPPORTED")) { errno = ENOTSUP; system_fail("atomic rename unavailable; no fallback"); }
#endif
    if (renameatx_np(stage, BUNDLE, root, target, flags)) system_fail("atomic rename failed; no fallback, inspect retained transaction");
    checkpoint("exchanged");
    sync_descriptor(stage);
    sync_descriptor(root);
    if (strcmp(state(root, stage, &record), "COMMITTED")) fail("publication could not be confirmed");
}
#include "claude-maintenance.h"
int main(int argc, char **argv) {
    umask(077);
    if (!getuid() || getuid() != geteuid()) fail("run as the ordinary user, without sudo or setuid");
    if (argc == 2 && !strcmp(argv[1], "desktop-idle")) return maintenance_process_state(NULL);
    if (argc == 3 && !strcmp(argv[1], "app-state")) return maintenance_process_state(argv[2]);
    if (argc < 3) fail("usage: helper run|locked|clean|publish|inspect APPLICATIONS [PROFILE|TRANSACTION INSTANCE]");
    const char *command = argv[1];
    bool run = !strcmp(command, "run"), locked = !strcmp(command, "locked"), clean = !strcmp(command, "clean");
    if ((!run && !locked && !clean && strcmp(command, "publish") && strcmp(command, "inspect")) ||
        (clean && argc != 4) ||
        (run && argc < 4) || (locked && argc != 3) || (!strcmp(command, "publish") && argc != 5) || (!strcmp(command, "inspect") && argc != 4))
        fail("invalid command or argument count");
    int root = open_root(argv[2]);
    lock_root(root, locked || clean);
    if (locked) return 0;
    if (clean) { cache_clean(argv[3]); return 0; }
    if (run) {
        char resolved[PATH_MAX];
        if (!realpath(argv[0], resolved)) system_fail("cannot resolve helper executable");
        char **arguments = calloc((size_t)argc + 2, sizeof(char *));
        if (!arguments) system_fail("cannot allocate worker arguments");
        arguments[0] = "/bin/bash"; arguments[1] = "-p"; arguments[2] = argv[3]; arguments[3] = resolved;
        for (int i = 4; i < argc; i++) arguments[i] = argv[i];
        execv(arguments[0], arguments);
        system_fail("cannot start locked worker");
    }
    int stage = open_stage(root, argv[3]);
    if (!strcmp(command, "publish")) publish(root, stage, argv[4]);
    struct record record = read_journal(root, stage);
    printf("%s %s %s\n", state(root, stage, &record), record.instance, argv[3]);
    return 0;
}
