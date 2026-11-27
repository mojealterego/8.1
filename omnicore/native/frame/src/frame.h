#ifndef OCR_FRAME_H
#define OCR_FRAME_H
#define OCR_MAX_FRAME 65536U
#define OCR_OK 0
#define OCR_NULL 1
#define OCR_INVALID_LENGTH 2
/* Caller must supply 4 accessible header bytes and a valid length output. */
int ocr_frame_encode(unsigned int length, unsigned char *header);
int ocr_frame_decode(const unsigned char *header, unsigned int *length);
#endif
