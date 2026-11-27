"""Private stdin/stdout worker for trusted, fixed, side-effect-free local handlers."""
from __future__ import annotations
import json
from pathlib import Path
import sys

# -I excludes the script directory; import only from the installed trusted tree.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omnicore_host.local_services import local_handlers
from omnicore_host.rpc import CallerIdentity, RpcRequest


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(262_145)
        if len(raw) > 262_144:
            return 2
        envelope = json.loads(raw.decode('utf-8'))
        req = RpcRequest(**envelope['request'])
        identity = envelope['principal']
        principal = CallerIdentity(identity['peer_id'], identity['tenant'],
                                   frozenset(identity['allowed_sources']),
                                   frozenset(identity['allowed_capabilities']))
        handler = local_handlers().get(req.capability)
        if handler is None or req.source not in principal.allowed_sources or req.capability not in principal.allowed_capabilities:
            return 2
        output = json.dumps(handler(req, principal), ensure_ascii=False, allow_nan=False,
                            separators=(',', ':')).encode('utf-8')
        if len(output) > 32_768:
            return 2
        sys.stdout.buffer.write(output)
        return 0
    except Exception:
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
