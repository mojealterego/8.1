"""Image verifier tests use artificial fixtures; they are not Android builds."""
from pathlib import Path
import struct
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verify_generic_build import ImageGateError, inspect_product_image


class ImageGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name)
        (self.out/'system').mkdir()
        (self.out/'system/build.prop').write_text('ro.build.version.release=8.1.0\nro.build.version.sdk=27\n')
        (self.out/'system.img').write_bytes(struct.pack('<I',0xED26FF3A)+b'\x00'*(1024*1024))

    def test_android_sparse_image_structure_accepted_as_sanity_only(self):
        result=inspect_product_image(self.out)
        self.assertEqual(result['result'],'SANITY_PASS')
        self.assertEqual(result['emulator_status'],'NOT_TESTED')
        self.assertEqual(len(result['sha256']),64)

    def test_missing_image_blocked(self):
        (self.out/'system.img').unlink()
        with self.assertRaisesRegex(ImageGateError,'missing_image'):
            inspect_product_image(self.out)

    def test_short_image_blocked(self):
        (self.out/'system.img').write_bytes(b'abc')
        with self.assertRaisesRegex(ImageGateError,'image_too_small'):
            inspect_product_image(self.out)

    def test_unknown_image_format_blocked(self):
        (self.out/'system.img').write_bytes(b'x'*(1024*1024+10))
        with self.assertRaisesRegex(ImageGateError,'invalid_image_format'):
            inspect_product_image(self.out)

    def test_wrong_android_api_blocked(self):
        (self.out/'system/build.prop').write_text('ro.build.version.release=8.1.0\nro.build.version.sdk=28\n')
        with self.assertRaisesRegex(ImageGateError,'incorrect_android_version'):
            inspect_product_image(self.out)

if __name__=='__main__':
    unittest.main()