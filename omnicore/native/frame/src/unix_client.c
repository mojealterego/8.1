#define _GNU_SOURCE
#include "unix_client.h"
#include "frame.h"
#include <errno.h>
#include <poll.h>
#include <stdint.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

static int64_t now_ms(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return -1;
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static enum ocr_unix_result wait_ready(int fd, short events, int64_t deadline) {
    for (;;) {
        int64_t now = now_ms();
        if (now < 0) return OCR_UNIX_IO;
        if (now >= deadline) return OCR_UNIX_TIMEOUT;
        struct pollfd p = { .fd = fd, .events = events };
        int n = poll(&p, 1, (int)(deadline - now));
        if (n > 0) return (p.revents & POLLNVAL) ? OCR_UNIX_IO : OCR_UNIX_OK;
        if (n == 0) return OCR_UNIX_TIMEOUT;
        if (errno != EINTR) return OCR_UNIX_IO;
    }
}

static enum ocr_unix_result transfer(int fd, const unsigned char *src,
    unsigned char *dst, size_t count, int64_t deadline) {
    size_t done = 0;
    while (done < count) {
        enum ocr_unix_result r = wait_ready(fd, src ? POLLOUT : POLLIN, deadline);
        if (r != OCR_UNIX_OK) return r;
        ssize_t n = src ? send(fd, src + done, count - done, MSG_NOSIGNAL)
                        : recv(fd, dst + done, count - done, 0);
        if (n > 0) done += (size_t)n;
        else if (n == 0) return OCR_UNIX_IO;
        else if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) return OCR_UNIX_IO;
    }
    int64_t now = now_ms();
    if (now < 0) return OCR_UNIX_IO;
    return now >= deadline ? OCR_UNIX_TIMEOUT : OCR_UNIX_OK;
}

static int trusted_peer(int fd, uid_t uid, const char *label, size_t label_len) {
    struct ucred peer;
    socklen_t size = sizeof(peer);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &size) != 0 ||
        size != sizeof(peer) || peer.pid <= 0 || peer.uid != uid) return 0;
    char actual[1024];
    size = sizeof(actual);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERSEC, actual, &size) != 0 ||
        size > sizeof(actual)) return 0;
    while (size && actual[size - 1] == '\0') --size;
    return size == label_len && memcmp(actual, label, size) == 0;
}

enum ocr_unix_result ocr_unix_exchange(
    const char *path, uid_t expected_uid, const char *expected_label,
    unsigned int timeout_ms, const unsigned char *request, size_t request_len,
    unsigned char *response, size_t capacity, size_t *response_len) {
    if (!response_len) return OCR_UNIX_ARGUMENT;
    *response_len = 0;
    struct sockaddr_un addr = { .sun_family = AF_UNIX };
    if (!path || path[0] != '/' || !expected_label || !request || !response ||
        !request_len || request_len > OCR_MAX_FRAME || !capacity ||
        capacity > OCR_MAX_FRAME || !timeout_ms || timeout_ms > 5000) return OCR_UNIX_ARGUMENT;
    size_t path_len = strnlen(path, sizeof(addr.sun_path));
    size_t label_len = strnlen(expected_label, 257);
    if (path_len < 2 || path_len >= sizeof(addr.sun_path) || !label_len || label_len > 256)
        return OCR_UNIX_ARGUMENT;
    memcpy(addr.sun_path, path, path_len + 1);
    int64_t start = now_ms();
    if (start < 0) return OCR_UNIX_IO;
    int64_t deadline = start + timeout_ms;
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) return OCR_UNIX_IO;
    enum ocr_unix_result r = OCR_UNIX_IO;
    if (connect(fd, (struct sockaddr *)&addr,
                (socklen_t)(offsetof(struct sockaddr_un, sun_path) + path_len + 1)) != 0) {
        if (errno != EINPROGRESS) goto out;
        r = wait_ready(fd, POLLOUT, deadline);
        if (r != OCR_UNIX_OK) goto out;
        int error = 0;
        socklen_t len = sizeof(error);
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &len) != 0 || error) {
            r = OCR_UNIX_IO;
            goto out;
        }
    }
    if (!trusted_peer(fd, expected_uid, expected_label, label_len)) {
        r = OCR_UNIX_PEER;
        goto out;
    }
    unsigned char header[4];
    unsigned int length = 0;
    if (ocr_frame_encode((unsigned int)request_len, header) != OCR_OK) {
        r = OCR_UNIX_ARGUMENT;
        goto out;
    }
    r = transfer(fd, header, NULL, sizeof(header), deadline);
    if (r != OCR_UNIX_OK) goto out;
    r = transfer(fd, request, NULL, request_len, deadline);
    if (r != OCR_UNIX_OK) goto out;
    r = transfer(fd, NULL, header, sizeof(header), deadline);
    if (r != OCR_UNIX_OK) goto out;
    if (ocr_frame_decode(header, &length) != OCR_OK) {
        r = OCR_UNIX_PROTOCOL;
        goto out;
    }
    if (length > capacity) {
        r = OCR_UNIX_CAPACITY;
        goto out;
    }
    r = transfer(fd, NULL, response, length, deadline);
    if (r == OCR_UNIX_OK) *response_len = length;
out:
    close(fd);
    return r;
}
