"""Ed25519 request signatures - the same scheme Learner State plans for evidence payloads
(learner-state architecture §9.2.1).

A sender signs canonical(body); body names the sender, so a signature cannot be moved to
another sender's name, and the request_id inside it cannot be changed without breaking it.
"""
import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (Ed25519PrivateKey,
                                                               Ed25519PublicKey)

from .contract import canonical


def new_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def public_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw,
                                         serialization.PublicFormat.Raw)


def private_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def load_private(pem: bytes) -> Ed25519PrivateKey:
    return serialization.load_pem_private_key(pem, password=None)


def sign(body: dict, key: Ed25519PrivateKey) -> dict:
    """The envelope a sender sends."""
    return {"body": body, "signature": base64.b64encode(key.sign(canonical(body))).decode()}


def verify(body: dict, signature: bytes, public_key: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes(public_key)).verify(signature, canonical(body))
        return True
    except (InvalidSignature, ValueError):
        return False
