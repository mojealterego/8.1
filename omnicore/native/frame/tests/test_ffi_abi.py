"""Native fixed-width C ABI contract, using actual AF_UNIX sockets."""
import ctypes as C
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]

class AbiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        so = Path(tmp.name) / 'ffi.so'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        *[str(ROOT/'src'/p) for p in ('frame.c','unix_client.c','unix_ffi.c')],
                        '-o', str(so)], check=True)
        cls.lib = C.CDLL(str(so))
        cls.call_ffi = cls.lib.ocr_unix_exchange_ffi
        cls.call_ffi.argtypes = [C.c_char_p,C.c_uint32,C.c_char_p,C.c_uint32,C.c_void_p,C.c_size_t,
                                 C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
        cls.call_ffi.restype = C.c_int

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.fsencode(Path(tmp.name)/'rpc.sock')
        a,b = socket.socketpair()
        with a,b:
            self.label = a.getsockopt(socket.SOL_SOCKET,31,1024).rstrip(b'\0')

    def exchange(self, response=b'\0\0\0\3xyz', *, uid=None, label=None, cap=16, request=b'{}'):
        out = (C.c_ubyte * cap)(*([0xA5]*cap))
        n = C.c_size_t(123)
        errors=[]
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
            listener.bind(self.path)
            listener.listen(1)
            listener.settimeout(2)
            def server():
                try:
                    conn,_ = listener.accept()
                    with conn:
                        conn.settimeout(2)
                        got=b''
                        while len(got)<4+len(request):
                            part=conn.recv(4+len(request)-len(got))
                            if not part: break
                            got+=part
                        if got:
                            assert got == struct.pack('!I',len(request))+request
                            conn.sendall(response)
                        elif uid is None and label is None:
                            raise AssertionError('no request received')
                except Exception as exc:
                    errors.append(exc)
            thread=threading.Thread(target=server)
            thread.start()
            try:
                code=self.call_ffi(self.path,os.getuid() if uid is None else uid,
                                   self.label if label is None else label,1000,
                                   request,len(request),out,cap,C.byref(n))
            finally:
                thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors,[])
        return code,n.value,bytes(out)

    def test_success(self):
        code,n,out=self.exchange()
        self.assertEqual((code,n,out[:n]),(0,3,b'xyz'))

    def test_untrusted_uid(self):
        self.assertEqual(self.exchange(uid=(os.getuid()+1)%2**32)[:2],(4,0))

    def test_untrusted_label(self):
        self.assertEqual(self.exchange(label=b'not-trusted')[:2],(4,0))

    def test_invalid_response(self):
        self.assertEqual(self.exchange(b'\0'*4)[:2],(5,0))

    def test_capacity(self):
        self.assertEqual(self.exchange(cap=2)[:2],(6,0))

    def test_partial_response_erased(self):
        code,n,out=self.exchange(b'\0\0\0\5xy')
        self.assertEqual((code,n,out),(2,0,b'\0'*16))

    def test_invalid_arguments(self):
        out=(C.c_ubyte*8)(*([0xA5]*8));n=C.c_size_t(99)
        code=self.call_ffi(b'relative',0,b'kernel',100,b'{}',2,out,8,C.byref(n))
        self.assertEqual((code,n.value,bytes(out)),(1,0,b'\0'*8))

    def test_absent_socket(self):
        out=(C.c_ubyte*8)(*([0xA5]*8));n=C.c_size_t(99)
        code=self.call_ffi(self.path,os.getuid(),self.label,100,b'{}',2,out,8,C.byref(n))
        self.assertEqual((code,n.value,bytes(out)),(2,0,b'\0'*8))

if __name__=='__main__': unittest.main()
