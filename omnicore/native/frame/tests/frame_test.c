#include "frame.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    unsigned char b[4]; unsigned int n;
    for (unsigned int i = 1; i <= OCR_MAX_FRAME; ++i) {
        assert(ocr_frame_encode(i, b) == OCR_OK);
        assert(b[0] == (unsigned char)(i >> 24));
        assert(b[1] == (unsigned char)(i >> 16));
        assert(b[2] == (unsigned char)(i >> 8));
        assert(b[3] == (unsigned char)i);
        assert(ocr_frame_decode(b, &n) == OCR_OK && n == i);
    }
    memset(b, 0xAA, 4);
    assert(ocr_frame_encode(0, b) == OCR_INVALID_LENGTH && b[0] == 0xAA);
    assert(ocr_frame_encode(65537, b) == OCR_INVALID_LENGTH && b[3] == 0xAA);
    assert(ocr_frame_encode(1, 0) == OCR_NULL);
    const unsigned char zero[4] = {0, 0, 0, 0};
    const unsigned char huge[4] = {255, 255, 255, 255};
    n = 42;
    assert(ocr_frame_decode(zero, &n) == OCR_INVALID_LENGTH && n == 42);
    assert(ocr_frame_decode(huge, &n) == OCR_INVALID_LENGTH && n == 42);
    assert(ocr_frame_decode(0, &n) == OCR_NULL);
    assert(ocr_frame_decode(zero, 0) == OCR_NULL);
    puts("PASS: 65536 exhaustive round trips, 7 negative checks");
    return 0;
}
