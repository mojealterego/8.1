"""Small, verified offline handlers. No Android action or AI is executed here.

They provide advisory UI intents only; the Android UI must check user intent
and invoke permitted Android Intents itself. No arbitrary command or tool calls.
"""
from __future__ import annotations
from .rpc import CallerIdentity, RpcRequest


def intent_local(request: RpcRequest, principal: CallerIdentity) -> dict:
    text = request.payload.casefold()
    if any(w in text for w in ('galeri', 'zdjęci', 'zdjeci', 'photo')):
        action = 'open_gallery'
    elif any(w in text for w in ('ustawieni', 'ustaw', 'setting')):
        action = 'open_settings'
    elif any(w in text for w in ('plik', 'file')):
        action = 'open_files'
    elif any(w in text for w in ('telefon', 'zadzwoń', 'zadzwo', 'call')):
        action = 'open_dialer'  # Dialer, no call placement
    else:
        action = 'no_matching_intent'
    return {'action':action,'offline':True}


def system_status(request: RpcRequest, principal: CallerIdentity) -> dict:
    return {'gateway':'host_only','online':True,'remote_ai':'not_configured',
            'android_rom':'not_built'}


def local_handlers() -> dict:
    return {'intent.local':intent_local,'system.status':system_status}