"""F1 emulator acceptance gate for an already running OmniCore AOSP 8.1 image."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time

HOME = 'org.omnicore.home/.HomeActivity'
INTENT = ('-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.HOME')


class GateError(RuntimeError):
    pass


def verify_emulator(serial: str, *, timeout: int = 180, run=subprocess.run) -> dict:
    if not re.fullmatch(r'emulator-[0-9]{4,5}', serial):
        raise GateError('explicit_emulator_serial_required')
    if not 1 <= timeout <= 1800:
        raise GateError('invalid_timeout')
    deadline = time.monotonic() + timeout

    def adb(*args: str) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GateError('deadline_exceeded')
        try:
            result = run(['adb', '-s', serial, *args], capture_output=True,
                         text=True, timeout=min(remaining, 30), check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GateError('adb_unavailable_or_timeout:' + args[0]) from exc
        if result.returncode != 0:
            raise GateError('adb_failed:' + args[0])
        return result.stdout.strip()

    def prop(name: str) -> str:
        return adb('shell', 'getprop', name)

    if adb('get-state') != 'device' or prop('ro.kernel.qemu') != '1':
        raise GateError('not_an_online_emulator')
    while prop('sys.boot_completed') != '1':
        time.sleep(max(0, min(1, deadline - time.monotonic())))
    for key, value in (('ro.build.version.sdk', '27'),
                       ('ro.build.version.release', '8.1.0'),
                       ('ro.omnicore.profile', 'EMULATOR')):
        if prop(key) != value:
            raise GateError('property_mismatch:' + key)
    paths = adb('shell', 'pm', 'path', 'org.omnicore.home').splitlines()
    if paths != ['package:/system/app/OmniCoreHome/OmniCoreHome.apk']:
        raise GateError('home_not_system_package')
    homes = adb('shell', 'cmd', 'package', 'query-activities', '--components',
                '--user', '0', *INTENT).splitlines()
    if HOME not in [line.strip() for line in homes]:
        raise GateError('home_not_registered')
    launch = adb('shell', 'am', 'start', '-W', '--user', '0', *INTENT, '-n', HOME)
    lines = launch.splitlines()
    if ('Status: ok' not in lines or 'Activity: ' + HOME not in lines
            or any(line.startswith('Error') for line in lines)):
        raise GateError('home_launch_failed')
    activities = adb('shell', 'dumpsys', 'activity', 'activities')
    if not re.search(r'^\s*mResumedActivity: ActivityRecord\{[^\n]*\bu0 '
                     + re.escape(HOME) + r'\s', activities, re.MULTILINE):
        raise GateError('home_not_resumed')
    return {'gate': 'F1_EMULATOR_HOME', 'result': 'PASS', 'serial': serial,
            'android_api': 27, 'profile': 'EMULATOR', 'activity': HOME,
            'hardware_status': 'NOT_TESTED', 'default_home_status': 'NOT_TESTED'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    try:
        result = verify_emulator(args.serial, timeout=args.timeout)
    except GateError as exc:
        print(json.dumps({'gate': 'F1_EMULATOR_HOME', 'result': 'BLOCKED',
                          'reason': str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
