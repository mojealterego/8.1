import json
import unittest
from omnicore_host.zenoh_acl import compile_router_config

A = 'omnicore/v1/node/tenantA/peerA/intent.local'
B = 'omnicore/v1/node/tenantB/peerB/system.status'


def config(grants=None, **kw):
    args = dict(service_cn='service', grants={'client-a': [A], 'client-b': [B]},
                expected_routes=[A, B], bind_ip='127.0.0.1', port=7447,
                ca='/pki/ca.pem', cert='/pki/router.pem', key='/pki/router.key')
    if grants is not None:
        args['grants'] = grants
    args.update(kw)
    return compile_router_config(**args)


def permitted(acl, cn, protocol, flow, message, route):
    # Independent evaluator for generated exact-key, singleton-CN policies only.
    subjects = {s['id']: s for s in acl['subjects']}
    rules = {r['id']: r for r in acl['rules']}
    decisions = []
    for p in acl['policies']:
        if any(cn in subjects[s]['cert_common_names'] and protocol in subjects[s]['link_protocols'] for s in p['subjects']):
            for rid in p['rules']:
                r = rules[rid]
                if flow in r['flows'] and message in r['messages'] and route in r['key_exprs']:
                    decisions.append(r['permission'])
    return 'deny' not in decisions and ('allow' in decisions or acl['default_permission'] == 'allow')


class AclTests(unittest.TestCase):
    def test_exhaustive_direction_matrix(self):
        acl = config()['access_control']
        for cn in ('client-a', 'client-b', 'service', 'unknown', None):
            for proto in ('tls', 'tcp', 'quic'):
                for flow in ('ingress', 'egress'):
                    for message in ('query', 'reply', 'declare_queryable', 'put', 'delete', 'declare_subscriber', 'liveliness_token', 'liveliness_query', 'declare_liveliness_subscriber'):
                        for route in (A, B, A.replace('peerA', '*'), 'other/key'):
                            expected = proto == 'tls' and ((cn == 'service' and route in (A, B) and (flow, message) in (('ingress','declare_queryable'),('ingress','reply'),('egress','query'))) or (cn in ('client-a','client-b') and route == {'client-a':A,'client-b':B}.get(cn) and (flow,message) in (('ingress','query'),('egress','reply'))))
                            self.assertEqual(permitted(acl, cn, proto, flow, message, route), expected, (cn,proto,flow,message,route))

    def test_deterministic(self):
        self.assertEqual(json.dumps(config()), json.dumps(config({'client-b':[B],'client-a':[A]}, expected_routes=[B,A])))

    def test_rejects_duplicate_route_owner(self):
        with self.assertRaises(ValueError): config({'client-a':[A,B], 'client-b':[B]})

    def test_rejects_missing_or_extra_routes(self):
        for grants in ({'client-a':[A]}, {'client-a':[A,B,A.replace('peerA','peerC')]}):
            with self.assertRaises(ValueError): config(grants)

    def test_rejects_wildcards_and_unknown_capability(self):
        for route in (A.replace('peerA','*'), A.replace('peerA','$*'), A.replace('intent.local','shell.exec')):
            with self.assertRaises(ValueError): config({'client-a':[route]}, expected_routes=[route])

    def test_rejects_service_identity_collision(self):
        with self.assertRaises(ValueError): config(service_cn='client-a')

    def test_rejects_client_multi_identity(self):
        with self.assertRaises(ValueError): config({'client-a':[A,B]})

    def test_rejects_node_mismatch(self):
        other = B.replace('/node/','/node2/')
        with self.assertRaises(ValueError): config({'client-a':[A], 'client-b':[other]}, expected_routes=[A,other])

    def test_secure_transport(self):
        c = config()
        self.assertEqual(c['mode'],'router')
        self.assertEqual(c['listen']['endpoints'],['tls/127.0.0.1:7447'])
        self.assertEqual(c['connect']['endpoints'],[])
        self.assertEqual(c['transport']['link']['protocols'],['tls'])
        self.assertTrue(c['transport']['link']['tls']['enable_mtls'])
        self.assertTrue(c['transport']['link']['tls']['close_link_on_expiration'])
        self.assertFalse(c['scouting']['multicast']['enabled'])
        self.assertFalse(c['scouting']['gossip']['enabled'])
        self.assertFalse(c['adminspace']['enabled'])
        self.assertEqual(c['access_control']['default_permission'],'deny')

    def test_bad_deployment_config(self):
        for kw in ({'bind_ip':'0.0.0.0'}, {'bind_ip':'localhost'}, {'port':True}, {'key':'relative.key'}, {'service_cn':'*'}, {'ca':'/pki/../ca.pem'}):
            with self.assertRaises(ValueError): config(**kw)

    def test_ipv6_endpoint(self):
        self.assertEqual(config(bind_ip='::1')['listen']['endpoints'],['tls/[::1]:7447'])

    def test_certificate_cn_rotation_replaces_permissions(self):
        before = config()['access_control']
        after = config({'new-a':[A],'client-b':[B]})['access_control']
        self.assertTrue(permitted(before,'client-a','tls','ingress','query',A))
        self.assertFalse(permitted(after,'client-a','tls','ingress','query',A))
        self.assertTrue(permitted(after,'new-a','tls','ingress','query',A))

if __name__ == '__main__': unittest.main()
