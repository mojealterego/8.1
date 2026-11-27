#ifndef OCR_UNIX_FFI_H
#define OCR_UNIX_FFI_H
#include <stddef.h>
#include <stdint.h>

/* Stable ABI for Rust: fixed-width UID and timeout, int result, size_t lengths.
 * Pointers must obey unix_client.h's non-aliasing and storage contract.
 * Valid bounded response storage is cleared on every error. */
int ocr_unix_exchange_ffi(const char *path, uint32_t uid, const char *label,
    uint32_t timeout_ms, const unsigned char *request, size_t request_len,
    unsigned char *response, size_t capacity, size_t *response_len);
#endif
