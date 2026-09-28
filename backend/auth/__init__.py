"""
ValiGuard AI authentication package.

Implements the Web3 authentication flow specified in the Phase 1
documentation (UC-01 / deployment sequence, section 4.10):

    MetaMask connects -> POST /auth/request-nonce -> wallet signs nonce
    -> POST /auth/verify (backend recovers the signer) -> JWT issued ->
    Bearer token grants access to secure telemetry endpoints.

Modules:
    nonce_store: In-memory, TTL-bound nonce store (request-nonce phase)
    jwt_auth:    JWT issuing/verification + @require_auth decorator
    routes:      /api/v1/auth/* Flask routes
"""
