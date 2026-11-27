#include "unix_client.h"
#include "frame.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    if (argc != 6) return 2;
    unsigned char request[OCR_MAX_FRAME + 1], response[OCR_MAX_FRAME];
    size_t n = fread(request, 1, sizeof(request), stdin), received = 99;
    if (ferror(stdin)) return 2;
    size_t capacity = strtoul(argv[5], NULL, 10);
    if (capacity > sizeof(response)) return 2;
    enum ocr_unix_result result = ocr_unix_exchange(
        argv[1], (uid_t)strtoul(argv[2], NULL, 10), argv[3],
        (unsigned int)strtoul(argv[4], NULL, 10), request, n,
        response, capacity, &received);
    printf("%d %zu\n", result, received);
    if (result == OCR_UNIX_OK && fwrite(response, 1, received, stdout) != received) return 2;
    return 0;
}
