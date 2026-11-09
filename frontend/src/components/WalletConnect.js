"use client";

import { useState, useEffect, useRef } from 'react';
import { ethers } from 'ethers';
import { User, Wallet, ShieldCheck } from 'lucide-react';
import {
    authenticateWallet,
    getDemoWallet,
    setWalletContext,
    clearWalletContext,
    getToken,
    setToken,
    isAuthenticated
} from '../lib/api';

// Demo (no-MetaMask) fallback only when explicitly enabled at build time.
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';

export default function WalletConnect({ onConnect }) {
    const [walletAddress, setWalletAddress] = useState(null);
    const [balance, setBalance] = useState(null);
    const [isConnecting, setIsConnecting] = useState(false);
    const [isAuthenticating, setIsAuthenticating] = useState(false);
    const [error, setError] = useState(null);
    const [authError, setAuthError] = useState(null);
    const [isDemo, setIsDemo] = useState(false);

    const isAuthenticatingRef = useRef(false);
    const isConnectingRef = useRef(false);

    // Auto-connect if permission already granted
    useEffect(() => {
        if (typeof window !== 'undefined' && window.ethereum) {
            window.ethereum.request({ method: 'eth_accounts' })
                .then(handleAccountsChanged)
                .catch((err) => console.warn("Wallet auto-check skipped:", err));

            window.ethereum.on('accountsChanged', handleAccountsChanged);
        }
        return () => {
            if (typeof window !== 'undefined' && window.ethereum) {
                window.ethereum.removeListener('accountsChanged', handleAccountsChanged);
            }
        };
    }, []);

    const signInWithBackend = async (address, signMessage) => {
        // Guard against duplicate / concurrent calls
        if (isAuthenticatingRef.current) return false;
        isAuthenticatingRef.current = true;
        setIsAuthenticating(true);
        try {
            await authenticateWallet(address, signMessage);
            // Register for transparent 401 re-auth in authedFetch.
            setWalletContext({ address, signMessage });
            setAuthError(null);
            return true;
        } catch (err) {
            console.warn('Backend sign-in failed:', err);
            setAuthError(err.message || 'Authentication failed');
            return false;
        } finally {
            setIsAuthenticating(false);
            isAuthenticatingRef.current = false;
        }
    };

    const handleAccountsChanged = async (accounts) => {
        if (accounts && accounts.length > 0) {
            const address = accounts[0];
            fetchBalance(address);

            if (typeof window !== 'undefined' && window.ethereum) {
                const provider = new ethers.BrowserProvider(window.ethereum);
                const signer = await provider.getSigner();
                const signMessage = (msg) => signer.signMessage(msg);
                setWalletContext({ address, signMessage });

                // Check if existing token in localStorage is already valid for this address
                let authed = false;
                const token = getToken();
                if (token) {
                    try {
                        const meRes = await fetch(`${API_BASE}/api/v1/auth/me`, {
                            headers: { Authorization: `Bearer ${token}` }
                        });
                        if (meRes.ok) {
                            const meData = await meRes.json();
                            if (meData.success && meData.data?.address?.toLowerCase() === address.toLowerCase()) {
                                authed = true;
                            }
                        }
                    } catch (e) {
                        // ignore network issue, proceed to sign in
                    }
                }

                if (!authed) {
                    authed = await signInWithBackend(address, signMessage);
                }

                if (authed) {
                    setWalletAddress(address);
                    setAuthError(null);
                    if (onConnect) onConnect(address);
                }
            }
        } else {
            setWalletAddress(null);
            setBalance(null);
            setToken(null);
            clearWalletContext();
            if (onConnect) onConnect(null);
        }
    };

    const fetchBalance = async (address) => {
        // 1. Try MetaMask BrowserProvider first
        if (typeof window !== 'undefined' && window.ethereum) {
            try {
                const provider = new ethers.BrowserProvider(window.ethereum);
                const bal = await provider.getBalance(address);
                setBalance(ethers.formatEther(bal));
                return;
            } catch (err) {
                // MetaMask RPC rate-limited (-32002) or unreachable; fall back to backend RPC
                console.warn("MetaMask getBalance fallback to backend RPC:", err?.message || err);
            }
        }

        // 2. Fallback to backend /api/v1/qie/account/<address>
        try {
            const res = await fetch(`${API_BASE}/api/v1/qie/account/${address}`);
            if (res.ok) {
                const body = await res.json();
                const rawBal = body?.data?.balance || "0";
                setBalance(ethers.formatEther(rawBal));
                return;
            }
        } catch (fallbackErr) {
            // Ignore and default to 0.0000
        }
        setBalance("0.0000");
    };

    const connectWallet = async () => {
        if (isConnectingRef.current) return;
        isConnectingRef.current = true;
        setIsConnecting(true);
        setError(null);
        setAuthError(null);

        try {
            if (typeof window !== 'undefined' && window.ethereum) {
                const provider = new ethers.BrowserProvider(window.ethereum);
                const accounts = await provider.send("eth_requestAccounts", []);
                await handleAccountsChanged(accounts);
            } else if (DEMO_MODE) {
                console.log("MetaMask unavailable. Using Demo Wallet with backend auth.");
                const demoWallet = await getDemoWallet();
                const signMessage = (msg) => demoWallet.signMessage(msg);
                setWalletContext({ address: demoWallet.address, signMessage });
                setBalance("1,000.00");
                const ok = await signInWithBackend(demoWallet.address, signMessage);
                if (ok) {
                    setWalletAddress(demoWallet.address);
                    setIsDemo(true);
                    if (onConnect) onConnect(demoWallet.address);
                }
            } else {
                setError("No wallet found. Install MetaMask or set NEXT_PUBLIC_DEMO_MODE=true.");
            }
        } catch (err) {
            console.warn("Wallet connection failed:", err);
            if (err.code === 4001) {
                setError("Connection rejected");
            } else {
                setError("Connection failed");
            }
        } finally {
            setIsConnecting(false);
            isConnectingRef.current = false;
        }
    };

    const disconnectWallet = () => {
        setWalletAddress(null);
        setBalance(null);
        setIsDemo(false);
        setToken(null);
        clearWalletContext();
        if (onConnect) onConnect(null);
    };

    return (
        <div className="flex flex-col items-end">
            <button
                id="wallet-connect-button"
                onClick={walletAddress ? disconnectWallet : connectWallet}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all shadow-lg ${walletAddress
                    ? 'bg-slate-700 text-green-400 border border-green-500/30'
                    : 'bg-gradient-to-r from-blue-600 to-purple-600 text-white hover:opacity-90'
                    }`}
                disabled={isConnecting || isAuthenticating}
            >
                {walletAddress ? (
                    <>
                        <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                        <span className="font-mono">{walletAddress.substring(0, 6)}...{walletAddress.substring(walletAddress.length - 4)}</span>
                        {isDemo && <span className="text-[10px] text-slate-400 ml-1">DEMO</span>}
                    </>
                ) : (
                    <>
                        <Wallet className="w-4 h-4" />
                        {isConnecting || isAuthenticating ? 'Connecting...' : 'Connect Wallet'}
                    </>
                )}
            </button>
            {isAuthenticating && (
                <div className="text-xs text-blue-400 mt-1 mr-1">Signing in...</div>
            )}
            {walletAddress && balance && (
                <div className="text-xs text-slate-400 mt-1 mr-1 font-mono">
                    {parseFloat(balance).toFixed(4)} QIE
                </div>
            )}
            {(error || authError) && (
                <div className="text-xs text-red-400 mt-1 mr-1">
                    {error || authError}
                </div>
            )}
        </div>
    );
}