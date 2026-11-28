"""Compile an exact-key ACL for a dedicated single-hop Zenoh 1.10.2 router.

Trusted deployment inputs only. CN ownership must be enforced by the issuing CA;
this compiler does not replace SignedIngress or provision certificates.
"""
from __future__ import annotations
from collections.abc import Mapping, Sequence
import ipaddress
from pathlib import PurePosixPath
import re

_SEG = r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}'
_ROUTE = re.compile(rf'omnicore/v1/({_SEG})/({_SEG})/({_SEG})/([a-z][a-z0-9_.]{{0,63}})\Z')
_CN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
_CAPS = frozenset({'intent.local','intent.classify','rag.query','media.thumbnail',
                   'media.tile_budget','media.offload','system.status'})


def _routes(values: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= 1024:
        raise ValueError('invalid_route_list')
    for value in values:
        match = _ROUTE.fullmatch(value) if isinstance(value, str) else None
        if not match or match[4] not in _CAPS:
            raise ValueError('invalid_exact_route')
    if len(set(values)) != len(values):
        raise ValueError('duplicate_route')
    return tuple(sorted(values))


def _cn(value: str) -> str:
    if not isinstance(value, str) or not _CN.fullmatch(value):
        raise ValueError('invalid_certificate_cn')
    return value


def _path(value: str) -> str:
    if (not isinstance(value, str) or not value.startswith('/') or value.startswith('//')
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or '..' in value.split('/') or str(PurePosixPath(value)) != value or value == '/'):
        raise ValueError('invalid_pki_path')
    return value


def compile_router_config(*, service_cn: str, grants: Mapping[str, Sequence[str]],
                          expected_routes: Sequence[str], bind_ip: str, port: int,
                          ca: str, cert: str, key: str) -> dict:
    """Return a complete dedicated-router configuration (JSON serializable).

    expected_routes must come from the trusted SignedIngress.routes snapshot.
    One client CN maps to one logical peer/tenant; one route has one owner.
    The router has no local application, no router federation and no discovery.
    Config generation is not deployment or a Zenoh parser/runtime validation.
    """
    _cn(service_cn)
    expected = _routes(expected_routes)
    if len({r.split('/')[2] for r in expected}) != 1:
        raise ValueError('multiple_service_nodes')
    if not isinstance(grants, Mapping) or not 1 <= len(grants) <= 256:
        raise ValueError('invalid_grants')
    if not isinstance(bind_ip, str):
        raise ValueError('invalid_bind_ip')
    ip = ipaddress.ip_address(bind_ip)
    if ip.is_unspecified or ip.is_multicast or getattr(ip, 'scope_id', None) is not None:
        raise ValueError('invalid_bind_ip')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid_port')
    paths = [_path(v) for v in (ca, cert, key)]
    if len(set(paths)) != 3:
        raise ValueError('duplicate_pki_path')
    subjects, rules, policies = [], [], []
    owned, identities = set(), set()

    def add(cn, routes, directions):
        sid = f's{len(subjects)}'
        subjects.append({'id':sid,'cert_common_names':[cn],'link_protocols':['tls']})
        ids = []
        for flow, messages in directions:
            rid = f'r{len(rules)}'
            rules.append({'id':rid,'permission':'allow','flows':[flow],
                          'messages':messages,'key_exprs':list(routes)})
            ids.append(rid)
        policies.append({'subjects':[sid],'rules':ids})

    for cn in grants:
        _cn(cn)
    for cn in sorted(grants):
        if cn == service_cn:
            raise ValueError('service_cn_collision')
        routes = _routes(grants[cn])
        owners = {tuple(r.split('/')[3:5]) for r in routes}
        if len(owners) != 1 or identities.intersection(owners) or owned.intersection(routes):
            raise ValueError('ambiguous_route_owner')
        identities.update(owners)
        owned.update(routes)
        add(cn, routes, [('ingress',['query']),('egress',['reply'])])
    if owned != set(expected):
        raise ValueError('route_registry_mismatch')
    add(service_cn, expected, [('ingress',['declare_queryable','reply']),('egress',['query'])])
    addr = f'[{ip}]' if ip.version == 6 else str(ip)
    return {'mode':'router','listen':{'endpoints':[f'tls/{addr}:{port}'],'timeout_ms':0},
            'connect':{'endpoints':[]},
            'scouting':{'multicast':{'enabled':False},'gossip':{'enabled':False}},
            'adminspace':{'enabled':False},
            'transport':{'link':{'protocols':['tls'],'tls':{
                'root_ca_certificate':paths[0],'listen_certificate':paths[1],
                'listen_private_key':paths[2],'enable_mtls':True,
                'verify_name_on_connect':True,'close_link_on_expiration':True}}},
            'access_control':{'enabled':True,'default_permission':'deny',
                              'rules':rules,'subjects':subjects,'policies':policies}}
