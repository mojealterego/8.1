"""Offline validation of the owner's AOSP 8.1 local manifest fragment.

A local manifest is NOT the complete upstream AOSP manifest; full source tree
and build require `repo sync` + independent pin of all upstream projects.
"""
from __future__ import annotations
from hashlib import sha256
import re
from xml.etree import ElementTree as ET

OWNER_SHA = '4a9acdc305c27336f8ef74505800bcc541f6052e'
OWNER_REMOTE = 'https://github.com/'

class SourceGateError(ValueError):
    pass


def verify_local_manifest(xml_text: str) -> dict[str, str]:
    if not isinstance(xml_text, str) or not (20 < len(xml_text) <= 65536):
        raise SourceGateError('invalid_manifest')
    if '<!DOCTYPE' in xml_text.upper() or '<!ENTITY' in xml_text.upper():
        raise SourceGateError('prohibited_xml_entity')
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceGateError('invalid_xml') from exc
    if root.tag != 'manifest':
        raise SourceGateError('not_a_repo_manifest')
    children = list(root)
    if any(c.tag not in ('project','remote','remove-project') for c in children):
        raise SourceGateError('unexpected_manifest_element')
    remotes = [c for c in children if c.tag == 'remote']
    projects = [c for c in children if c.tag == 'project']
    removed = [c for c in children if c.tag == 'remove-project']
    if len(projects) != 1:
        raise SourceGateError('unexpected_project')
    if len(remotes) != 1 or remotes[0].attrib.get('fetch') != OWNER_REMOTE:
        raise SourceGateError('untrusted_remote')
    if len(removed) != 1 or removed[0].attrib.get('name') != 'platform/frameworks/base':
        raise SourceGateError('missing_upstream_removal')
    project = projects[0]
    if project.attrib.get('remote') != remotes[0].attrib.get('name'):
        raise SourceGateError('unexpected_remote_ref')
    if project.attrib.get('path') != 'frameworks/base' or project.attrib.get('name') != 'mojealterego/8.1':
        raise SourceGateError('wrong_framework_project')
    if project.attrib.get('revision') != OWNER_SHA:
        raise SourceGateError('incorrect_framework_revision')
    if not re.fullmatch(r'[0-9a-f]{40}', OWNER_SHA):
        raise SourceGateError('invalid_sha')
    return {'source_kind':'frameworks_base_only','framework_path':'frameworks/base',
            'revision':OWNER_SHA,'manifest_sha256':sha256(xml_text.encode('utf-8')).hexdigest()}