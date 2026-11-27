#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

/* Dedicated readiness endpoint, not the OmniCore RPC protocol. */
static const char ready[] = "OMNICORE-HEALTH/1 READY\n";
static volatile sig_atomic_t stopping;

static void stop_service(int signo) {
    (void)signo;
    stopping = 1;
}

/* Strict decimal parsing: no sign, whitespace, leading zeros, or overflow. */
static int decimal(const char *text, unsigned int max, unsigned int *value) {
    if (!text || !*text || (*text == '0' && text[1])) return 0;
    unsigned int n = 0;
    for (; *text; ++text) {
        if (*text < '0' || *text > '9') return 0;
        unsigned int d = (unsigned int)(*text - '0');
        if (d > max || n > (max - d) / 10U) return 0;
        n = n * 10U + d;
    }
    *value = n;
    return 1;
}

/* Init owns creation, bind, mode and label. Never bind or unlink here. */
static int adopt(const char *path) {
    unsigned int fd;
    const char *env = getenv("ANDROID_SOCKET_omnicore_health");
    if (!decimal(env, INT_MAX, &fd) || fd < 3U || !path || path[0] != '/') return -1;
    struct sockaddr_un name = {0};
    size_t n = strlen(path);
    if (n >= sizeof(name.sun_path)) return -1;
    socklen_t len = sizeof(name);
    if (getsockname((int)fd, (struct sockaddr *)&name, &len) != 0 ||
        name.sun_family != AF_UNIX || len != offsetof(struct sockaddr_un, sun_path) + n + 1U ||
        memcmp(name.sun_path, path, n + 1U) != 0) return -1;
    int kind = 0, listening = 0;
    len = sizeof(kind);
    if (getsockopt((int)fd, SOL_SOCKET, SO_TYPE, &kind, &len) != 0 ||
        len != sizeof(kind) || kind != SOCK_STREAM) return -1;
    len = sizeof(listening);
    if (getsockopt((int)fd, SOL_SOCKET, SO_ACCEPTCONN, &listening, &len) != 0 ||
        len != sizeof(listening) || listening) return -1;
    len = sizeof(name);
    if (getpeername((int)fd, (struct sockaddr *)&name, &len) == 0 || errno != ENOTCONN) return -1;
    int flags = fcntl((int)fd, F_GETFL);
    if (flags < 0 || fcntl((int)fd, F_SETFL, flags | O_NONBLOCK) != 0 ||
        fcntl((int)fd, F_SETFD, FD_CLOEXEC) != 0) return -1;
    if (listen((int)fd, 4) != 0) return -1;
    return (int)fd;
}

static int trusted(int fd, uid_t uid, const char *label) {
    struct ucred peer;
    socklen_t len = sizeof(peer);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &len) != 0 ||
        len != sizeof(peer) || peer.pid <= 0 || peer.uid != uid) return 0;
    char security[1024];
    len = sizeof(security);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERSEC, security, &len) != 0 ||
        len > sizeof(security)) return 0;
    while (len && security[len - 1U] == '\0') --len;
    return len == strlen(label) && memcmp(security, label, len) == 0;
}

static int serve(int fd, uid_t uid, const char *label) {
    while (!stopping) {
        struct pollfd p = { .fd = fd, .events = POLLIN };
        int n = poll(&p, 1, 250);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 || (n > 0 && (p.revents & (POLLERR | POLLHUP | POLLNVAL)))) return 1;
        if (n == 0 || !(p.revents & POLLIN)) continue;
        int conn = accept4(fd, NULL, NULL, SOCK_CLOEXEC | SOCK_NONBLOCK);
        if (conn < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK || errno == ECONNABORTED) continue;
            return 1;
        }
        if (trusted(conn, uid, label)) {
            /* Fixed tiny response; no blocking retries and no request payload. */
            (void)send(conn, ready, sizeof(ready) - 1U, MSG_NOSIGNAL);
        }
        close(conn);
    }
    return 0;
}

int main(int argc, char **argv) {
    const char *path = "/dev/socket/omnicore_health";
    const char *label = "u:r:system_server:s0";
    unsigned int uid = 1000U;
#ifdef OMNI_HOST_TEST
    if (argc != 4 || !decimal(argv[2], UINT_MAX, &uid)) return 2;
    path = argv[1];
    label = argv[3];
    if (!*label || strlen(label) > 256U) return 2;
#else
    (void)argv;
    if (argc != 1 || getuid() != 9999U || geteuid() != 9999U) return 2;
#endif
    struct sigaction action = {0};
    action.sa_handler = stop_service;
    if (sigemptyset(&action.sa_mask) != 0 || sigaction(SIGTERM, &action, NULL) != 0 ||
        sigaction(SIGINT, &action, NULL) != 0) return 2;
    int fd = adopt(path);
    if (fd < 0) return 2;
#ifdef OMNI_HOST_TEST
    puts("LISTENING");
    fflush(stdout);
#endif
    int result = serve(fd, (uid_t)uid, label);
    close(fd);
    return result;
}
