# Exploratory AOSP 8.1 x86_64 emulator product; no MT6580 hardware claims.
$(call inherit-product, $(SRC_TARGET_DIR)/product/aosp_x86_64.mk)

PRODUCT_NAME := omnicore_emulator_x86_64
PRODUCT_BRAND := OmniCore
PRODUCT_MODEL := OmniCore Revolution System Omega Emulator
PRODUCT_MANUFACTURER := OmniCore

# Do not remove Launcher3, SystemUI, FallbackHome, PackageInstaller or telephony.
PRODUCT_PACKAGES += OmniCoreHome
PRODUCT_PROPERTY_OVERRIDES += ro.omnicore.profile=EMULATOR