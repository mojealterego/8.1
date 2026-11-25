"""Pinned framework source policy: never claim that one fork is a complete AOSP ROM."""
import pytest
from omnicore_host.source_gate import verify_local_manifest, SourceGateError


def manifest(remote='https://github.com/', revision='4a9acdc305c27336f8ef74505800bcc541f6052e'):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<manifest><remote name="omnicore-gh" fetch="{remote}" />
<remove-project name="platform/frameworks/base" />
<project path="frameworks/base" name="mojealterego/8.1" remote="omnicore-gh" revision="{revision}" /></manifest>'''


def test_valid_pinned_manifest():
    result = verify_local_manifest(manifest())
    assert result['framework_path'] == 'frameworks/base'
    assert result['revision'] == '4a9acdc305c27336f8ef74505800bcc541f6052e'
    assert result['source_kind'] == 'frameworks_base_only'


def test_reject_unpinned_branch():
    with pytest.raises(SourceGateError, match='incorrect_framework_revision'):
        verify_local_manifest(manifest(revision='main'))


def test_reject_insecure_remote():
    with pytest.raises(SourceGateError, match='untrusted_remote'):
        verify_local_manifest(manifest(remote='http://github.com/'))


def test_reject_missing_remove_project():
    with pytest.raises(SourceGateError, match='missing_upstream_removal'):
        verify_local_manifest(manifest().replace('<remove-project name="platform/frameworks/base" />',''))


def test_reject_extra_project_as_not_reviewed():
    with pytest.raises(SourceGateError, match='unexpected_project'):
        verify_local_manifest(manifest().replace('</manifest>', '<project path="vendor/evil" name="other" /></manifest>'))