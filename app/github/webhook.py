import hmac
import hashlib

def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False
    # GitHub sends: "sha256=..."
    if not signature_header.startswith("sha256="):
        return False
    their_sig = signature_header.split("=", 1)[1].strip()
    our_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(our_sig, their_sig)
