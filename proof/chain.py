"""Minimal Solana JSON-RPC client shared by anchoring and verification (requests only)."""
import requests

RPC = "https://api.devnet.solana.com"


def rpc(method, *params, url=RPC):
    reply = requests.post(url, json=dict(jsonrpc="2.0", id=1, method=method, params=list(params)), timeout=30).json()
    if "error" in reply:
        raise RuntimeError(f"{method}: {reply['error']}")
    return reply["result"]
