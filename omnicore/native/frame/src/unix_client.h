#ifndef OCR_UNIX_CLIENT_H
#define OCR_UNIX_CLIENT_H
#include <stddef.h>
#include <sys/types.h>

enum ocr_unix_result {
    OCR_UNIX_OK = 0, OCR_UNIX_ARGUMENT = 1, OCR_UNIX_IO = 2,
    OCR_UNIX_TIMEOUT = 3, OCR_UNIX_PEER = 4, OCR_UNIX_PROTOCOL = 5,
    OCR_UNIX_CAPACITY = 6
};
/* One request per connection; no retry. All pointers must refer to valid,
 * non-overlapping storage. The caller trusts the configured path, UID and
 * exact kernel security label, not values supplied by a remote request.
 * On error *response_len is zero and response contents must be discarded.
 * A transport error after sending does not imply the request was not executed. */
enum ocr_unix_result ocr_unix_exchange(
    const char *path, uid_t expected_uid, const char *expected_label,
    unsigned int timeout_ms, const unsigned char *request, size_t request_len,
    unsigned char *response, size_t capacity, size_t *response_len);
#endif
