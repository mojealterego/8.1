#include "frame.h"
_Static_assert(__CHAR_BIT__ == 8 && sizeof(unsigned int) == 4, "unsupported ABI");
int ocr_frame_encode(unsigned int length, unsigned char *header) {
    if (!header) return OCR_NULL;
    if (!length || length > OCR_MAX_FRAME) return OCR_INVALID_LENGTH;
    header[0] = (unsigned char)(length >> 24);
    header[1] = (unsigned char)(length >> 16);
    header[2] = (unsigned char)(length >> 8);
    header[3] = (unsigned char)length;
    return OCR_OK;
}
int ocr_frame_decode(const unsigned char *header, unsigned int *length) {
    if (!header || !length) return OCR_NULL;
    unsigned int n = ((unsigned int)header[0] << 24) |
                     ((unsigned int)header[1] << 16) |
                     ((unsigned int)header[2] << 8) | (unsigned int)header[3];
    if (!n || n > OCR_MAX_FRAME) return OCR_INVALID_LENGTH;
    *length = n;
    return OCR_OK;
}
