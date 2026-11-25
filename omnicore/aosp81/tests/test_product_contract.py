"""Static source checks; NOT a substitute for AOSP compilation or UI instrumentation."""
from pathlib import Path
from xml.etree import ElementTree as ET
import unittest

PRODUCT = Path(__file__).resolve().parent.parent/'product'
APP = PRODUCT/'packages/apps/OmniCoreHome'
DEVICE = PRODUCT/'device/omnicore/generic'


class NanoHomeSourceTests(unittest.TestCase):
    def test_manifest_has_explicit_home_activity_and_no_privileged_permissions(self):
        root = ET.parse(APP/'AndroidManifest.xml').getroot()
        android = '{http://schemas.android.com/apk/res/android}'
        self.assertEqual(root.get('package'), 'org.omnicore.home')
        self.assertEqual(root.findall('uses-permission'), [])
        app = root.find('application')
        self.assertEqual(app.get(android+'allowBackup'), 'false')
        activity = app.find('activity')
        self.assertEqual(activity.get(android+'exported'), 'true')
        intent = activity.find('intent-filter')
        categories = {e.get(android+'name') for e in intent.findall('category')}
        self.assertIn('android.intent.category.HOME', categories)
        self.assertIn('android.intent.category.DEFAULT', categories)

    def test_home_does_not_replace_stock_launcher_or_privilege_itself(self):
        mk = (APP/'Android.mk').read_text()
        # Drop comments before parsing for feature flags.
        active = '\n'.join(l for l in mk.splitlines() if not l.lstrip().startswith('#'))
        self.assertNotIn('LOCAL_OVERRIDES_PACKAGES', active)
        self.assertNotIn('LOCAL_PRIVILEGED_MODULE', active)
        self.assertIn('LOCAL_SDK_VERSION := 27', active)

    def test_product_includes_home_preserving_generic_base(self):
        product = (DEVICE/'omnicore_emulator_x86_64.mk').read_text()
        self.assertIn('$(SRC_TARGET_DIR)/product/aosp_x86_64.mk', product)
        self.assertIn('PRODUCT_PACKAGES += OmniCoreHome', product)
        self.assertIn('omnicore_emulator_x86_64.mk', (DEVICE/'AndroidProducts.mk').read_text())

    def test_no_network_ipc_or_periodic_render_loop(self):
        java = (APP/'src/org/omnicore/home/HomeActivity.java').read_text()
        self.assertNotIn('INTERNET', java)
        self.assertNotIn('HttpURLConnection', java)
        self.assertNotIn('while (true)', java)
        self.assertNotIn('Thread.sleep', java)
        self.assertIn('ACTION_OPEN_DOCUMENT', java)

if __name__ == '__main__':
    unittest.main()
