LOCAL_PATH := $(call my-dir)
include $(CLEAR_VARS)
LOCAL_MODULE := omnicore_healthd
LOCAL_SRC_FILES := healthd.c
LOCAL_CFLAGS := -std=c11 -Wall -Wextra -Werror
LOCAL_INIT_RC := omnicore_healthd.rc
LOCAL_MODULE_TAGS := optional
include $(BUILD_EXECUTABLE)
