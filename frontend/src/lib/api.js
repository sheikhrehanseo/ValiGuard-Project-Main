"use client";

/**
 * ValiGuard API client with Web3 authentication (UC-01).
 *
 * Auth flow:
 *   1. POST /api/v1/auth/request-nonce {address}
 *   2. Wallet signs the returned message (personal_sign)
 *   3. POST /api/v1/auth/verify {address, nonce, signature} -> JWT
 *   4. JWT is stored in localStorage and attached as a Bearer header to
 *      every subsequent API call via `authedFetch`.
 *
 * Demo mode (no MetaMask): an ephemeral wallet is generated in the browser,
 * persisted in localStorage, and signs the nonce — the same server flow,
 * no extension required.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
const TOKEN_KEY = 'valiguard_jwt';
const DEMO_WALLET_KEY = 'valiguard_demo_wallet_pk';

// --- Token storage ---------------------------------------------------------

export function getToken() {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
    if (typeof window === 'undefined') return;
    if (token) {
        localStorage.setItem(TOKEN_KEY, token);
    } else {
        localStorage.removeItem(TOKEN_KEY);
    }
}

export function isAuthenticated() {
    return !!getToken();
}

// --- 401 recovery -----------------------------------------------------------

/**
 * Wallet context registered by WalletConnect after a successful sign-in so
 * authedFetch can transparently re-run the auth flow when a token expires.
 * Shape: { address, signMessage(msg) -> Promise<string> }
 */
let walletContext = null;

// Single in-flight re-auth promise shared by ALL parallel 401 responses —
// a burst of expired-token requests triggers exactly ONE wallet sign prompt.
let reauthInFlight = null;

export function setWalletContext(ctx) {
    walletContext = ctx;
}

export function clearWalletContext() {
    walletContext = null;
    reauthInFlight = null;
}

async function ensureFreshToken() {
    if (!reauthInFlight) {
        reauthInFlight = authenticateWallet(
            walletContext.address,
            walletContext.signMessage
        ).finally(() => {
            reauthInFlight = null;
        });
    }
    return reauthInFlight;
}

/**
 * fetch wrapper that attaches the stored JWT.
 * On a 401 while a wallet context is registered, clears the stale token,
 * re-runs the Web3 auth flow (nonce -> sign -> verify) — deduped so
 * parallel 401s share one re-auth — and retries once.
 * Returns the raw Response; callers decide how to handle status codes.
 */
export async function authedFetch(path, options = {}) {
    const doFetch = () => {
        const token = getToken();
        const headers = {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            ...(options.headers || {}),
        };
        return fetch(`${API_BASE}${path}`, { ...options, headers });
    };

    let res = await doFetch();

    if (res.status === 401 && getToken() && walletContext) {
        setToken(null);
        try {
            await ensureFreshToken();
            res = await doFetch(); // retry once with the fresh token
        } catch (err) {
            console.error('Re-authentication failed:', err);
        }
    }
    return res;
}

// --- Web3 authentication flow ----------------------------------------------

export async function requestNonce(address) {
    const res = await fetch(`${API_BASE}/api/v1/auth/request-nonce`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || 'Failed to request nonce');
    return body.data; // { nonce, message, expires_in }
}

export async function verifySignature(address, nonce, signature) {
    const res = await fetch(`${API_BASE}/api/v1/auth/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address, nonce, signature }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || 'Signature verification failed');
    return body.data; // { token, token_type, expires_in, address }
}

/**
 * Full sign-in flow for a connected wallet.
 * @param {string} address  Wallet address
 * @param {function(string): Promise<string>} signMessage  signer.signMessage
 * @returns {Promise<string>} the stored JWT
 */
export async function authenticateWallet(address, signMessage) {
    const { nonce, message } = await requestNonce(address);
    const signature = await signMessage(message);
    const data = await verifySignature(address, nonce, signature);
    setToken(data.token);
    return data.token;
}

// --- Demo (no-MetaMask) wallet ----------------------------------------------

/**
 * Get (or lazily create) a persisted ephemeral wallet for demo mode.
 * Same server-side auth flow — just a locally generated signer.
 */
export async function getDemoWallet() {
    const { ethers } = await import('ethers');
    let pk = localStorage.getItem(DEMO_WALLET_KEY);
    if (!pk) {
        pk = ethers.Wallet.createRandom().privateKey;
        localStorage.setItem(DEMO_WALLET_KEY, pk);
    }
    return new ethers.Wallet(pk);
}
