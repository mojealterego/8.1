"""Native C/Python host wire contract test; no Android or Zenoh emulation."""
import ctypes
import struct
import sys

lib = ctypes.CDLL(sys.argv[1])
Header = ctypes.c_ubyte * 4
lib.ocr_frame_encode.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_ubyte)]
lib.ocr_frame_encode.restype = ctypes.c_int
lib.ocr_frame_decode.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(ctypes.c_uint)]
lib.ocr_frame_decode.restype = ctypes.c_int
for n in range(1, 65537):
    header = Header()
    assert lib.ocr_frame_encode(n, header) == 0
    assert bytes(header) == struct.pack('!I', n)
    decoded = ctypes.c_uint()
    assert lib.ocr_frame_decode(Header.from_buffer_copy(struct.pack('!I', n)), ctypes.byref(decoded)) == 0
    assert decoded.value == n
print('PASS: 65536 C/Python bidirectional wire lengths')
