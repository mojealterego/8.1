# OmniCore Revolution System Ω — Android 8.1 source and emulator preparation (F0 → F1)

**Verified owner fork:** https://github.com/mojealterego/8.1 (`main`, original frameworks/base revision `4a9acdc305c27336f8ef74505800bcc541f6052e`). This fork is **NOT** the whole AOSP Android 8.1, kernel, or MT6580 BSP.

The `omnicore.xml` local manifest replaces the upstream `frameworks/base` project with the fixed owner SHA. It is not a full manifest. Use the official AOSP `android-8.1.0_r1` multi-repository manifest as the base, and place this file under `.repo/local_manifests/` on an isolated build host.

## Current deliverables

- `preflight.py`: F0 source pin verification against a **resolved, revision-locked** manifest (`repo manifest -r`), rejecting incomplete checkouts, unpinned SHAs, missing Git projects, symlink directory escapes, mismatched commits. `F0_MANIFEST_ONLY PASS` does **not** mean source checkout is available.
- `product/packages/apps/OmniCoreHome`: first **offline-only, non-privileged** Android API 27 HOME candidate. Uses a static Canvas view, Dialer, SAF files picker and Settings; deliberately does not remove Launcher3 or FallbackHome.
- `product/device/omnicore/generic`: exploratory x86_64 emulator product inheriting `aosp_x86_64.mk`, adding OmniCoreHome.
- `install_overlay.py`: non-destructive, idempotent installer with default dry-run, no overwrite, conflict checks and cleanup on failure; requires source gate first.
- `build_generic.sh`: actual host build orchestration; invokes installed AOSP make system, propagates failures through `pipefail` and checks output image. **It has not run against a real AOSP checkout in this environment.**
- `verify_generic_build.py`: offline image **sanity check**, not evidence of emulator boot or ROM production.

## Tests available immediately

```bash
python3 -m unittest discover -s omnicore/aosp81/tests -q
python3 omnicore/aosp81/preflight.py --manifest omnicore/aosp81/omnicore.xml
bash -n omnicore/aosp81/build_generic.sh
```

All paths above are relative to the root of the GitHub fork. The source-only preflight intentionally reports `F0_MANIFEST_ONLY`.

## Build procedure — requires separate full AOSP checkout

Run in an isolated, adequately provisioned Linux x86_64 environment with a working historic Android 8.1 toolchain. The build script itself does **not** download sources or modify a phone.

```bash
# On the AOSP build host, after obtaining the full android-8.1.0_r1 tree:
cp /path/to/fork/omnicore/aosp81/omnicore.xml /path/to/aosp/.repo/local_manifests/omnicore.xml
cd /path/to/aosp
repo sync -c -j4
repo manifest -r -o /path/to/aosp/manifest.lock.xml

# Check all projects and their exact pinned SHA; no shortcuts.
python3 /path/to/fork/omnicore/aosp81/preflight.py \
  --manifest /path/to/fork/omnicore/aosp81/omnicore.xml \
  --aosp /path/to/aosp --lock /path/to/aosp/manifest.lock.xml

# Stage-only preview, then optional explicit application.
python3 /path/to/fork/omnicore/aosp81/install_overlay.py \
  --aosp /path/to/aosp --lock /path/to/aosp/manifest.lock.xml

# Execute real build (copies the two overlay directories, no flashing).
/path/to/fork/omnicore/aosp81/build_generic.sh \
  /path/to/aosp /path/to/aosp/manifest.lock.xml
```

The product target is exploratory: `omnicore_emulator_x86_64-eng`. It must be validated by the actual AOSP 8.1 build. A green host test or successful `system.img` sanity scan is not a replacement for booting an emulator and verifying `getprop sys.boot_completed` and `getprop ro.build.version.sdk`.

## Release blocks

- **F1 BUILD-GENERIC:** not executed; build host/complete AOSP absent here.
- **F1 EMULATOR:** not executed; emulator boot and Home UI not verified.
- **Rust/Zenoh:** not integrated into this AOSP product; host-only code in separate engineering artifact.
- **F6 MT6580:** blocked until exact myPhone FUN 6 Lite BSP, safe backup and tested stock recovery. Never flash this generic image onto the physical phone.
- Android 8.1 remains obsolete and must not store banking data or valuable secrets.