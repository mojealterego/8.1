LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)
LOCAL_MODULE_TAGS := optional
LOCAL_PACKAGE_NAME := OmniCoreHome
LOCAL_SDK_VERSION := 27
LOCAL_SRC_FILES := $(call all-java-files-under, src)
LOCAL_RESOURCE_DIR := $(LOCAL_PATH)/res
# Intentional: do NOT override Launcher3 or FallbackHome before emulator acceptance.
include $(BUILD_PACKAGE)