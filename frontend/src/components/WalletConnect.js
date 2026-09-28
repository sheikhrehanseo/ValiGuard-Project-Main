"use client";

import { useState, useEffect } from 'react';
import { ethers } from 'ethers';
import { User, Wallet, ShieldCheck } from 'lucide-react';
import { authenticateWallet, getDemoWallet, setWalletContext, clearWalletContext } from '../lib/api';

// Demo (no-MetaMask) fallback only when explicitly enabled at build time.
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

export default function WalletConnect({ onConnect }) {
    const [walletAddress, setWalletAddress] = useState(null);
    const [balance, setBalance] = useState(null);
    const [isConnecting, setIsConnecting] = useState(false);
    const [isAuthenticating, setIsAuthenticating] = useState(false);
    const [error, setError] = useState(null);
    const [authError, setAuthError] = useState(null);
    const [isDemo, setIsDemo] = useState(false);

    // Auto-connect if permission already granted
    useEffect(() => {
        if (typeof window !== 'undefined' && window.ethereum) {
            window.ethereum.request({ method: 'eth_accounts' })
                .then(handleAccountsChanged)
                .catch(console.error);

            window.ethereum.on('accountsChanged', handleAccountsChanged);
        }
        return () => {
            if (typeof window !== 'undefined' && window.ethereum) {
                window.ethereum.removeListener('accountsChanged', handleAccountsChanged);
            }
        }
    }, []);

    const signInWithBackend = async (address, signMessage) => {
        // Web3 login (UC-01): nonce -> signature -> JWT stored by api client
        setIsAuthenticating(true);
        try {
            await authenticateWallet(address, signMessage);
            // Register for transparent 401 re-auth in authedFetch.
            setWalletContext({ address, signMessage });
            setAuthError(null);
        } catch (err) {
            console.error('Backend sign-in failed:', err);
            setAuthError(err.message || 'Authentication failed');
        } finally {
            setIsAuthenticating(false);
        }
    };

    const handleAccountsChanged = async (accounts) => {
        if (accounts.length > 0) {
            const address = accounts[0];
            setWalletAddress(address);
            if (onConnect) onConnect(address);
            fetchBalance(address);
            // Sign in to the ValiGuard API with the connected wallet.
            const provider = new ethers.BrowserProvider(window.ethereum);
            const signer = await provider.getSigner();
            await signInWithBackend(address, (msg) => signer.signMessage(msg));
        } else {
            setWalletAddress(null);
            setBalance(null);
            if (onConnect) onConnect(null);
        }
    };

    const fetchBalance = async (address) => {
        try {
            if (window.ethereum) {
                const provider = new ethers.BrowserProvider(window.ethereum);
                const bal = await provider.getBalance(address);
                setBalance(ethers.formatEther(bal));
            }
        } catch (err) {
            console.error("Failed to fetch balance:", err);
        }
    };

    const connectWallet = async () => {
        setIsConnecting(true);
        setError(null);

        if (typeof window !== 'undefined' && window.ethereum) {
            try {
                const provider = new ethers.BrowserProvider(window.ethereum);
                const accounts = await provider.send("eth_requestAccounts", []);
                handleAccountsChanged(accounts);
            } catch (err) {
                console.warn("Wallet connection failed:", err);
                if (err.code === 4001) {
                    setError("Connection rejected");
                } else {
                    setError("Connection failed");
                }
            }
        } else if (DEMO_MODE) {
            // Demo mode (NEXT_PUBLIC_DEMO_MODE=true): no MetaMask — sign in
            // with a persisted ephemeral wallet.
            console.log("MetaMask unavailable. Using Demo Wallet with backend auth.");
            setTimeout(async () => {
                try {
                    const demoWallet = await getDemoWallet();
                    setWalletAddress(demoWallet.address);
                    setIsDemo(true);
                    setBalance("1,000.00");
                    if (onConnect) onConnect(demoWallet.address);
                    await signInWithBackend(demoWallet.address, (msg) => demoWallet.signMessage(msg));
                } catch (err) {
                    console.error("Demo sign-in failed:", err);
                    setError("Demo authentication failed");
                }
            }, 500);
        } else {
            setError("No wallet found. Install MetaMask or set NEXT_PUBLIC_DEMO_MODE=true.");
        }
        setIsConnecting(false);
    };

    const disconnectWallet = () => {
        setWalletAddress(null);
        setBalance(null);
        setIsDemo(false);
        clearWalletContext();
        if (onConnect) onConnect(null);
    };

    return (
        <div className="flex flex-col items-end">
            <button
                onClick={walletAddress ? disconnectWallet : connectWallet}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all shadow-lg ${walletAddress
                    ? 'bg-slate-700 text-green-400 border border-green-500/30'
                    : 'bg-gradient-to-r from-blue-600 to-purple-600 text-white hover:opacity-90'
                    }`}
                disabled={isConnecting}
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
                        {isConnecting ? 'Connecting...' : 'Connect Wallet'}
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
