#include "unix_ffi.h"
#include "unix_client.h"
#include "frame.h"
#include <string.h>

_Static_assert(sizeof(uid_t) == sizeof(uint32_t) && (uid_t)-1 > 0,
               "unsupported uid_t ABI");
_Static_assert(sizeof(unsigned int) == sizeof(uint32_t), "unsupported timeout ABI");

int ocr_unix_exchange_ffi(const char *path, uint32_t uid, const char *label,
    uint32_t timeout_ms, const unsigned char *request, size_t request_len,
    unsigned char *response, size_t capacity, size_t *response_len) {
    int result = (int)ocr_unix_exchange(path, (uid_t)uid, label,
        (unsigned int)timeout_ms, request, request_len, response, capacity, response_len);
    if (result != OCR_UNIX_OK && response && capacity && capacity <= OCR_MAX_FRAME)
        memset(response, 0, capacity);
    return result;
}
