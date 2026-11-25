"""Real filesystem Unix socket service; no Zenoh/AI execution is implied."""
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import threading
import uuid
import pytest

from omnicore_host.rpc import CallerIdentity
from omnicore_host.adapter import DigitalLifeAdapter
from omnicore_host.gateway import Gateway
from omnicore_host.local_services import local_handlers
from omnicore_host.replay import ReplayStore
from omnicore_host.transport import get_peer_credential, IdentityRegistry, UnixRpcEndpoint
from omnicore_host.server import LocalHostServer, send_rpc_frame


def frame(cap, payload='proszę otwórz galerię'):
    return json.dumps({'schema':'omnicore.rpc.v1','request_id':str(uuid.uuid4()),
       'source':'omnicore-home','capability':cap,'deadline_ms':1000,
       'payload_sha256':hashlib.sha256(payload.encode()).hexdigest(),
       'reply_to':'device/local/session','payload':payload},ensure_ascii=False).encode('utf-8')


def test_offline_intents_are_real_local_decisions():
    handler=local_handlers()['intent.local']
    from omnicore_host.rpc import RpcRequest
    req=RpcRequest(str(uuid.uuid4()),'omnicore-home','intent.local',500,'proszę otwórz galerię','device/local/session')
    principal=CallerIdentity('p','t',frozenset({'omnicore-home'}),frozenset({'intent.local'}))
    assert handler(req,principal)=={'action':'open_gallery','offline':True}


def test_status_does_not_claim_remote_engine_is_running():
    handler=local_handlers()['system.status']
    from omnicore_host.rpc import RpcRequest
    req=RpcRequest(str(uuid.uuid4()),'omnicore-home','system.status',500,'','device/local/session')
    principal=CallerIdentity('p','t',frozenset({'omnicore-home'}),frozenset({'system.status'}))
    assert handler(req,principal)['remote_ai']=='not_configured'


def test_filesystem_socket_end_to_end(tmp_path):
    socket_dir=tmp_path/'sock'
    socket_dir.mkdir(mode=0o700)
    socket_path=socket_dir/'rpc.sock'
    # Discover kernel-supplied context from a real host AF_UNIX socketpair.
    a,b=socket.socketpair()
    try:
        peer=get_peer_credential(a)
    finally:
        a.close();b.close()
    principal=CallerIdentity('peer','tenant',frozenset({'omnicore-home'}),frozenset({'intent.local','system.status'}))
    reg=IdentityRegistry({(os.getuid(),peer.security_context):principal})
    gate=Gateway(ReplayStore(tmp_path/'replay.db'),DigitalLifeAdapter(local_handlers()))
    srv=LocalHostServer(socket_path,UnixRpcEndpoint(gate,reg))
    started=threading.Event();stop=threading.Event()
    thread=threading.Thread(target=srv.serve_forever,kwargs={'stop':stop,'started':started})
    thread.start()
    try:
        assert started.wait(2)
        response=send_rpc_frame(socket_path,frame('intent.local'))
        assert response['status']=='OK' and response['body']['action']=='open_gallery'
        assert socket_path.exists()
    finally:
        stop.set();thread.join(3)
    assert not thread.is_alive()
    assert not socket_path.exists()


def test_refuses_world_accessible_socket_parent(tmp_path):
    root=tmp_path/'world';root.mkdir(mode=0o777)
    root.chmod(0o777)
    srv=LocalHostServer(root/'rpc.sock',UnixRpcEndpoint(
        Gateway(ReplayStore(tmp_path/'r.db'),DigitalLifeAdapter({})),IdentityRegistry({})))
    with pytest.raises(PermissionError,match='socket_parent_insecure'):
        srv.prepare()


def test_refuses_to_overwrite_existing_socket_path(tmp_path):
    root=tmp_path/'safe';root.mkdir(mode=0o700)
    path=root/'rpc.sock';path.write_text('existing')
    srv=LocalHostServer(path,UnixRpcEndpoint(
        Gateway(ReplayStore(tmp_path/'r.db'),DigitalLifeAdapter({})),IdentityRegistry({})))
    with pytest.raises(FileExistsError):
        srv.prepare()
    assert path.read_text()=='existing'
