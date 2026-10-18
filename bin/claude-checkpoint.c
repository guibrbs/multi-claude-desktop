// macOS 12+, content checkpoints only. Never restores or opens Claude accounts.
// Sources must be closed by the caller; repeated observations are not a snapshot.
#define COMMON_DIGEST_FOR_OPENSSL
#include <CommonCrypto/CommonDigest.h>
#include <sys/acl.h>
#include <sys/stat.h>
#include <sys/xattr.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>

struct digest { CC_SHA256_CTX content, witness; uint64_t entries; dev_t device; bool private; };
struct hashes { char content[65], witness[65]; };
struct record { char binding[65]; struct hashes desktop, code; };
static void fail(const char *message) {
    fprintf(stderr, "checkpoint: %s; incomplete private staging is retained for inspection\n", message);
    exit(1);
}
static void syserr(const char *message) {
    fprintf(stderr, "checkpoint: %s: %s\n", message, strerror(errno));
    exit(1);
}
static void hook(const char *point) {
#ifdef MCD_CHECKPOINT_TESTING
    const char *stop = getenv("MCD_CHECKPOINT_STOP");
    if (stop && !strcmp(stop, point)) raise(SIGSTOP);
    const char *failure = getenv("MCD_CHECKPOINT_FAIL");
    if (failure && !strcmp(failure, point)) fail("injected failure");
#else
    (void)point;
#endif
}
static void update(CC_SHA256_CTX *hash, const void *bytes, size_t length) {
    if (length > UINT32_MAX || !CC_SHA256_Update(hash, bytes, (CC_LONG)length)) fail("hash update failed");
}
static void number(CC_SHA256_CTX *hash, uint64_t value) {
    unsigned char bytes[8];
    for (int i = 7; i >= 0; i--) { bytes[i] = (unsigned char)value; value >>= 8; }
    update(hash, bytes, sizeof(bytes));
}
static void finish(CC_SHA256_CTX *hash, char text[65]) {
    unsigned char bytes[CC_SHA256_DIGEST_LENGTH];
    if (!CC_SHA256_Final(bytes, hash)) fail("hash finalization failed");
    for (size_t i = 0; i < sizeof(bytes); i++) snprintf(text + 2 * i, 3, "%02x", bytes[i]);
}
static struct stat info(int fd) {
    struct stat value;
    if (fstat(fd, &value)) syserr("cannot inspect descriptor");
    return value;
}
static bool same(struct stat a, struct stat b) {
    return a.st_dev == b.st_dev && a.st_ino == b.st_ino && a.st_mode == b.st_mode &&
        a.st_uid == b.st_uid && a.st_gid == b.st_gid && a.st_nlink == b.st_nlink &&
        a.st_size == b.st_size && a.st_flags == b.st_flags &&
        a.st_mtimespec.tv_sec == b.st_mtimespec.tv_sec && a.st_mtimespec.tv_nsec == b.st_mtimespec.tv_nsec &&
        a.st_ctimespec.tv_sec == b.st_ctimespec.tv_sec && a.st_ctimespec.tv_nsec == b.st_ctimespec.tv_nsec;
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
static void no_metadata(int fd) {
    acl_t acl = acl_get_fd_np(fd, ACL_TYPE_EXTENDED);
    if (acl) {
        acl_entry_t entry;
        errno = 0;
        int result = acl_get_entry(acl, ACL_FIRST_ENTRY, &entry), saved_errno = errno;
        acl_free(acl);
        if (result != -1 || saved_errno != EINVAL) fail("ACL entries are unsupported in content checkpoints");
    } else if (errno != ENOENT) syserr("cannot inspect ACL");
    if (!only_provenance_attribute(fd)) fail("extended attributes are unsupported; nothing is silently omitted");
}
static void check_node(int fd, struct stat value, dev_t device, bool private) {
    if (value.st_uid != getuid() || (value.st_mode & 07022) || value.st_flags || value.st_dev != device)
        fail("foreign, writable, flagged or mounted source entry");
    if (!S_ISDIR(value.st_mode) && !S_ISREG(value.st_mode)) fail("only regular files and directories are supported");
    if (S_ISREG(value.st_mode) && value.st_nlink != 1) fail("hardlinked files are unsupported");
    if (private && ((S_ISDIR(value.st_mode) && (value.st_mode & 0777) != 0700) ||
        (S_ISREG(value.st_mode) && (value.st_mode & 0777) != (0600 | (value.st_mode & 0100)))))
        fail("checkpoint tree permissions changed");
    no_metadata(fd);
}
static void witness(CC_SHA256_CTX *hash, struct stat value) {
    number(hash, (uint64_t)value.st_dev); number(hash, value.st_ino);
    number(hash, value.st_mode); number(hash, value.st_uid); number(hash, value.st_gid);
    number(hash, value.st_nlink); number(hash, (uint64_t)value.st_size); number(hash, value.st_flags);
    number(hash, (uint64_t)value.st_mtimespec.tv_sec); number(hash, (uint64_t)value.st_mtimespec.tv_nsec);
    number(hash, (uint64_t)value.st_ctimespec.tv_sec); number(hash, (uint64_t)value.st_ctimespec.tv_nsec);
}
static void sync_fd(int fd) {
    int rc;
    do { rc = fsync(fd); } while (rc && errno == EINTR);
    if (rc) syserr("cannot sync checkpoint");
}
static void write_all(int fd, const void *bytes, size_t length) {
    const unsigned char *cursor = bytes;
    while (length) {
        ssize_t count = write(fd, cursor, length);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) syserr("cannot write checkpoint");
        cursor += count; length -= (size_t)count;
    }
}
static int order_names(const void *left, const void *right) {
    return strcmp(*(char *const *)left, *(char *const *)right);
}
static char **names_in(int fd, size_t *length) {
    int duplicate = dup(fd);
    if (duplicate < 0) syserr("cannot duplicate directory");
    DIR *directory = fdopendir(duplicate);
    if (!directory) syserr("cannot enumerate directory");
    rewinddir(directory);
    char **names = NULL; size_t capacity = 0;
    *length = 0;
    for (;;) {
        errno = 0;
        struct dirent *entry = readdir(directory);
        if (!entry) { if (errno) syserr("directory enumeration failed"); break; }
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        if (*length >= 1000000) fail("directory entry limit exceeded");
        if (*length == capacity) {
            capacity = capacity ? capacity * 2 : 32;
            if (capacity > 1000000) capacity = 1000000;
            char **grown = realloc(names, capacity * sizeof(*names));
            if (!grown) syserr("cannot allocate directory list");
            names = grown;
        }
        names[*length] = strdup(entry->d_name);
        if (!names[*length]) syserr("cannot allocate entry name");
        (*length)++;
    }
    if (closedir(directory)) syserr("cannot close directory enumeration");
    if (*length) qsort(names, *length, sizeof(*names), order_names);
    return names;
}
// Keep the data buffer out of the recursive traversal's stack frame.
static void file_bytes(int source, int destination, struct digest *hash, off_t expected) {
    if (lseek(source, 0, SEEK_SET) < 0) syserr("cannot rewind source file");
    unsigned char bytes[65536]; uint64_t total = 0;
    for (;;) {
        ssize_t count = read(source, bytes, sizeof(bytes));
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) syserr("cannot read source file");
        if (!count) break;
        total += (uint64_t)count;
        if (total > (uint64_t)expected) fail("source file grew during copy");
        update(&hash->content, bytes, (size_t)count);
        if (destination >= 0) write_all(destination, bytes, (size_t)count);
    }
    if (total != (uint64_t)expected) fail("source file shrank during copy");
    if (destination >= 0) hook("file-copied");
}
static void visit(int source, int destination, struct digest *hash, unsigned depth) {
    if (depth > 128 || ++hash->entries > 1000000) fail("tree depth or entry limit exceeded");
    struct stat before = info(source);
    check_node(source, before, hash->device, hash->private);
    witness(&hash->witness, before);
    if (S_ISDIR(before.st_mode)) {
        update(&hash->content, "D", 1);
        size_t count;
        char **names = names_in(source, &count);
        number(&hash->content, count);
        for (size_t i = 0; i < count; i++) {
            struct stat named;
            if (fstatat(source, names[i], &named, AT_SYMLINK_NOFOLLOW)) syserr("cannot inspect child");
            if (!S_ISDIR(named.st_mode) && !S_ISREG(named.st_mode)) fail("symlinks and special files are unsupported");
            int child = openat(source, names[i], O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
            if (child < 0) syserr("cannot open child without following links");
            if (!same(named, info(child))) fail("child changed during open");
            number(&hash->content, strlen(names[i])); update(&hash->content, names[i], strlen(names[i]));
            int output = -1;
            if (destination >= 0) {
                if (S_ISDIR(named.st_mode)) {
                    if (mkdirat(destination, names[i], 0700)) syserr("cannot create checkpoint directory");
                    output = openat(destination, names[i], O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
                } else output = openat(destination, names[i], O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC,
                                       0600 | (named.st_mode & 0100));
                if (output < 0) syserr("cannot create checkpoint entry exclusively");
            }
            visit(child, output, hash, depth + 1);
            struct stat after;
            if (fstatat(source, names[i], &after, AT_SYMLINK_NOFOLLOW) || !same(named, after)) fail("named child changed during traversal");
            if (output >= 0) { sync_fd(output); if (close(output)) syserr("cannot close checkpoint entry"); }
            close(child); free(names[i]);
        }
        free(names);
    } else {
        update(&hash->content, "F", 1);
        number(&hash->content, before.st_mode & 0100); number(&hash->content, (uint64_t)before.st_size);
        file_bytes(source, destination, hash, before.st_size);
    }
    if (!same(before, info(source))) fail("source changed during traversal");
}
static bool absolute(const char *path) {
    if (path[0] != '/' || path[1] == '\0' || strstr(path, "//") || path[strlen(path) - 1] == '/') return false;
    const char *part = path + 1;
    while (*part) {
        size_t size = strcspn(part, "/");
        if ((size == 1 && part[0] == '.') || (size == 2 && !strncmp(part, "..", 2))) return false;
        part += size; if (*part) part++;
    }
    return true;
}
static bool overlaps(const char *left, const char *right) {
    size_t a = strlen(left), b = strlen(right), common = a < b ? a : b;
    return !strncasecmp(left, right, common) && (a == b || (a > b ? left[b] == '/' : right[a] == '/'));
}
static int open_directory(const char *path, bool private) {
    if (!absolute(path)) fail("noncanonical directory path");
    int fd = open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW_ANY | O_CLOEXEC);
    if (fd < 0) syserr("cannot open directory without symlinks");
    struct stat value = info(fd);
    check_node(fd, value, value.st_dev, private);
    return fd;
}
static void check_path(int fd, const char *path) {
    int current = open_directory(path, false);
    if (!same(info(fd), info(current))) fail("profile root path changed");
    close(current);
}
static struct hashes tree(int source, int destination, bool private) {
    struct digest hash = {.entries = 0, .device = info(source).st_dev, .private = private};
    if (!CC_SHA256_Init(&hash.content) || !CC_SHA256_Init(&hash.witness)) fail("hash initialization failed");
    update(&hash.content, "MCD_TREE_1", 10);
    visit(source, destination, &hash, 0);
    struct hashes result;
    finish(&hash.content, result.content); finish(&hash.witness, result.witness);
    return result;
}
static bool equal(struct hashes a, struct hashes b) { return !strcmp(a.content, b.content) && !strcmp(a.witness, b.witness); }
static bool hex_hash(const char *hash) {
    return strlen(hash) == 64 && strspn(hash, "0123456789abcdef") == 64;
}
static bool uuid(const char *id) {
    if (strlen(id) != 36) return false;
    for (size_t i = 0; i < 36; i++) {
        if (i == 8 || i == 13 || i == 18 || i == 23) { if (id[i] != '-') return false; }
        else if (!strchr("0123456789abcdef", id[i])) return false;
    }
    return true;
}
static int slot(int root, const char *name) {
    int fd = openat(root, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) syserr("cannot open checkpoint directory");
    struct stat value = info(fd);
    check_node(fd, value, info(root).st_dev, true);
    return fd;
}
static size_t serialize(struct record value, char buffer[600]) {
    int length = snprintf(buffer, 600, "MCD_CHECKPOINT 1\nbinding %s\ndesktop %s\ncode %s\ndesktop-source %s\ncode-source %s\n",
        value.binding, value.desktop.content, value.code.content, value.desktop.witness, value.code.witness);
    if (length <= 0 || length >= 600) fail("manifest serialization failed");
    return (size_t)length;
}
static void write_record(int stage, struct record record) {
    char buffer[600]; size_t length = serialize(record, buffer);
    int fd = openat(stage, "manifest.txt", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) syserr("cannot create manifest exclusively");
    write_all(fd, buffer, length); sync_fd(fd);
    if (close(fd)) syserr("cannot close manifest");
}
static void consume(const char **cursor, const char *end, const char *literal) {
    size_t length = strlen(literal);
    if ((size_t)(end - *cursor) < length || memcmp(*cursor, literal, length)) fail("noncanonical or partial manifest");
    *cursor += length;
}
static void read_hash(const char **cursor, const char *end, const char *label, char value[65]) {
    consume(cursor, end, label);
    if (end - *cursor < 65) fail("partial manifest digest");
    memcpy(value, *cursor, 64); value[64] = '\0'; *cursor += 64;
    if (!hex_hash(value)) fail("invalid manifest digest");
    consume(cursor, end, "\n");
}
static struct record read_record(int stage) {
    int fd = openat(stage, "manifest.txt", O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) syserr("cannot open manifest");
    struct stat before = info(fd);
    check_node(fd, before, info(stage).st_dev, true);
    if (!S_ISREG(before.st_mode) || (before.st_mode & 0777) != 0600 || before.st_size <= 0 || before.st_size >= 600)
        fail("invalid manifest type, size or permissions");
    char buffer[600]; size_t total = 0;
    while (total < sizeof(buffer)) {
        ssize_t count = read(fd, buffer + total, sizeof(buffer) - total);
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) syserr("cannot read manifest");
        if (!count) break;
        total += (size_t)count;
    }
    if (total != (size_t)before.st_size || !same(before, info(fd))) fail("manifest changed while reading");
    close(fd);
    const char *cursor = buffer, *end = buffer + total;
    struct record record;
    consume(&cursor, end, "MCD_CHECKPOINT 1\n");
    read_hash(&cursor, end, "binding ", record.binding);
    read_hash(&cursor, end, "desktop ", record.desktop.content);
    read_hash(&cursor, end, "code ", record.code.content);
    read_hash(&cursor, end, "desktop-source ", record.desktop.witness);
    read_hash(&cursor, end, "code-source ", record.code.witness);
    if (cursor != end) fail("extra manifest bytes");
    return record;
}
static void verify(int stage, struct record record, const char *binding) {
    if (strcmp(record.binding, binding)) fail("checkpoint belongs to a different profile pair or app build");
    size_t count; char **names = names_in(stage, &count);
    if (count != 3 || strcmp(names[0], "code") || strcmp(names[1], "desktop") || strcmp(names[2], "manifest.txt"))
        fail("unexpected checkpoint root entries");
    for (size_t i = 0; i < count; i++) free(names[i]);
    free(names);
    int desktop = slot(stage, "desktop"), code = slot(stage, "code");
    struct hashes d = tree(desktop, -1, true), c = tree(code, -1, true);
    if (strcmp(d.content, record.desktop.content) || strcmp(c.content, record.code.content)) fail("checkpoint content digest mismatch");
    close(desktop); close(code);
}
int main(int argc, char **argv) {
    if (getuid() == 0 || getuid() != geteuid()) fail("requires an unprivileged user");
    umask(077);
    bool prepare = argc == 7 && !strcmp(argv[1], "prepare");
    bool commit = argc == 7 && !strcmp(argv[1], "commit");
    bool inspect = argc == 5 && !strcmp(argv[1], "verify");
    if ((!prepare && !commit && !inspect) || !uuid(argv[3]) || !hex_hash(argv[4])) fail("invalid operation, checkpoint UUID or binding");
    int root = open_directory(argv[2], true);
    char pending[46]; snprintf(pending, sizeof(pending), ".pending-%s", argv[3]);
    if (prepare && mkdirat(root, pending, 0700)) syserr("pending checkpoint already exists or cannot be created");
    int stage = slot(root, inspect ? argv[3] : pending);
    if (inspect) {
        verify(stage, read_record(stage), argv[4]);
        check_path(root, argv[2]);
        printf("VERIFIED %s (content/binding only; no restore compatibility established)\n", argv[3]);
        return 0;
    }
    if (overlaps(argv[2], argv[5]) || overlaps(argv[2], argv[6]) || overlaps(argv[5], argv[6])) fail("checkpoint and source directories overlap");
    int desktop = open_directory(argv[5], false), code = open_directory(argv[6], false);
    struct stat ds = info(desktop), cs = info(code);
    if (ds.st_dev == cs.st_dev && ds.st_ino == cs.st_ino) fail("source directories alias");
    struct record record;
    if (prepare) {
        memcpy(record.binding, argv[4], 65);
        record.desktop = tree(desktop, -1, false); record.code = tree(code, -1, false);
        hook("sources-recorded");
        if (mkdirat(stage, "desktop", 0700) || mkdirat(stage, "code", 0700)) syserr("cannot create checkpoint pair");
        int d = slot(stage, "desktop"), c = slot(stage, "code");
        struct hashes copied_d = tree(desktop, d, false), copied_c = tree(code, c, false);
        sync_fd(d); sync_fd(c); close(d); close(c);
        if (!equal(record.desktop, copied_d) || !equal(record.code, copied_c)) fail("source changed before or during copy");
        if (!equal(record.desktop, tree(desktop, -1, false)) || !equal(record.code, tree(code, -1, false))) fail("source changed after copy");
        check_path(desktop, argv[5]); check_path(code, argv[6]);
        write_record(stage, record); verify(stage, record, argv[4]);
        sync_fd(stage); sync_fd(root); hook("prepared");
        printf("PREPARED %s (not published)\n", argv[3]);
        return 0;
    }
    record = read_record(stage);
    verify(stage, record, argv[4]);
    if (!equal(record.desktop, tree(desktop, -1, false)) || !equal(record.code, tree(code, -1, false))) fail("source changed since preparation");
    check_path(desktop, argv[5]); check_path(code, argv[6]);
    check_path(root, argv[2]);
    hook("before-publish");
#ifdef MCD_CHECKPOINT_TESTING
    if (getenv("MCD_CHECKPOINT_RENAME_UNSUPPORTED")) { errno = ENOTSUP; syserr("exclusive publication unsupported; no fallback"); }
#endif
    if (renameatx_np(root, pending, root, argv[3], RENAME_EXCL | RENAME_NOFOLLOW_ANY)) syserr("exclusive checkpoint publication failed; no fallback");
    sync_fd(root); hook("published");
    printf("COMMITTED %s (content checkpoint only; no automatic restore)\n", argv[3]);
    return 0;
}
