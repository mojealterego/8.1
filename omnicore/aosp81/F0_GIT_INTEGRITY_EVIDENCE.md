# F0 source integrity hardening — evidence

Base: 5993979a0973e769f1d9ec4bc7fd2f84dc7c8e79. Mode: NATIVE (real Git repositories in temporary directories), Python 3.13.5, Git 2.47.3, Linux.
Command from omnicore/aosp81: python3 -m unittest discover -s tests -p test_git_checkout.py -v
RED: ModuleNotFoundError: No module named 'git_checkout' (new module absent).
GREEN: 9 tests, 0 failures/errors, 0.231s. py_compile passed for module and tests.
Source SHA256: 534ba6606c2ef19af93bc6d8204c82d2d2c101d14ff4f2ba5f193639026d09b0
Test SHA256: 30e00e227bbb218729a0d23c6d1823765db9322c7265f7dd61cf7cd8937e6fa0
Test IDs: GitCheckoutTests.test_assume_unchanged_rejected, test_clean_checkout, test_deleted_tracked_file, test_git_dir_environment_ignored, test_modified_tracked_file, test_parent_repository_is_not_a_project, test_skip_worktree_rejected, test_staged_file, test_untracked_overlay_allowed.
Integration: preflight._git_head delegates to checked_head, preserving existing GateError interface. This wrapper and earlier suites were not executed in this session; complete checkout is absent.
Scope: checks repository root, tracked status, hidden index flags, inherited Git environment, stable HEAD at two observations. Allows untracked files deliberately (nested AOSP projects and existing overlay). Does not attest untracked files, malicious local Git configuration, concurrent worktree changes or upstream manifest completeness; isolated trusted build host is required.
F1 native build and emulator remain BLOCKED. No Rust/Zenoh integration or hardware deployment performed.
