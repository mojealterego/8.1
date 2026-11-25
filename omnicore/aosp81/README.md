# OmniCore Revolution System Ω — AOSP 8.1 / F0

This folder is the source preflight for Android 8.1 (API 27), not a complete Android ROM.

Source of the owner framework fork: https://github.com/mojealterego/8.1

Pinned framework commit: 4a9acdc305c27336f8ef74505800bcc541f6052e

## Proven scope

The fork contains AOSP frameworks/base only. It does NOT contain the complete Android 8.1 AOSP multi-repo tree, MediaTek MT6580 BSP, a verified system image, signed firmware or verified physical recovery.

A local manifest snippet is included in omnicore.xml. A full AOSP tree must be assembled with the upstream android-8.1.0_r1 manifest and compatible build toolchain before attempting a baseline build. The snippet itself does not produce a bootable ROM.

## Reproducible preflight

Run Python 3 offline:

    python3 omnicore/aosp81/preflight.py --manifest omnicore/aosp81/omnicore.xml
    python3 -m unittest discover -s omnicore/aosp81/tests -v

After obtaining a complete upstream AOSP checkout, place the manifest file under the checkout's .repo/local_manifests/ directory, synchronize it using repo, and check the result:

    python3 omnicore/aosp81/preflight.py --manifest omnicore/aosp81/omnicore.xml --aosp /path/to/aosp

F0 check verifies exact SHA, required project directories and SystemUI/Android.mk. It does not assert reproducible build or emulator success.

## Blockers and safety

- F1: Full AOSP sync/build and emulator boot have not been executed.
- F2: Rust/SELinux/Binder/Zenoh integration not compiled or validated on Android 8.1.
- F6: myPhone FUN 6 Lite BSP, partition map and tested stock recovery missing.
- No flashing, bootloader unlock, or vendor partition modification is authorized by this preflight.
- Android 8.1 legacy is unsuitable for banking or sensitive secrets; Zero Trust host code cannot patch obsolete firmware by itself.
