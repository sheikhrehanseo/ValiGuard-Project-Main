"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
    Shield,
    Activity,
    AlertTriangle,
    CheckCircle,
    BarChart3,
    Globe,
    Bell,
    User,
    Menu,
    ChevronRight,
    ChevronLeft,
    TrendingUp,
    Boxes,
    Newspaper,
    Filter,
    Search,
    RefreshCw,
    X,
    Lock,
    Wallet,
    CheckSquare
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

import WalletConnect from '../components/WalletConnect';
import { authedFetch, isAuthenticated, getToken } from '../lib/api';
import { io } from 'socket.io-client';
import { Line, Bar } from 'react-chartjs-2';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend,
    Filler
} from 'chart.js';

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend,
    Filler
);

// 4-tier severity styling (canonical scale from backend/core/severity.py)
const SEVERITY_STYLES = {
    critical: { bg: 'bg-red-500/10', border: 'border-red-500/50', text: 'text-red-400', icon: AlertTriangle, label: 'Critical' },
    high: { bg: 'bg-orange-500/10', border: 'border-orange-500/50', text: 'text-orange-400', icon: AlertTriangle, label: 'High' },
    medium: { bg: 'bg-yellow-500/10', border: 'border-yellow-500/50', text: 'text-yellow-400', icon: Activity, label: 'Medium' },
    low: { bg: 'bg-blue-500/10', border: 'border-blue-500/50', text: 'text-blue-400', icon: CheckCircle, label: 'Normal' },
};

const TX_PAGE_SIZE = 15;
const BRIDGE_PAGE_SIZE = 5;
const VALIDATOR_PAGE_SIZE = 6;

function parseUtcDate(timestamp) {
    if (!timestamp) return null;
    if (timestamp instanceof Date) return timestamp;
    let str = String(timestamp).trim();
    // SQLite/Python isoformat() omits 'Z' on UTC datetimes; append 'Z' so browser parses as UTC
    if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}/.test(str) && !str.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(str)) {
        str = str.replace(' ', 'T') + 'Z';
    }
    const parsed = new Date(str);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatTimeAgo(timestamp) {
    const parsed = parseUtcDate(timestamp);
    if (!parsed) return '—';

    const seconds = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
}

function deriveOnChainTxType(tx) {
    if (tx.raw_entry) return 'Raw Consensus Tx';
    const src = String(tx.source_chain || '').trim();
    const s = src.toLowerCase();
    const dst = String(tx.destination_chain || 'QIE').trim();
    const val = Number(tx.value ?? tx.amount ?? 0);

    if (s.includes('oracle')) return 'Oracle Update';
    if (s.includes('prediction') || s.includes('broq')) return 'Prediction Contract';
    if (s.includes('qiedex') || s.includes('qidex') || s.includes('liquidity') || s.includes('-lp') || s.includes('swap')) return 'DEX Swap / LP';
    if (s.includes('token') || s.includes('weth') || s.includes('wbnb') || s.includes('usdt') || s.includes('usdc') || s.includes('wqie') || s.includes('qusd') || s.includes('([a-z0-9]+)')) {
        if (src.includes('(') && src.includes(')') && !s.includes('contract')) return 'Token Transfer';
    }
    if (s.includes('token')) return 'Token Transfer';
    if (s.includes('native')) return val > 0 ? 'Native Transfer' : 'Smart Contract Call';
    if (s.includes('contract')) return 'Smart Contract Call';
    if (src in { Ethereum: 1, BSC: 1, Polygon: 1, Avalanche: 1 }) {
        return `${src} → ${dst}`;
    }
    return val > 0 ? 'Token Transfer' : 'Smart Contract Call';
}

function formatTxAmount(value, rawEntry = false, assetSymbol = null) {
    if (rawEntry || value == null) return '—';
    const num = Number(value);
    if (Number.isNaN(num)) return '—';
    const unit = assetSymbol || 'unknown asset';
    if (num === 0) return `0 ${unit}`;
    if (num < 0.01) return `${num.toFixed(4)} ${unit}`;
    return `${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })} ${unit}`;
}

function generateLast7DaysVolumeHistory() {
    const history = [];
    const baseCounts = [180, 210, 195, 240, 220, 265, 310];
    const baseVolumes = [24500, 31200, 28900, 42100, 36800, 48400, 55900];

    for (let i = 6; i >= 0; i--) {
        const d = new Date();
        d.setUTCDate(d.getUTCDate() - i);
        const yyyy = d.getUTCFullYear();
        const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
        const dd = String(d.getUTCDate()).padStart(2, '0');
        history.push({
            date: `${mm}-${dd}`,
            fullDate: `${yyyy}-${mm}-${dd}`,
            count: baseCounts[6 - i],
            volume: baseVolumes[6 - i]
        });
    }
    return history;
}

export default function Dashboard() {
    const isDemoModeEnabled = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

    const [mounted, setMounted] = useState(false);
    const [activeSection, setActiveSection] = useState('dashboard');
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [selectedNews, setSelectedNews] = useState(null);

    const [dataSource, setDataSource] = useState(isDemoModeEnabled ? 'MOCK' : 'REAL');
    const [walletAddress, setWalletAddress] = useState(null);
    const [backendStatus, setBackendStatus] = useState('unknown');

    // Validator & Node State
    const [stats, setStats] = useState({
        activeBridges: null,
        anomalies24h: 0,
        validationRate: null,
        modelAccuracy: null
    });

    const [nodeStatus, setNodeStatus] = useState({
        synced: false,
        height: null,
        moniker: null,
        network: null
    });

    // Daily Stats & Real Analytics
    const [dailyStats, setDailyStats] = useState(null);
    const [volumeHistory, setVolumeHistory] = useState([]);
    const [bridgeRoutes, setBridgeRoutes] = useState([]);
    const [validatorStats, setValidatorStats] = useState({
        total_validators: null,
        active_validators: null,
        avg_uptime: null,
        top_validators: []
    });

    // Live WebSocket & Paginated Transaction State
    const [liveAlerts, setLiveAlerts] = useState([]);
    const [transactions, setTransactions] = useState([]);
    const [txPage, setTxPage] = useState(1);
    const [txTotal, setTxTotal] = useState(0);

    // Pagination for Bridge Routes & Validators
    const [bridgePage, setBridgePage] = useState(1);
    const [validatorPage, setValidatorPage] = useState(1);

    const [pipelineLatency, setPipelineLatency] = useState(null);
    const [peakTps, setPeakTps] = useState(null);
    const [, setAgeTick] = useState(Date.now());

    // Alerts Tab Search, History & Multi-Select State
    const [alertHistory, setAlertHistory] = useState([]);
    const [alertPage, setAlertPage] = useState(1);
    const [alertTotal, setAlertTotal] = useState(0);
    const alertRequest = useRef(0);
    const anomalyRequest = useRef(0);
    const refreshAlertDataRef = useRef(null);
    const ALERT_PAGE_SIZE = 50;
    const [alertFilterSeverity, setAlertFilterSeverity] = useState('');
    const [alertFilterResolved, setAlertFilterResolved] = useState('');
    const [alertFilterTxHash, setAlertFilterTxHash] = useState('');
    const [alertFilterFrom, setAlertFilterFrom] = useState('');
    const [alertFilterTo, setAlertFilterTo] = useState('');
    const [alertsLoading, setAlertsLoading] = useState(false);
    const [selectedAlertIds, setSelectedAlertIds] = useState([]);

    useEffect(() => {
        setMounted(true);
    }, []);

    useEffect(() => {
        const interval = setInterval(() => setAgeTick(Date.now()), 1000);
        return () => clearInterval(interval);
    }, []);

    const handleWalletConnect = (address) => {
        setWalletAddress(address);
    };

    // Open endpoint node status fetch (public, no auth needed)
    const fetchPublicNodeStatus = useCallback(async () => {
        const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
        try {
            const statusRes = await fetch(`${API_BASE}/api/v1/qie/node/status`);
            if (statusRes.ok) {
                const statusData = await statusRes.json();
                setBackendStatus('online');
                if (statusData.success && statusData.data?.node) {
                    setNodeStatus(prev => ({
                        ...prev,
                        height: statusData.data.node.height ?? prev.height,
                        synced: !!statusData.data.node.healthy
                    }));
                }
            } else {
                const healthRes = await fetch(`${API_BASE}/health`).catch(() => null);
                setBackendStatus(healthRes && healthRes.ok ? 'online' : 'offline');
            }
        } catch (error) {
            const healthRes = await fetch(`${API_BASE}/health`).catch(() => null);
            setBackendStatus(healthRes && healthRes.ok ? 'online' : 'offline');
        }
    }, []);

    // Fetch paginated transaction history from backend
    const fetchTransactionPage = useCallback(async (pageToFetch = txPage) => {
        if (dataSource === 'MOCK') return;
        const authed = typeof window !== 'undefined' && (!!walletAddress || isAuthenticated());
        if (!authed) return;

        try {
            const offset = (pageToFetch - 1) * TX_PAGE_SIZE;
            const histRes = await authedFetch(`/api/v1/bridge/history?limit=${TX_PAGE_SIZE}&offset=${offset}`);
            if (histRes.ok) {
                const histData = await histRes.json();
                if (histData.success && Array.isArray(histData.data?.transactions)) {
                    setTxTotal(histData.data.total ?? histData.data.transactions.length);
                    const mappedTxs = histData.data.transactions.map(tx => {
                        const txHash = tx.tx_hash || tx.transaction_hash || '';
                        const value = tx.value ?? tx.amount;
                        return {
                            hash: txHash ? `${txHash.substring(0, 10)}...` : '—',
                            full_hash: txHash,
                            type: deriveOnChainTxType(tx),
                            timestamp: tx.timestamp || tx.created_at,
                            from: tx.sender ? `${tx.sender.substring(0, 10)}...${tx.sender.slice(-4)}` : '—',
                            amt: formatTxAmount(value, tx.raw_entry, tx.asset_symbol),
                            severity: tx.severity,
                            raw_entry: tx.raw_entry,
                            status: tx.status || 'confirmed'
                        };
                    });
                    setTransactions(mappedTxs);
                }
            }
        } catch (err) {
            console.warn("Transaction history fetch failed:", err);
        }
    }, [dataSource, walletAddress, txPage]);

    const fetchAnomalyCount = useCallback(async () => {
        if (dataSource !== 'REAL' || !(walletAddress || isAuthenticated())) return;
        const requestId = ++anomalyRequest.current;
        try {
            const res = await authedFetch('/api/v1/analytics/open-anomalies');
            if (!res.ok) return;
            const body = await res.json();
            if (body.success && requestId === anomalyRequest.current) {
                setStats(prev => ({ ...prev, anomalies24h: body.data.open_anomalies_24h }));
            }
        } catch (error) { console.warn('Anomaly count refresh failed:', error); }
    }, [dataSource, walletAddress]);

    // Authenticated data fetcher (runs only when wallet is connected)
    const fetchProtectedRealData = useCallback(async () => {
        const authed = typeof window !== 'undefined' && (!!walletAddress || isAuthenticated());
        if (!authed) return;

        try {
            setBackendStatus('online');

            fetchAnomalyCount();
            // 1. Fetch Daily Stats
            const statsRes = await authedFetch('/api/v1/analytics/daily-stats');
            let statsData = null;
            if (statsRes.ok) {
                statsData = await statsRes.json();
                if (statsData.success && statsData.data) {
                    setDailyStats(statsData.data);
                    setPeakTps(statsData.data.peak_tps ?? null);
                    if (Array.isArray(statsData.data.bridge_routes)) {
                        setBridgeRoutes(statsData.data.bridge_routes);
                    }
                    setStats(prev => ({
                        ...prev,
                        activeBridges: statsData.data.active_bridges ?? prev.activeBridges,
                        validationRate: statsData.data.low_risk_rate ?? null
                    }));
                }
            }

            // 2. Fetch Model Accuracy
            const modelRes = await authedFetch('/api/v1/analytics/model-accuracy');
            if (modelRes.ok) {
                const modelData = await modelRes.json();
                if (modelData.success && modelData.data) {
                    const rawAcc = modelData.data.accuracy;
                    const normalizedAcc = rawAcc == null
                        ? null
                        : (rawAcc <= 1 ? Number((rawAcc * 100).toFixed(2)) : Number(Number(rawAcc).toFixed(2)));
                    setStats(prev => ({
                        ...prev,
                        modelAccuracy: normalizedAcc,
                    }));
                }
            }

            // 3. Fetch Validator Stats
            const valRes = await authedFetch('/api/v1/analytics/validator-stats');
            if (valRes.ok) {
                const valData = await valRes.json();
                if (valData.success && valData.data) {
                    setValidatorStats(valData.data);
                    if (Array.isArray(valData.data.bridge_routes) && valData.data.bridge_routes.length > 0) {
                        setBridgeRoutes(valData.data.bridge_routes);
                    }
                    setStats(prev => ({
                        ...prev,
                        activeBridges: valData.data.active_bridges ?? prev.activeBridges ?? valData.data.active_validators
                    }));
                }
            }

            // 4. Fetch current page of Transaction History
            await fetchTransactionPage(txPage);

            // 5. Fetch Volume History for Traffic Chart (fetched once, then today's bar updated live)
            setVolumeHistory(prev => {
                if (prev.length === 7 && statsData?.success && statsData?.data) {
                    const updated = [...prev];
                    updated[6] = {
                        ...updated[6],
                        count: statsData.data.total_transactions ?? updated[6].count,
                        volume: statsData.data.total_volume ?? updated[6].volume,
                    };
                    return updated;
                }
                return prev;
            });

            if (volumeHistory.length === 0) {
                const dates = [];
                for (let i = 6; i >= 0; i--) {
                    const d = new Date();
                    d.setUTCDate(d.getUTCDate() - i);
                    dates.push(d.toISOString().slice(0, 10));
                }
                const dailyResponses = await Promise.all(
                    dates.map(dateStr =>
                        authedFetch(`/api/v1/analytics/daily-stats?date=${dateStr}`)
                            .then(r => r.ok ? r.json() : { success: false })
                            .catch(() => ({ success: false }))
                    )
                );
                const history = dates.map((dateStr, idx) => {
                    const res = dailyResponses[idx];
                    return {
                        date: dateStr.slice(5),
                        fullDate: dateStr,
                        count: (res.success && res.data?.total_transactions) ? res.data.total_transactions : 0,
                        volume: (res.success && res.data?.total_volume) ? res.data.total_volume : 0
                    };
                });
                setVolumeHistory(history);
            }

        } catch (error) {
            console.warn("Protected telemetry fetch warning:", error);
        }
    }, [walletAddress, txPage, volumeHistory.length, fetchTransactionPage, fetchAnomalyCount]);

    // When user clicks a transaction page number in REAL mode, fetch immediately
    useEffect(() => {
        if (dataSource === 'REAL' && (walletAddress || isAuthenticated())) {
            fetchTransactionPage(txPage);
        }
    }, [txPage, dataSource, walletAddress, fetchTransactionPage]);

    // Fetch Alerts with filter criteria
    const fetchFilteredAlerts = useCallback(async ({ silent = false } = {}) => {
        if (dataSource === 'MOCK') return;
        const authed = typeof window !== 'undefined' && (!!walletAddress || isAuthenticated());
        if (!authed) return;

        const requestId = ++alertRequest.current;
        if (!silent) setAlertsLoading(true);
        try {
            const params = new URLSearchParams();
            if (alertFilterSeverity) params.set('severity', alertFilterSeverity);
            if (alertFilterResolved) params.set('resolved', alertFilterResolved);
            if (alertFilterTxHash.trim()) params.set('tx_hash', alertFilterTxHash.trim());
            if (alertFilterFrom) params.set('from', alertFilterFrom);
            if (alertFilterTo) params.set('to', alertFilterTo);
            params.set('limit', String(ALERT_PAGE_SIZE));
            params.set('offset', String((alertPage - 1) * ALERT_PAGE_SIZE));

            const res = await authedFetch(`/api/v1/alerts?${params.toString()}`);
            if (res.ok) {
                const data = await res.json();
                const items = data.data?.alerts ?? data.data?.items;
                if (data.success && Array.isArray(items) && requestId === alertRequest.current) {
                    setAlertHistory(items);
                    setAlertTotal(data.data.total);
                    const lastPage = Math.max(1, Math.ceil(data.data.total / ALERT_PAGE_SIZE));
                    if (alertPage > lastPage) setAlertPage(lastPage);
                }
            }
        } catch (error) {
            console.warn("Failed to query alerts:", error);
        } finally {
            if (requestId === alertRequest.current) setAlertsLoading(false);
        }
    }, [dataSource, walletAddress, alertPage, alertFilterSeverity, alertFilterResolved, alertFilterTxHash, alertFilterFrom, alertFilterTo]);

    useEffect(() => {
        setAlertPage(1);
        setSelectedAlertIds([]);
    }, [alertFilterSeverity, alertFilterResolved, alertFilterTxHash, alertFilterFrom, alertFilterTo]);

    refreshAlertDataRef.current = () => Promise.all([fetchAnomalyCount(), fetchFilteredAlerts({ silent: true })]);


    // Handle Single Alert Resolution
    const handleResolveAlert = async (alertId) => {
        if (!alertId) return;
        if (dataSource === 'MOCK') {
            setLiveAlerts(prev => prev.map(a => (a.id === alertId || a.alert_id === alertId) ? { ...a, is_resolved: true } : a));
            setAlertHistory(prev => prev.map(a => (a.id === alertId || a.alert_id === alertId) ? { ...a, is_resolved: true } : a));
            setSelectedAlertIds(prev => prev.filter(id => id !== alertId));
            return;
        }
        try {
            const res = await authedFetch(`/api/v1/alerts/${alertId}/resolve`, { method: 'PATCH' });
            if (res.ok) {
                ++anomalyRequest.current;
                ++alertRequest.current;
                setLiveAlerts(prev => prev.map(a => (a.id === alertId || a.alert_id === alertId) ? { ...a, is_resolved: true } : a));
                setAlertHistory(prev => prev.map(a => (a.id === alertId || a.alert_id === alertId) ? { ...a, is_resolved: true } : a));
                setSelectedAlertIds(prev => prev.filter(id => id !== alertId));
                await refreshAlertDataRef.current();
            }
        } catch (err) {
            console.warn("Failed to resolve alert:", err);
        }
    };

    // Handle Multi-Select Bulk Alert Resolution
    const handleBulkResolveAlerts = async () => {
        if (selectedAlertIds.length === 0) return;
        const idsToResolve = [...selectedAlertIds];

        if (dataSource === 'MOCK') {
            setLiveAlerts(prev => prev.map(a => idsToResolve.includes(a.id ?? a.alert_id) ? { ...a, is_resolved: true } : a));
            setAlertHistory(prev => prev.map(a => idsToResolve.includes(a.id ?? a.alert_id) ? { ...a, is_resolved: true } : a));
            setSelectedAlertIds([]);
            return;
        }

        try {
            const res = await authedFetch('/api/v1/alerts/resolve-bulk', {
                method: 'POST',
                body: JSON.stringify({ alert_ids: idsToResolve }),
            });
            if (res.ok) {
                ++anomalyRequest.current;
                ++alertRequest.current;
                setLiveAlerts(prev => prev.map(a => idsToResolve.includes(a.id ?? a.alert_id) ? { ...a, is_resolved: true } : a));
                setAlertHistory(prev => prev.map(a => idsToResolve.includes(a.id ?? a.alert_id) ? { ...a, is_resolved: true } : a));
                setSelectedAlertIds([]);
                await refreshAlertDataRef.current();
            }
        } catch (err) {
            console.warn("Bulk alert resolution failed:", err);
        }
    };

    // Periodic Polling Effect
    useEffect(() => {
        let interval;

        if (dataSource === 'MOCK' && isDemoModeEnabled) {
            setBackendStatus('online');
            setNodeStatus({
                synced: true,
                height: 1245032,
                moniker: 'ValiGuard AI Validator (demo)',
                network: 'demo'
            });
            setStats(prev => prev.activeBridges ? prev : {
                activeBridges: 4,
                anomalies24h: 1,
                validationRate: 98.5,
                modelAccuracy: 95.12
            });
            setDailyStats(prev => prev ? prev : {
                total_transactions: 1420,
                validation_success_rate: 98.5,
                avg_anomaly_score: 18.4,
                critical_alerts: 0,
                high_alerts: 1,
                severity_counts: { low: 950, medium: 340, high: 120, critical: 10 }
            });
            setVolumeHistory(prev => prev.length > 0 ? prev : generateLast7DaysVolumeHistory());
            setBridgeRoutes(prev => prev.length > 0 ? prev : [
                { chain: 'Ethereum', status: 'active', transactions: 620, volume: 145200.5, flagged: 1 },
                { chain: 'BSC', status: 'active', transactions: 410, volume: 68400.0, flagged: 0 },
                { chain: 'Polygon', status: 'active', transactions: 290, volume: 41200.0, flagged: 0 },
                { chain: 'Avalanche', status: 'active', transactions: 100, volume: 13000.0, flagged: 0 }
            ]);
            setValidatorStats(prev => prev.total_validators ? prev : {
                total_validators: 6,
                active_validators: 5,
                avg_uptime: 99.4,
                top_validators: [
                    { address: 'qie1valoper1...89a', name: 'Demo Validator Alpha', stake_amount: 45000, voting_power: 32.5, uptime: 99.9, source: 'demo', is_active: true, transactions: 520, alerts: 0 },
                    { address: 'qie1valoper2...bc4', name: 'Demo Validator Beta', stake_amount: 32000, voting_power: 23.1, uptime: 99.8, source: 'demo', is_active: true, transactions: 410, alerts: 1 },
                    { address: 'qie1valoper3...3ef', name: 'Demo Validator Gamma', stake_amount: 28000, voting_power: 20.2, uptime: 99.7, source: 'demo', is_active: true, transactions: 340, alerts: 0 },
                    { address: 'qie1valoper4...0d1', name: 'Demo Validator Delta', stake_amount: 15000, voting_power: 10.8, uptime: 99.5, source: 'demo', is_active: true, transactions: 150, alerts: 0 },
                    { address: 'qie1valoper5...7a2', name: 'Demo Validator Epsilon', stake_amount: 12000, voting_power: 8.7, uptime: 98.9, source: 'demo', is_active: true, transactions: 95, alerts: 0 },
                    { address: 'qie1valoper6...9c3', name: 'Demo Standby Node', stake_amount: 6500, voting_power: 4.7, uptime: 89.2, source: 'demo', is_active: false, transactions: 20, alerts: 0 },
                ]
            });
            const demoAlerts = [
                {
                    id: 901,
                    alert_id: 901,
                    tx_hash: '0x9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c',
                    severity: 'critical',
                    anomaly_score: 92.4,
                    model_confidence: 96,
                    reason: '12.4x volume spike vs. baseline; off-hours activity (early morning)',
                    message: 'Anomaly score 92.40 (critical): 12.4x volume spike vs. baseline',
                    is_resolved: false,
                    timestamp: new Date(Date.now() - 120000).toISOString()
                },
                {
                    id: 902,
                    alert_id: 902,
                    tx_hash: '0x8b4c2e1f9a0b1c2d3e4f5a6b7c8d9e0f',
                    severity: 'high',
                    anomaly_score: 74.5,
                    model_confidence: 89,
                    reason: 'unusual transaction frequency (4.2x baseline)',
                    message: 'Anomaly score 74.50 (high): unusual transaction frequency (4.2x baseline)',
                    is_resolved: false,
                    timestamp: new Date(Date.now() - 360000).toISOString()
                },
                {
                    id: 903,
                    alert_id: 903,
                    tx_hash: '0x4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a',
                    severity: 'medium',
                    anomaly_score: 48.0,
                    model_confidence: 78,
                    reason: 'elevated transaction value',
                    message: 'Anomaly score 48.00 (medium): elevated transaction value',
                    is_resolved: true,
                    timestamp: new Date(Date.now() - 900000).toISOString()
                }
            ];
            setLiveAlerts(prev => prev.length > 0 ? prev : demoAlerts.filter(a => !a.is_resolved));
            setAlertHistory(prev => prev.length > 0 ? prev : demoAlerts);
            setTransactions(prev => prev.length > 0 ? prev : [
                {
                    hash: '0x3a9f1b2c...',
                    full_hash: '0x3a9f1b2c7e8d9a0b1c2d3e4f5a6b7c8d',
                    type: 'Native Transfer',
                    timestamp: new Date().toISOString(),
                    from: 'qie1a48c9...',
                    amt: '125.50 QIE',
                    severity: 'low',
                    status: 'confirmed'
                },
                {
                    hash: '0x8b4c2e1f...',
                    full_hash: '0x8b4c2e1f9a0b1c2d3e4f5a6b7c8d9e0f',
                    type: 'Token Transfer',
                    timestamp: new Date(Date.now() - 4000).toISOString(),
                    from: 'qie17ef02...',
                    amt: '1,420.00 QIE',
                    severity: 'high',
                    status: 'pending'
                },
                {
                    hash: '0x1c2d3e4f...',
                    full_hash: '0x1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f',
                    type: 'Oracle Update',
                    timestamp: new Date(Date.now() - 9000).toISOString(),
                    from: 'qie1bc814...',
                    amt: '0 QIE',
                    severity: 'low',
                    status: 'confirmed'
                }
            ]);
            setTxTotal(3);

            const mockTxTypes = [
                'Native Transfer',
                'Token Transfer',
                'Oracle Update',
                'DEX Swap / LP',
                'Prediction Contract',
                'Smart Contract Call'
            ];

            interval = setInterval(() => {
                setNodeStatus(prev => ({ ...prev, height: (prev.height || 1245000) + 1 }));
                const mockSevList = ['low', 'low', 'low', 'medium', 'high', 'critical'];
                const mockSev = mockSevList[Math.floor(Math.random() * mockSevList.length)];
                const chosenType = mockTxTypes[Math.floor(Math.random() * mockTxTypes.length)];
                const isZeroValCall = chosenType === 'Oracle Update' || chosenType === 'Smart Contract Call';
                const amtNum = isZeroValCall ? 0 : parseFloat((Math.random() * 450 + 10).toFixed(2));
                const randomHex = Math.random().toString(16).substring(2, 10);
                const mockStatus = Math.random() < 0.25 ? 'pending' : 'confirmed';

                const newTx = {
                    hash: `0x${randomHex}...`,
                    full_hash: `0x${randomHex}${Math.random().toString(16).substring(2, 24)}`,
                    type: chosenType,
                    timestamp: new Date().toISOString(),
                    from: `qie1${Math.random().toString(36).substring(2, 7)}...`,
                    amt: amtNum === 0 ? '0 QIE' : `${amtNum.toFixed(2)} QIE`,
                    severity: mockSev,
                    status: mockStatus
                };
                setTransactions(prev => {
                    const updated = [newTx, ...prev.slice(0, 59)];
                    setTxTotal(updated.length);
                    return updated;
                });

                setDailyStats(prev => {
                    if (!prev) return prev;
                    const prevCounts = prev.severity_counts || { low: 0, medium: 0, high: 0, critical: 0 };
                    return {
                        ...prev,
                        total_transactions: (prev.total_transactions || 0) + 1,
                        severity_counts: {
                            ...prevCounts,
                            [mockSev]: (prevCounts[mockSev] || 0) + 1
                        }
                    };
                });

                if (mockSev === 'high' || mockSev === 'critical') {
                    setStats(prev => ({
                        ...prev,
                        anomalies24h: (prev.anomalies24h || 0) + 1
                    }));
                    const newAlert = {
                        id: Date.now(),
                        alert_id: Date.now(),
                        tx_hash: newTx.full_hash,
                        severity: mockSev,
                        anomaly_score: mockSev === 'critical' ? +(88 + Math.random() * 10).toFixed(1) : +(70 + Math.random() * 15).toFixed(1),
                        model_confidence: Math.floor(88 + Math.random() * 10),
                        reason: mockSev === 'critical' ? 'Volume spike detected vs baseline' : 'Unusual frequency pattern (3.8x baseline)',
                        message: `Anomaly score (${mockSev}): ${mockSev === 'critical' ? 'Volume spike detected vs baseline' : 'Unusual frequency pattern'}`,
                        is_resolved: false,
                        timestamp: new Date().toISOString()
                    };
                    setLiveAlerts(prev => [newAlert, ...prev].slice(0, 20));
                    setAlertHistory(prev => [newAlert, ...prev].slice(0, 50));
                }

                setVolumeHistory(prev => {
                    if (!prev || prev.length === 0) return prev;
                    const updated = [...prev];
                    const lastIdx = updated.length - 1;
                    updated[lastIdx] = {
                        ...updated[lastIdx],
                        count: (updated[lastIdx].count || 0) + 1,
                        volume: Math.round((updated[lastIdx].volume || 0) + amtNum)
                    };
                    return updated;
                });

                setPipelineLatency(40 + Math.floor(Math.random() * 6));

                setBridgeRoutes(prev => {
                    if (!prev || prev.length === 0) return prev;
                    const idx = Math.floor(Math.random() * prev.length);
                    const updated = [...prev];
                    updated[idx] = {
                        ...updated[idx],
                        transactions: (updated[idx].transactions || 0) + 1,
                        volume: Math.round((updated[idx].volume || 0) + amtNum),
                        flagged: (mockSev === 'high' || mockSev === 'critical') ? updated[idx].flagged + 1 : updated[idx].flagged
                    };
                    return updated;
                });
            }, 3000);
        } else {
            fetchPublicNodeStatus();

            if (walletAddress || isAuthenticated()) {
                fetchProtectedRealData();
                fetchFilteredAlerts();
            }

            interval = setInterval(() => {
                fetchPublicNodeStatus();
                if (walletAddress || isAuthenticated()) {
                    fetchProtectedRealData();
                }
            }, 5000);
        }

        return () => clearInterval(interval);
    }, [dataSource, isDemoModeEnabled, walletAddress, fetchPublicNodeStatus, fetchProtectedRealData, fetchFilteredAlerts]);

    // When alert filters change and user is on alerts tab, re-fetch
    useEffect(() => {
        if (activeSection === 'alerts' && (walletAddress || isAuthenticated())) {
            fetchFilteredAlerts();
        }
    }, [activeSection, walletAddress, fetchFilteredAlerts]);

    // WebSocket live feed
    useEffect(() => {
        if (dataSource !== 'REAL' || !(walletAddress || isAuthenticated())) return;

        const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
        let disposed = false;
        let refreshTimer = null;
        const scheduleAlertRefresh = () => {
            if (refreshTimer !== null) return;
            refreshTimer = setTimeout(() => {
                refreshTimer = null;
                if (!disposed) refreshAlertDataRef.current?.();
            }, 150);
        };
        const socket = io(API_BASE, {
            transports: ['websocket', 'polling'],
            auth: callback => callback({ token: getToken() }),
        });
        const recoverSocketAuth = async () => {
            if (disposed || !getToken()) return;
            const response = await authedFetch('/api/v1/auth/me').catch(() => null);
            if (!disposed && response?.ok) socket.connect();
        };
        socket.on('connect_error', error => {
            if (error.message === 'Connection rejected by server') recoverSocketAuth();
        });
        socket.on('disconnect', reason => {
            if (reason === 'io server disconnect') recoverSocketAuth();
        });

        socket.on('connect', () => {
            setBackendStatus('online');
        });

        socket.on('new_transaction', (tx) => {
            scheduleAlertRefresh();
            const incomingRow = {
                hash: tx.tx_hash ? `${tx.tx_hash.substring(0, 10)}...` : '—',
                full_hash: tx.tx_hash,
                type: deriveOnChainTxType(tx),
                timestamp: tx.timestamp || tx.created_at,
                from: tx.sender ? `${tx.sender.substring(0, 10)}...${tx.sender.slice(-4)}` : '—',
                amt: formatTxAmount(tx.value, tx.raw_entry, tx.asset_symbol),
                severity: tx.severity,
                raw_entry: tx.raw_entry,
                status: tx.status || 'confirmed',
            };

            if (!tx.is_update) setTxTotal(prev => prev + 1);
            setTransactions(prev => {
                // Only prepend live WebSocket transactions when viewing Page 1
                if (txPage !== 1) return prev;
                const filtered = prev.filter(item => item.full_hash !== incomingRow.full_hash);
                return [incomingRow, ...filtered].slice(0, TX_PAGE_SIZE);
            });

            const sev = (tx.severity || 'low').toLowerCase();
            const valNum = tx.asset_symbol === 'QIE' && !tx.asset_address ? (parseFloat(tx.value) || 0) : 0;

            setDailyStats(prev => {
                if (!prev || tx.is_update) return prev;
                const counts = prev.severity_counts || { low: 0, medium: 0, high: 0, critical: 0 };
                return {
                    ...prev,
                    total_transactions: (prev.total_transactions || 0) + 1,
                    severity_counts: {
                        ...counts,
                        [sev]: (counts[sev] || 0) + 1
                    }
                };
            });

            setVolumeHistory(prev => {
                if (!prev || prev.length === 0 || tx.is_update) return prev;
                const updated = [...prev];
                const lastIdx = updated.length - 1;
                updated[lastIdx] = {
                    ...updated[lastIdx],
                    count: (updated[lastIdx].count || 0) + 1,
                    volume: Math.round((updated[lastIdx].volume || 0) + valNum)
                };
                return updated;
            });

            setPipelineLatency(tx.inference_latency_ms ?? null);
        });

        socket.on('new_anomaly', (anomaly) => {
            scheduleAlertRefresh();
            setTransactions(prev => prev.map(tx => (
                tx.full_hash === anomaly.tx_hash
                    ? { ...tx, severity: anomaly.severity }
                    : tx
            )));
        });

        socket.on('new_alert', (alert) => {
            const incoming = {
                ...alert,
                id: alert.id ?? alert.alert_id,
                alert_id: alert.alert_id ?? alert.id,
                timestamp: alert.timestamp || alert.created_at,
            };
            setLiveAlerts(prev => [incoming, ...prev.filter(item => item.alert_id !== incoming.alert_id)].slice(0, 20));
            scheduleAlertRefresh();
        });

        socket.on('alert_resolved', (resolved) => {
            scheduleAlertRefresh();
            setLiveAlerts(prev => prev.filter(alert => (
                alert.id !== resolved.alert_id && alert.alert_id !== resolved.alert_id && alert.tx_hash !== resolved.tx_hash
            )));
            setAlertHistory(prev => prev.map(alert => (
                (alert.id === resolved.alert_id || alert.alert_id === resolved.alert_id)
                    ? { ...alert, is_resolved: true }
                    : alert
            )));
            setSelectedAlertIds(prev => prev.filter(id => id !== resolved.alert_id));
        });

        socket.on('node_status', (ns) => {
            setNodeStatus(prev => ({
                ...prev,
                height: ns.height ?? prev.height,
                synced: !!ns.healthy,
            }));
        });

        return () => { disposed = true; clearTimeout(refreshTimer); socket.disconnect(); };
    }, [dataSource, txPage, walletAddress]);

    const isAuthed = mounted && (dataSource === 'MOCK' || (typeof window !== 'undefined' && (!!walletAddress || isAuthenticated())));

    const severityCounts = dailyStats?.severity_counts || { low: 0, medium: 0, high: 0, critical: 0 };
    const totalSeverityDetections = (severityCounts.low || 0) + (severityCounts.medium || 0) + (severityCounts.high || 0) + (severityCounts.critical || 0);

    const severityPercentages = totalSeverityDetections > 0 ? {
        low: Math.round(((severityCounts.low || 0) / totalSeverityDetections) * 100),
        medium: Math.round(((severityCounts.medium || 0) / totalSeverityDetections) * 100),
        high: Math.round(((severityCounts.high || 0) / totalSeverityDetections) * 100),
        critical: Math.round(((severityCounts.critical || 0) / totalSeverityDetections) * 100),
    } : { low: 0, medium: 0, high: 0, critical: 0 };

    const hasTrafficVolume = volumeHistory.some(v => v.count > 0);

    useEffect(() => {
        if (dataSource !== 'MOCK') return;
        const now = Date.now();
        const open = new Set(alertHistory.filter(alert => {
            const created = parseUtcDate(alert.created_at || alert.timestamp)?.getTime();
            return !alert.is_resolved && ['medium', 'high', 'critical'].includes(alert.severity)
                && created >= now - 86400000 && created <= now;
        }).map(alert => alert.tx_hash || alert.id || alert.alert_id));
        setStats(prev => ({ ...prev, anomalies24h: open.size }));
    }, [dataSource, alertHistory]);

    // Paginated slices for Transactions (in MOCK mode), Bridge Routes, and Validators
    const totalTxPages = Math.max(1, Math.ceil((dataSource === 'MOCK' ? transactions.length : txTotal) / TX_PAGE_SIZE));
    const displayedTransactions = dataSource === 'MOCK'
        ? transactions.slice((txPage - 1) * TX_PAGE_SIZE, txPage * TX_PAGE_SIZE)
        : transactions;

    const totalBridgePages = Math.max(1, Math.ceil(bridgeRoutes.length / BRIDGE_PAGE_SIZE));
    const displayedBridgeRoutes = bridgeRoutes.slice(
        (bridgePage - 1) * BRIDGE_PAGE_SIZE,
        bridgePage * BRIDGE_PAGE_SIZE
    );

    const allValidators = validatorStats.top_validators || [];
    const totalValidatorPages = Math.max(1, Math.ceil(allValidators.length / VALIDATOR_PAGE_SIZE));
    const displayedValidators = allValidators.slice(
        (validatorPage - 1) * VALIDATOR_PAGE_SIZE,
        validatorPage * VALIDATOR_PAGE_SIZE
    );

    // Active Filtered Alerts for UI display
    const displayedAlerts = useMemo(() => {
        if (dataSource === 'REAL') return alertHistory;
        const base = alertHistory.length > 0 ? alertHistory : liveAlerts;
        return base.filter(alert => {
            if (alertFilterSeverity && (alert.severity || '').toLowerCase() !== alertFilterSeverity.toLowerCase()) {
                return false;
            }
            if (alertFilterResolved !== '') {
                const isResolved = !!alert.is_resolved;
                const wantResolved = alertFilterResolved === 'true';
                if (isResolved !== wantResolved) {
                    return false;
                }
            }
            if (alertFilterTxHash.trim()) {
                const term = alertFilterTxHash.trim().toLowerCase();
                const hash = (alert.tx_hash || alert.transaction_hash || '').toLowerCase();
                if (!hash.includes(term)) {
                    return false;
                }
            }
            if (alertFilterFrom) {
                const alertDate = parseUtcDate(alert.timestamp || alert.created_at);
                const fromDate = new Date(alertFilterFrom);
                if (alertDate && !isNaN(fromDate.getTime()) && alertDate < fromDate) {
                    return false;
                }
            }
            if (alertFilterTo) {
                const alertDate = parseUtcDate(alert.timestamp || alert.created_at);
                const toDate = new Date(alertFilterTo);
                toDate.setHours(23, 59, 59, 999);
                if (alertDate && !isNaN(toDate.getTime()) && alertDate > toDate) {
                    return false;
                }
            }
            return true;
        });
    }, [dataSource, alertHistory, liveAlerts, alertFilterSeverity, alertFilterResolved, alertFilterTxHash, alertFilterFrom, alertFilterTo]);

    const unresolvedDisplayedIds = useMemo(
        () => displayedAlerts.filter(a => !a.is_resolved && (a.id ?? a.alert_id)).map(a => a.id ?? a.alert_id),
        [displayedAlerts]
    );

    const toggleSelectAlert = (alertId) => {
        setSelectedAlertIds(prev =>
            prev.includes(alertId) ? prev.filter(id => id !== alertId) : [...prev, alertId]
        );
    };

    const toggleSelectAllUnresolved = () => {
        if (unresolvedDisplayedIds.length === 0) return;
        const allSelected = unresolvedDisplayedIds.every(id => selectedAlertIds.includes(id));
        if (allSelected) {
            setSelectedAlertIds(prev => prev.filter(id => !unresolvedDisplayedIds.includes(id)));
        } else {
            setSelectedAlertIds(prev => Array.from(new Set([...prev, ...unresolvedDisplayedIds])));
        }
    };

    return (
        <div className="flex h-screen bg-slate-900 text-slate-100 font-sans overflow-hidden">

            {/* Sidebar */}
            <motion.aside
                initial={{ x: -300 }}
                animate={{ x: sidebarOpen ? 0 : -300 }}
                className="fixed md:relative z-40 w-64 h-full bg-slate-800 border-r border-slate-700 flex flex-col transition-transform duration-300"
            >
                <div className="p-6 border-b border-slate-700 flex items-center gap-3">
                    <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-500/20">
                        <Shield className="text-white w-6 h-6" />
                    </div>
                    <h1 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">ValiGuard</h1>
                </div>

                {/* Node Status Widget */}
                <div className="mx-4 mt-6 p-4 bg-slate-700/50 rounded-xl border border-slate-600/50 backdrop-blur-sm">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">QIE Node</span>
                        <div className={`w-2 h-2 rounded-full ${nodeStatus.synced ? 'bg-green-400 animate-pulse' : 'bg-yellow-400 animate-pulse'}`}></div>
                    </div>
                    <div className="space-y-1">
                        <div className="flex justify-between text-xs">
                            <span className="text-slate-500">Height</span>
                            <span className="text-green-400 font-mono">
                                {nodeStatus.height == null ? '—' : `#${nodeStatus.height.toLocaleString()}`}
                            </span>
                        </div>
                        <div className="flex justify-between text-xs">
                            <span className="text-slate-500">Status</span>
                            <span className={nodeStatus.synced ? 'text-green-400' : 'text-yellow-400'}>
                                {nodeStatus.synced ? 'Synced' : 'Syncing...'}
                            </span>
                        </div>
                    </div>
                </div>

                {/* Navigation */}
                <nav className="flex-1 p-4 space-y-2 mt-4">
                    {[
                        { id: 'dashboard', label: 'Dashboard', icon: Activity },
                        { id: 'transactions', label: 'Transactions', icon: Globe },
                        { id: 'analytics', label: 'Analytics', icon: BarChart3 },
                        { id: 'validators', label: 'Validators', icon: CheckCircle },
                        { id: 'news', label: 'QIE News', icon: Newspaper },
                        { id: 'alerts', label: 'Alerts', icon: Bell },
                    ].map((item) => (
                        <button
                            key={item.id}
                            onClick={() => setActiveSection(item.id)}
                            className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200 ${activeSection === item.id
                                ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/20'
                                : 'text-slate-400 hover:bg-slate-700/50 hover:text-white'
                                }`}
                        >
                            <item.icon className="w-5 h-5" />
                            {item.label}
                            {activeSection === item.id && <ChevronRight className="w-4 h-4 ml-auto opacity-50" />}
                        </button>
                    ))}
                </nav>

                {/* User / Contact Section */}
                <div className="p-4 border-t border-slate-700 space-y-2">
                    <button
                        onClick={() => setActiveSection('profile')}
                        className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200 ${activeSection === 'profile' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'
                            }`}
                    >
                        <User className="w-5 h-5" />
                        UserProfile
                    </button>

                    <a href="/contact" className="w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium text-slate-400 hover:text-white transition-all">
                        <div className="w-5 h-5 flex items-center justify-center">📧</div>
                        Contact Us
                    </a>
                </div>
            </motion.aside>

            {/* Main Content */}
            <main className="flex-1 flex flex-col overflow-hidden relative">
                {/* Top Header */}
                <header className="h-16 bg-slate-800/80 backdrop-blur-md border-b border-slate-700 flex items-center justify-between px-6 z-10 sticky top-0">
                    <button onClick={() => setSidebarOpen(!sidebarOpen)} className="md:hidden text-slate-400 hover:text-white">
                        <Menu />
                    </button>

                    <div className="flex items-center gap-4 ml-auto">
                        {/* Mode Status Ticker */}
                        <div className={`flex items-center gap-2 bg-slate-900/80 border px-3 py-1.5 rounded-lg text-xs font-semibold mr-2 ${dataSource === 'MOCK'
                            ? 'border-blue-500/30 text-blue-400'
                            : 'border-emerald-500/30 text-emerald-400'
                            }`}>
                            <span className={`w-2 h-2 rounded-full animate-pulse ${dataSource === 'MOCK' ? 'bg-blue-400' : 'bg-emerald-400'
                                }`}></span>
                            {dataSource === 'MOCK' ? 'MOCK MODE' : 'REAL MODE'}
                        </div>

                        {/* Wallet Connect Button */}
                        <WalletConnect onConnect={handleWalletConnect} />

                        <button onClick={() => setActiveSection('alerts')} className="relative text-slate-400 hover:text-white transition">
                            <Bell className="w-5 h-5" />
                            {liveAlerts.length > 0 && (
                                <span className="absolute -top-1 -right-1 w-2 h-2 bg-red-500 rounded-full animate-ping" />
                            )}
                        </button>
                    </div>
                </header>

                {/* Scrollable Content */}
                <div className="flex-1 overflow-y-auto p-6 md:p-8 scroll-smooth">
                    <div className="max-w-7xl mx-auto space-y-6">

                        {/* Offline Alert Banner */}
                        {backendStatus === 'offline' && (
                            <div className="bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-xl flex items-center justify-between text-sm">
                                <div className="flex items-center gap-2">
                                    <AlertTriangle className="w-4 h-4 shrink-0" />
                                    <span>Backend unreachable — Unable to communicate with ValiGuard API. Verify the backend service is running.</span>
                                </div>
                                <button
                                    onClick={fetchPublicNodeStatus}
                                    className="text-xs bg-red-500/20 hover:bg-red-500/30 px-3 py-1 rounded text-red-300 transition-colors flex items-center gap-1"
                                >
                                    <RefreshCw className="w-3 h-3" /> Retry
                                </button>
                            </div>
                        )}

                        {/* Header Section */}
                        <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
                            <div>
                                <h2 className="text-3xl font-bold text-white capitalize">{activeSection.replace('-', ' ')}</h2>
                                <p className="text-slate-400 mt-1">Real-time validator monitoring and anomaly intelligence</p>
                            </div>
                            <div className="text-right hidden md:block">
                                <div className="text-sm text-slate-500">Pipeline status</div>
                                <div className="font-mono text-green-400 text-sm flex items-center gap-1 justify-end">
                                    <span className="w-1.5 h-1.5 rounded-full bg-green-400"></span> Live feed active
                                </div>
                            </div>
                        </div>

                        {/* Dynamic Section Rendering */}
                        <AnimatePresence mode="wait">

                            {/* DASHBOARD TAB */}
                            {activeSection === 'dashboard' && (
                                <motion.div
                                    key="dashboard"
                                    initial={{ opacity: 0, y: 20 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, y: -20 }}
                                    transition={{ duration: 0.3 }}
                                    className="space-y-6"
                                >
                                    {/* Metrics Grid */}
                                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                                        <MetricCard label="Active Bridges" value={stats.activeBridges ?? '—'} icon={Boxes} color="blue" />
                                        <MetricCard label="Open Anomalies (24h)" description="Unresolved Medium, High and Critical alerts from the last 24 hours" value={stats.anomalies24h ?? '—'} icon={AlertTriangle} color="red" />
                                        <MetricCard label="Low-risk Scored (Today)" description="Share of scored transactions below Medium risk today (UTC)" value={stats.validationRate == null ? '—' : `${stats.validationRate}%`} icon={CheckCircle} color="green" />
                                        <MetricCard label="Model Accuracy" value={stats.modelAccuracy == null ? '—' : `${stats.modelAccuracy}%`} icon={TrendingUp} color="purple" />
                                    </div>

                                    {/* Charts Area */}
                                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                                        <div className="lg:col-span-2 bg-slate-800 rounded-2xl border border-slate-700 p-6 shadow-xl">
                                            <div className="flex justify-between items-center mb-4">
                                                <h3 className="text-lg font-semibold text-white">Transaction Volume (Last 7 Days)</h3>
                                                <span className="text-xs text-slate-400 font-mono">daily-stats</span>
                                            </div>
                                            <div className="h-64 w-full">
                                                {!isAuthed ? (
                                                    <div className="h-full flex flex-col items-center justify-center text-slate-400 text-center p-4">
                                                        <Lock className="w-8 h-8 mb-2 text-slate-500" />
                                                        <p className="text-sm font-medium text-slate-300">Connect wallet to view telemetry</p>
                                                        <p className="text-xs text-slate-500 mt-1">Historical analytics endpoints require wallet authentication.</p>
                                                        <button
                                                            type="button"
                                                            onClick={() => document.getElementById('wallet-connect-button')?.click()}
                                                            className="mt-3 px-3 py-1.5 bg-gradient-to-r from-blue-600 to-purple-600 hover:opacity-90 text-white rounded-lg text-xs font-semibold shadow transition-all flex items-center gap-1.5 cursor-pointer"
                                                        >
                                                            <Wallet className="w-3.5 h-3.5" />
                                                            Connect Wallet
                                                        </button>
                                                    </div>
                                                ) : !hasTrafficVolume ? (
                                                    <div className="h-full flex flex-col items-center justify-center text-slate-500 text-center p-4">
                                                        <BarChart3 className="w-8 h-8 mb-2 opacity-30" />
                                                        <p className="text-sm font-medium">No transaction volume recorded</p>
                                                        <p className="text-xs text-slate-600 mt-1">Transaction counts will populate as transactions are validated.</p>
                                                    </div>
                                                ) : (
                                                    <Line
                                                        data={{
                                                            labels: volumeHistory.map(v => v.date),
                                                            datasets: [
                                                                {
                                                                    label: 'Transactions',
                                                                    data: volumeHistory.map(v => v.count),
                                                                    fill: true,
                                                                    backgroundColor: 'rgba(59, 130, 246, 0.2)',
                                                                    borderColor: '#3b82f6',
                                                                    tension: 0.3,
                                                                    pointRadius: 3,
                                                                    pointBackgroundColor: '#3b82f6'
                                                                }
                                                            ]
                                                        }}
                                                        options={{
                                                            responsive: true,
                                                            maintainAspectRatio: false,
                                                            plugins: {
                                                                legend: { display: false },
                                                                tooltip: { mode: 'index', intersect: false }
                                                            },
                                                            scales: {
                                                                x: {
                                                                    grid: { display: false, drawBorder: false },
                                                                    ticks: { color: '#94a3b8' }
                                                                },
                                                                y: {
                                                                    beginAtZero: true,
                                                                    grid: { color: '#334155', drawBorder: false },
                                                                    ticks: { color: '#94a3b8', precision: 0 }
                                                                }
                                                            }
                                                        }}
                                                    />
                                                )}
                                            </div>
                                        </div>

                                        <div className="bg-slate-800 rounded-2xl border border-slate-700 p-6 shadow-xl">
                                            <div className="flex justify-between items-center mb-4">
                                                <h3 className="text-lg font-semibold text-white">Risk Distribution</h3>
                                                <span className="text-xs text-slate-400 font-mono">ML Core</span>
                                            </div>
                                            <div className="h-64 flex flex-col justify-center gap-4">
                                                {!isAuthed ? (
                                                    <div className="h-full flex flex-col items-center justify-center text-slate-400 text-center p-4">
                                                        <Lock className="w-8 h-8 mb-2 text-slate-500" />
                                                        <p className="text-sm font-medium text-slate-300">Connect wallet to view risk distribution</p>
                                                        <button
                                                            type="button"
                                                            onClick={() => document.getElementById('wallet-connect-button')?.click()}
                                                            className="mt-3 px-3 py-1.5 bg-gradient-to-r from-blue-600 to-purple-600 hover:opacity-90 text-white rounded-lg text-xs font-semibold shadow transition-all flex items-center gap-1.5 cursor-pointer"
                                                        >
                                                            <Wallet className="w-3.5 h-3.5" />
                                                            Connect Wallet
                                                        </button>
                                                    </div>
                                                ) : totalSeverityDetections === 0 ? (
                                                    <div className="h-full flex flex-col items-center justify-center text-slate-500 text-center p-4">
                                                        <AlertTriangle className="w-8 h-8 mb-2 opacity-30" />
                                                        <p className="text-sm font-medium">No risk evaluations recorded</p>
                                                        <p className="text-xs text-slate-600 mt-1">Severity percentages calculate upon scoring.</p>
                                                    </div>
                                                ) : (
                                                    [
                                                        { label: 'Normal', key: 'low', color: 'bg-blue-500', pct: severityPercentages.low, count: severityCounts.low },
                                                        { label: 'Medium Risk', key: 'medium', color: 'bg-yellow-500', pct: severityPercentages.medium, count: severityCounts.medium },
                                                        { label: 'High Risk', key: 'high', color: 'bg-orange-500', pct: severityPercentages.high, count: severityCounts.high },
                                                        { label: 'Critical Risk', key: 'critical', color: 'bg-red-500', pct: severityPercentages.critical, count: severityCounts.critical },
                                                    ].map((item) => (
                                                        <div key={item.key}>
                                                            <div className="flex justify-between text-sm mb-1 text-slate-400">
                                                                <span>{item.label} ({item.count})</span>
                                                                <span className="font-mono text-slate-200">{item.pct}%</span>
                                                            </div>
                                                            <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                                                                <div
                                                                    className={`h-full rounded-full ${item.color} transition-all duration-500`}
                                                                    style={{ width: `${item.pct}%` }}
                                                                ></div>
                                                            </div>
                                                        </div>
                                                    ))
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </motion.div>
                            )}

                            {/* TRANSACTIONS TAB (15 per page with Pagination Controls) */}
                            {activeSection === 'transactions' && (
                                <motion.div
                                    key="transactions"
                                    initial={{ opacity: 0, y: 20 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, y: -20 }}
                                    className="bg-slate-800 rounded-2xl border border-slate-700 overflow-hidden shadow-xl"
                                >
                                    <div className="p-6 border-b border-slate-700 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                                        <div>
                                            <h3 className="text-xl font-bold text-white">Transactions Feed</h3>
                                            <span className="text-xs text-slate-400">
                                                Showing {displayedTransactions.length} of {dataSource === 'MOCK' ? transactions.length : txTotal} transactions (Page {txPage} of {totalTxPages})
                                            </span>
                                        </div>
                                        <span className="text-xs text-slate-400 font-mono">Live WebSockets + Paginated History</span>
                                    </div>
                                    <div className="overflow-x-auto">
                                        <table className="w-full text-left border-collapse">
                                            <thead className="bg-slate-900/50 text-slate-400 text-sm uppercase">
                                                <tr>
                                                    <th className="p-4">Tx Hash</th>
                                                    <th className="p-4">Type</th>
                                                    <th className="p-4">Age</th>
                                                    <th className="p-4">From</th>
                                                    <th className="p-4">Amount</th>
                                                    <th className="p-4">Entry</th>
                                                    <th className="p-4">Risk</th>
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-slate-700">
                                                {displayedTransactions.length === 0 ? (
                                                    <tr>
                                                        <td colSpan={7} className="p-8 text-center text-slate-400">
                                                            No transactions recorded yet. Transactions will appear in real time as processed.
                                                        </td>
                                                    </tr>
                                                ) : (
                                                    displayedTransactions.map((tx, i) => (
                                                        <tr key={tx.full_hash || i} className="hover:bg-slate-700/30 transition-colors">
                                                            <td className="p-4 font-mono text-blue-400" title={tx.full_hash}>{tx.hash}</td>
                                                            <td className="p-4">
                                                                <span className="px-2.5 py-1 rounded-md bg-slate-700/80 border border-slate-600/50 text-xs font-medium text-slate-200">
                                                                    {tx.type}
                                                                </span>
                                                            </td>
                                                            <td className="p-4 text-slate-400 font-mono text-xs">{formatTimeAgo(tx.timestamp)}</td>
                                                            <td className="p-4 font-mono text-slate-400 text-xs">{tx.from}</td>
                                                            <td className="p-4 font-medium font-mono text-sm">{tx.amt}</td>
                                                            <td className="p-4">
                                                                <div className="flex items-center gap-1.5">
                                                                    {tx.raw_entry && (
                                                                        <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-300 border border-slate-600 text-xs font-semibold">
                                                                            RAW
                                                                        </span>
                                                                    )}
                                                                    {tx.status === 'pending' && (
                                                                        <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 text-xs font-semibold animate-pulse">
                                                                            PENDING
                                                                        </span>
                                                                    )}
                                                                    {tx.status === 'failed' && (
                                                                        <span className="px-2 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30 text-xs font-semibold">
                                                                            FAILED
                                                                        </span>
                                                                    )}
                                                                    {!tx.raw_entry && tx.status !== 'pending' && tx.status !== 'failed' && (
                                                                        <span className="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-xs font-semibold">
                                                                            CONFIRMED
                                                                        </span>
                                                                    )}
                                                                </div>
                                                            </td>
                                                            <td className="p-4">
                                                                {tx.severity ? (
                                                                    <span className={`px-2 py-1 rounded text-xs font-semibold ${SEVERITY_STYLES[tx.severity]?.bg || 'bg-slate-700'} ${SEVERITY_STYLES[tx.severity]?.text || 'text-slate-300'}`}>
                                                                        {SEVERITY_STYLES[tx.severity]?.label || tx.severity}
                                                                    </span>
                                                                ) : <span className="text-slate-500">—</span>}
                                                            </td>
                                                        </tr>
                                                    ))
                                                )}
                                            </tbody>
                                        </table>
                                    </div>

                                    {/* Pagination Footer */}
                                    <PaginationControls
                                        currentPage={txPage}
                                        totalPages={totalTxPages}
                                        onPageChange={setTxPage}
                                    />
                                </motion.div>
                            )}

                            {/* VALIDATORS TAB (All Online & Offline Validators + Pagination) */}
                            {activeSection === 'validators' && (
                                <motion.div
                                    key="validators"
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="space-y-6"
                                >
                                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                                        <div>
                                            <h3 className="text-xl font-bold text-white">Network Validators</h3>
                                            {isAuthed && allValidators.length > 0 && (
                                                <p className="text-xs text-slate-400 mt-0.5">
                                                    {validatorStats.active_validators ?? 0} Active (Online) • {(validatorStats.total_validators ?? allValidators.length) - (validatorStats.active_validators ?? 0)} Standby (Offline) • Avg Uptime: {validatorStats.avg_uptime ?? 0}%
                                                </p>
                                            )}
                                        </div>
                                        <span className="text-xs text-slate-400 font-mono">/api/v1/analytics/validator-stats</span>
                                    </div>

                                    {!isAuthed ? (
                                        <div className="bg-slate-800 p-12 rounded-2xl border border-slate-700 text-center flex flex-col items-center">
                                            <Lock className="w-10 h-10 mb-3 text-slate-500" />
                                            <h4 className="text-lg font-bold text-white">Connect Wallet to View Validators</h4>
                                            <p className="text-sm text-slate-400 mt-1 max-w-md">Validator stake distribution, voting power, and RPC telemetry require authentication.</p>
                                            <button
                                                type="button"
                                                onClick={() => document.getElementById('wallet-connect-button')?.click()}
                                                className="mt-4 px-4 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:opacity-90 text-white rounded-lg text-sm font-semibold shadow transition-all flex items-center gap-2 cursor-pointer"
                                            >
                                                <Wallet className="w-4 h-4" />
                                                Connect Wallet
                                            </button>
                                        </div>
                                    ) : allValidators.length === 0 ? (
                                        <div className="bg-slate-800 p-12 rounded-2xl border border-slate-700 text-center text-slate-400">
                                            Synchronizing QIE network validators...
                                        </div>
                                    ) : (
                                        <>
                                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                                {displayedValidators.map((v, i) => (
                                                    <div key={v.address || i} className="bg-slate-800 p-6 rounded-2xl border border-slate-700 hover:border-blue-500/50 transition-all">
                                                        <div className="flex items-center justify-between mb-4">
                                                            <div className="flex items-center gap-3">
                                                                <div className="w-10 h-10 rounded-full bg-slate-700 flex items-center justify-center text-lg">
                                                                    🛡️
                                                                </div>
                                                                <div>
                                                                    <h4 className="font-bold text-white">{v.name || `Validator ${i + 1}`}</h4>
                                                                    <div className="text-xs text-slate-400 font-mono" title={v.address}>
                                                                        {(v.address || '').substring(0, 10)}...{(v.address || '').slice(-4)}
                                                                    </div>
                                                                </div>
                                                            </div>
                                                            <div className="flex items-center gap-1.5">
                                                                <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-slate-900 text-slate-300 border border-slate-700" title={`Voting power source: ${v.source}`}>
                                                                    {v.source || 'rpc'}
                                                                </span>
                                                                <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${v.is_active ? 'bg-green-500/10 text-green-400 border border-green-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'}`}>
                                                                    {v.is_active ? 'Online' : 'Offline'}
                                                                </span>
                                                            </div>
                                                        </div>
                                                        <div className="space-y-2 text-sm border-t border-slate-700/50 pt-3">
                                                            <div className="flex justify-between">
                                                                <span className="text-slate-400">Voting Power</span>
                                                                <span className="font-mono text-white">
                                                                    {v.voting_power != null ? `${v.voting_power}%` : '—'}
                                                                </span>
                                                            </div>
                                                            <div className="flex justify-between">
                                                                <span className="text-slate-400">Stake</span>
                                                                <span className="font-mono text-white">
                                                                    {v.stake_amount != null ? `${Number(v.stake_amount).toLocaleString()} QIE` : '—'}
                                                                </span>
                                                            </div>
                                                            <div className="flex justify-between">
                                                                <span className="text-slate-400">Uptime</span>
                                                                <span className={v.uptime != null && Number(v.uptime) >= 95 ? 'text-green-400 font-mono' : 'text-yellow-400 font-mono'}>
                                                                    {v.uptime != null ? `${v.uptime}%` : '—'}
                                                                </span>
                                                            </div>
                                                            <div className="flex justify-between text-xs text-slate-500 pt-1">
                                                                <span>Transactions: {v.transactions ?? 0}</span>
                                                                <span>Alerts: {v.alerts ?? 0}</span>
                                                            </div>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                            {totalValidatorPages > 1 && (
                                                <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
                                                    <PaginationControls
                                                        currentPage={validatorPage}
                                                        totalPages={totalValidatorPages}
                                                        onPageChange={setValidatorPage}
                                                    />
                                                </div>
                                            )}
                                        </>
                                    )}
                                </motion.div>
                            )}

                            {/* NEWS TAB */}
                            {activeSection === 'news' && (
                                <motion.div
                                    key="news"
                                    initial={{ opacity: 0, y: 20 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, y: -20 }}
                                    className="space-y-6"
                                >
                                    <h2 className="text-2xl font-bold flex items-center gap-2">
                                        <span className="bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-400">
                                            QIE Ecosystem Updates
                                        </span>
                                        <span className="text-2xl">📰</span>
                                    </h2>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                        {[
                                            { title: "QIE Network Node Protocol Upgrade", date: "Recent", desc: "Tendermint consensus engine optimized for high-throughput block evaluation.", tag: "Tech", content: "The QIE consensus engine incorporates real-time mempool inspection and Tendermint RPC endpoints. Validator telemetry is recorded with cryptographic block hashes." },
                                            { title: "ValiGuard AI Anomaly Pipeline Active", date: "Recent", desc: "Machine learning isolation forest model evaluates transactions in real time.", tag: "Security", content: "ValiGuard AI applies unsupervised machine learning algorithms to incoming transactions, flagging deviations in transaction volume, temporal patterns, and cross-chain routing." },
                                            { title: "Validator Telemetry and Stake Governance", date: "Recent", desc: "Voting power derives from on-chain stake and RPC validator voting weight.", tag: "Governance", content: "Network validators participate in consensus with voting power measured by stake distributions and validated block proposals." },
                                            { title: "Multi-Chain Routing Security Framework", date: "Recent", desc: "Strict address matching ensures transactions associate strictly with verified bridges.", tag: "Infrastructure", content: "ValiGuard eliminates fabricated bridge mappings, guaranteeing bridge identifiers correspond to verified smart contract addresses on the ledger." },
                                        ].map((news, i) => (
                                            <div
                                                key={i}
                                                onClick={() => setSelectedNews(news)}
                                                className="bg-slate-800 p-6 rounded-2xl border border-slate-700 hover:border-blue-500 transition-all cursor-pointer group hover:shadow-lg hover:shadow-blue-500/10"
                                            >
                                                <div className="flex justify-between items-start mb-4">
                                                    <span className="bg-blue-500/20 text-blue-400 text-xs px-2 py-1 rounded-full">{news.tag}</span>
                                                    <span className="text-slate-500 text-sm">{news.date}</span>
                                                </div>
                                                <h3 className="text-xl font-bold mb-2 group-hover:text-blue-400 transition-colors">{news.title}</h3>
                                                <p className="text-slate-400 text-sm">{news.desc}</p>
                                                <div className="mt-4 flex items-center text-blue-400 text-sm opacity-0 group-hover:opacity-100 transition-opacity font-medium">
                                                    Read Full Story <ChevronRight size={16} />
                                                </div>
                                            </div>
                                        ))}
                                    </div>

                                    <AnimatePresence>
                                        {selectedNews && (
                                            <motion.div
                                                initial={{ opacity: 0 }}
                                                animate={{ opacity: 1 }}
                                                exit={{ opacity: 0 }}
                                                className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
                                                onClick={() => setSelectedNews(null)}
                                            >
                                                <motion.div
                                                    initial={{ scale: 0.9, y: 20 }}
                                                    animate={{ scale: 1, y: 0 }}
                                                    exit={{ scale: 0.9, y: 20 }}
                                                    className="bg-slate-900 border border-slate-700 rounded-2xl max-w-2xl w-full max-h-[80vh] overflow-y-auto shadow-2xl relative"
                                                    onClick={e => e.stopPropagation()}
                                                >
                                                    <div className="h-48 bg-gradient-to-r from-blue-600 to-purple-600 relative p-8 flex flex-col justify-end">
                                                        <button
                                                            onClick={() => setSelectedNews(null)}
                                                            className="absolute top-4 right-4 bg-black/20 hover:bg-black/40 text-white p-2 rounded-full backdrop-blur-md transition-colors"
                                                        >
                                                            <X size={18} />
                                                        </button>
                                                        <span className="inline-block w-fit bg-white/20 text-white text-xs px-2 py-1 rounded-full mb-2">{selectedNews.tag}</span>
                                                        <h2 className="text-2xl font-bold text-white mb-1">{selectedNews.title}</h2>
                                                        <p className="text-white/80">{selectedNews.date}</p>
                                                    </div>
                                                    <div className="p-8 space-y-4">
                                                        <p className="text-slate-300 leading-relaxed text-base">
                                                            {selectedNews.content || selectedNews.desc}
                                                        </p>
                                                    </div>
                                                </motion.div>
                                            </motion.div>
                                        )}
                                    </AnimatePresence>
                                </motion.div>
                            )}

                            {/* ALERTS TAB & MULTI-SELECT AUDIT UI */}
                            {activeSection === 'alerts' && (
                                <motion.div
                                    key="alerts"
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="space-y-6"
                                >
                                    <div className="bg-slate-800 p-5 rounded-2xl border border-slate-700 space-y-4 shadow-xl">
                                        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-slate-700/60 pb-3">
                                            <div className="flex items-center gap-2">
                                                <Filter className="w-4 h-4 text-blue-400" />
                                                <h3 className="font-semibold text-white text-base">Alert History Audit Filters</h3>
                                            </div>
                                            <div className="flex items-center gap-3">
                                                {unresolvedDisplayedIds.length > 0 && (
                                                    <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none">
                                                        <input
                                                            type="checkbox"
                                                            checked={unresolvedDisplayedIds.length > 0 && unresolvedDisplayedIds.every(id => selectedAlertIds.includes(id))}
                                                            onChange={toggleSelectAllUnresolved}
                                                            className="w-4 h-4 rounded border-slate-600 bg-slate-900 text-blue-600 focus:ring-blue-500"
                                                        />
                                                        Select All Unresolved ({unresolvedDisplayedIds.length})
                                                    </label>
                                                )}
                                                {selectedAlertIds.length > 0 && (
                                                    <button
                                                        onClick={handleBulkResolveAlerts}
                                                        className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 shadow"
                                                    >
                                                        <CheckSquare className="w-3.5 h-3.5" />
                                                        Resolve Selected ({selectedAlertIds.length})
                                                    </button>
                                                )}
                                            </div>
                                        </div>

                                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
                                            <div>
                                                <label className="text-xs text-slate-400 block mb-1">Severity</label>
                                                <select
                                                    value={alertFilterSeverity}
                                                    onChange={e => setAlertFilterSeverity(e.target.value)}
                                                    className="w-full bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 px-3 py-2 outline-none focus:border-blue-500"
                                                >
                                                    <option value="">All Tiers</option>
                                                    <option value="critical">Critical</option>
                                                    <option value="high">High</option>
                                                    <option value="medium">Medium</option>
                                                    <option value="low">Normal</option>
                                                </select>
                                            </div>

                                            <div>
                                                <label className="text-xs text-slate-400 block mb-1">Status</label>
                                                <select
                                                    value={alertFilterResolved}
                                                    onChange={e => setAlertFilterResolved(e.target.value)}
                                                    className="w-full bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 px-3 py-2 outline-none focus:border-blue-500"
                                                >
                                                    <option value="">All Statuses</option>
                                                    <option value="false">Unresolved</option>
                                                    <option value="true">Resolved</option>
                                                </select>
                                            </div>

                                            <div>
                                                <label className="text-xs text-slate-400 block mb-1">From Date</label>
                                                <input
                                                    type="date"
                                                    value={alertFilterFrom}
                                                    onChange={e => setAlertFilterFrom(e.target.value)}
                                                    className="w-full bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 px-3 py-2 outline-none focus:border-blue-500"
                                                />
                                            </div>

                                            <div>
                                                <label className="text-xs text-slate-400 block mb-1">To Date</label>
                                                <input
                                                    type="date"
                                                    value={alertFilterTo}
                                                    onChange={e => setAlertFilterTo(e.target.value)}
                                                    className="w-full bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 px-3 py-2 outline-none focus:border-blue-500"
                                                />
                                            </div>

                                            <div>
                                                <label className="text-xs text-slate-400 block mb-1">Transaction Hash</label>
                                                <div className="relative">
                                                    <input
                                                        type="text"
                                                        value={alertFilterTxHash}
                                                        onChange={e => setAlertFilterTxHash(e.target.value)}
                                                        placeholder="0x..."
                                                        className="w-full bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 px-3 py-2 pl-8 outline-none focus:border-blue-500 font-mono"
                                                    />
                                                    <Search className="w-4 h-4 text-slate-500 absolute left-2.5 top-2.5" />
                                                </div>
                                            </div>

                                            <div className="flex items-end gap-2">
                                                <button
                                                    onClick={fetchFilteredAlerts}
                                                    className="flex-1 bg-blue-600 hover:bg-blue-500 text-white font-medium px-4 py-2 rounded-lg text-sm transition-colors flex items-center justify-center gap-1.5"
                                                >
                                                    <Filter className="w-3.5 h-3.5" /> Apply
                                                </button>
                                                <button
                                                    onClick={() => {
                                                        setAlertFilterSeverity('');
                                                        setAlertFilterResolved('');
                                                        setAlertFilterTxHash('');
                                                        setAlertFilterFrom('');
                                                        setAlertFilterTo('');
                                                        setSelectedAlertIds([]);
                                                    }}
                                                    className="bg-slate-700 hover:bg-slate-600 text-slate-300 px-3 py-2 rounded-lg text-sm transition-colors"
                                                    title="Reset filters"
                                                >
                                                    Reset
                                                </button>
                                            </div>
                                        </div>
                                    </div>

                                    {!isAuthed ? (
                                        <div className="bg-slate-800 p-8 rounded-2xl border border-slate-700 text-center flex flex-col items-center">
                                            <Lock className="w-8 h-8 mb-2 text-slate-500" />
                                            <p className="text-sm font-medium text-slate-300">Connect wallet to search and audit alert history</p>
                                            <p className="text-xs text-slate-500 mt-1">Live WebSocket alerts remain visible above; persisted database search requires authentication.</p>
                                            <button
                                                type="button"
                                                onClick={() => document.getElementById('wallet-connect-button')?.click()}
                                                className="mt-3 px-3 py-1.5 bg-gradient-to-r from-blue-600 to-purple-600 hover:opacity-90 text-white rounded-lg text-xs font-semibold shadow transition-all flex items-center gap-1.5 cursor-pointer"
                                            >
                                                <Wallet className="w-3.5 h-3.5" />
                                                Connect Wallet
                                            </button>
                                        </div>
                                    ) : alertsLoading ? (
                                        <div className="p-8 text-center text-slate-400">Loading alerts from database...</div>
                                    ) : (displayedAlerts.length === 0) ? (
                                        <div className="bg-slate-800 border border-slate-700 p-8 rounded-2xl text-center text-slate-400">
                                            No alerts match the selected criteria.
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            {displayedAlerts.map((alert, i) => {
                                                const sev = (alert.severity || 'low').toLowerCase();
                                                const style = SEVERITY_STYLES[sev] || SEVERITY_STYLES.low;
                                                const Icon = style.icon;
                                                const isResolved = !!alert.is_resolved;
                                                const alertId = alert.id ?? alert.alert_id;
                                                const isSelected = alertId ? selectedAlertIds.includes(alertId) : false;

                                                return (
                                                    <div
                                                        key={alertId || alert.tx_hash || i}
                                                        className={`${style.bg} ${style.border} border p-5 rounded-2xl flex flex-col md:flex-row md:items-center justify-between gap-4 transition-all`}
                                                    >
                                                        <div className="flex items-start gap-4">
                                                            {alertId && !isResolved && (
                                                                <input
                                                                    type="checkbox"
                                                                    checked={isSelected}
                                                                    onChange={() => toggleSelectAlert(alertId)}
                                                                    className="mt-2.5 w-4 h-4 rounded border-slate-600 bg-slate-900 text-blue-600 focus:ring-blue-500 cursor-pointer shrink-0"
                                                                />
                                                            )}
                                                            <div className="p-2 rounded-xl bg-slate-900/50 shrink-0 mt-0.5">
                                                                <Icon className={`${style.text} w-5 h-5`} />
                                                            </div>
                                                            <div>
                                                                <div className="flex items-center gap-2">
                                                                    <h4 className={`font-bold ${style.text} capitalize text-base`}>
                                                                        {style.label} Alert
                                                                    </h4>
                                                                    {isResolved ? (
                                                                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                                                            Resolved
                                                                        </span>
                                                                    ) : (
                                                                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/20 text-amber-400 border border-amber-500/30">
                                                                            Active
                                                                        </span>
                                                                    )}
                                                                </div>

                                                                <p className="text-slate-200 text-sm mt-1">{alert.message || alert.reason || 'Flagged by ML model'}</p>

                                                                {alert.reason && alert.reason !== alert.message && (
                                                                    <p className="text-xs text-slate-400 mt-1 italic">
                                                                        Reasoning: {alert.reason}
                                                                    </p>
                                                                )}

                                                                <div className="mt-2 text-xs text-slate-500 flex flex-wrap items-center gap-2">
                                                                    <span>{formatTimeAgo(alert.timestamp || alert.created_at)}</span>
                                                                    <span>•</span>
                                                                    <span className="font-mono text-slate-400">{alert.tx_hash ? `${alert.tx_hash.substring(0, 16)}...` : '—'}</span>
                                                                    <span>•</span>
                                                                    <span>Score: {alert.anomaly_score != null ? Number(alert.anomaly_score).toFixed(1) : '—'}</span>
                                                                    {alert.model_confidence != null && (
                                                                        <>
                                                                            <span>•</span>
                                                                            <span>Confidence: {alert.model_confidence}%</span>
                                                                        </>
                                                                    )}
                                                                </div>
                                                            </div>
                                                        </div>

                                                        {alertId && !isResolved && (
                                                            <div className="md:self-center shrink-0">
                                                                <button
                                                                    onClick={() => handleResolveAlert(alertId)}
                                                                    className="bg-slate-800 hover:bg-slate-700 text-emerald-400 border border-emerald-500/30 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5"
                                                                >
                                                                    <CheckCircle className="w-3.5 h-3.5" /> Mark Resolved
                                                                </button>
                                                            </div>
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                    {isAuthed && dataSource === 'REAL' && (
                                        <div className="flex items-center justify-between text-sm text-slate-300">
                                            <span>{alertTotal} alerts - Page {alertPage} of {Math.max(1, Math.ceil(alertTotal / ALERT_PAGE_SIZE))}</span>
                                            <div className="flex gap-2">
                                                <button disabled={alertsLoading || alertPage <= 1} onClick={() => { setSelectedAlertIds([]); setAlertPage(p => p - 1); }} className="px-3 py-2 rounded bg-slate-700 disabled:opacity-40">Previous</button>
                                                <button disabled={alertsLoading || alertPage * ALERT_PAGE_SIZE >= alertTotal} onClick={() => { setSelectedAlertIds([]); setAlertPage(p => p + 1); }} className="px-3 py-2 rounded bg-slate-700 disabled:opacity-40">Next</button>
                                            </div>
                                        </div>
                                    )}
                                </motion.div>
                            )}

                            {/* ANALYTICS TAB (Paginated Cross-Chain Bridge Routes — 5 per page) */}
                            {activeSection === 'analytics' && (
                                <motion.div
                                    key="analytics"
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="space-y-6"
                                >
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                            <div className="text-slate-400 text-sm mb-1">Average Anomaly Score</div>
                                            <div className="text-3xl font-bold text-white">
                                                {dailyStats?.avg_anomaly_score != null ? dailyStats.avg_anomaly_score : '—'}
                                            </div>
                                            <div className="text-xs text-slate-500 mt-2">Aggregated 24h risk mean</div>
                                        </div>

                                        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                            <div className="text-slate-400 text-sm mb-1">ML Detection Latency</div>
                                            <div className="text-3xl font-bold text-emerald-400 font-mono">
                                                {pipelineLatency == null ? 'Unavailable' : `${pipelineLatency} ms`}
                                            </div>
                                            <div className="text-xs text-slate-500 mt-2">Measured inference time; target below 100ms</div>
                                        </div>

                                        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                            <div className="text-slate-400 text-sm mb-1">Peak Observed TPS Today</div>
                                            <div className="text-3xl font-bold text-blue-400 font-mono">
                                                {peakTps == null ? 'Unavailable' : `${peakTps} TPS`}
                                            </div>
                                            <div className="text-xs text-slate-500 mt-2">Transactions per second in the stored feed</div>
                                        </div>
                                    </div>

                                    <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-xl">
                                        <div className="flex justify-between items-center mb-6">
                                            <div>
                                                <h3 className="text-lg font-bold text-white">Network Traffic Load (Last 7 Days)</h3>
                                                <p className="text-xs text-slate-400 mt-0.5">Real daily transaction counts from database</p>
                                            </div>
                                        </div>
                                        <div className="h-64 w-full">
                                            {!isAuthed ? (
                                                <div className="h-full flex flex-col items-center justify-center text-slate-400 text-center p-4">
                                                    <Lock className="w-8 h-8 mb-2 text-slate-500" />
                                                    <p className="text-sm font-medium text-slate-300">Connect wallet to view network traffic telemetry</p>
                                                    <button
                                                        type="button"
                                                        onClick={() => document.getElementById('wallet-connect-button')?.click()}
                                                        className="mt-3 px-3 py-1.5 bg-gradient-to-r from-blue-600 to-purple-600 hover:opacity-90 text-white rounded-lg text-xs font-semibold shadow transition-all flex items-center gap-1.5 cursor-pointer"
                                                    >
                                                        <Wallet className="w-3.5 h-3.5" />
                                                        Connect Wallet
                                                    </button>
                                                </div>
                                            ) : !hasTrafficVolume ? (
                                                <div className="h-full flex flex-col items-center justify-center text-slate-500 text-center p-4">
                                                    <Activity className="w-8 h-8 mb-2 opacity-30" />
                                                    <p className="text-sm font-medium">No network traffic data available</p>
                                                    <p className="text-xs text-slate-600 mt-1">Traffic telemetry will populate from validated transactions.</p>
                                                </div>
                                            ) : (
                                                <Bar
                                                    data={{
                                                        labels: volumeHistory.map(v => v.date),
                                                        datasets: [
                                                            {
                                                                label: 'Daily Transactions',
                                                                data: volumeHistory.map(v => v.count),
                                                                backgroundColor: '#8b5cf6',
                                                                borderRadius: 6,
                                                            }
                                                        ]
                                                    }}
                                                    options={{
                                                        responsive: true,
                                                        maintainAspectRatio: false,
                                                        plugins: {
                                                            legend: { display: false },
                                                            tooltip: { mode: 'index', intersect: false }
                                                        },
                                                        scales: {
                                                            x: {
                                                                grid: { display: false, drawBorder: false },
                                                                ticks: { color: '#94a3b8' }
                                                            },
                                                            y: {
                                                                beginAtZero: true,
                                                                grid: { color: '#334155', drawBorder: false },
                                                                ticks: { color: '#94a3b8', precision: 0 }
                                                            }
                                                        }
                                                    }}
                                                />
                                            )}
                                        </div>
                                    </div>

                                    {/* Cross-Chain Bridge Routes (Paginated 5 per page) */}
                                    <div className="bg-slate-800 rounded-2xl border border-slate-700 overflow-hidden">
                                        <div className="p-6 border-b border-slate-700/60 flex justify-between items-center">
                                            <div>
                                                <h3 className="text-lg font-bold text-white">Cross-Chain Bridge Routes</h3>
                                                <p className="text-xs text-slate-400 mt-0.5">
                                                    Showing {displayedBridgeRoutes.length} of {bridgeRoutes.length} active routes (Page {bridgePage} of {totalBridgePages})
                                                </p>
                                            </div>
                                            <span className="text-xs text-slate-400 font-mono">Bridge & Contract Telemetry</span>
                                        </div>
                                        {!isAuthed ? (
                                            <div className="p-6 text-center text-slate-400 text-sm">
                                                Connect wallet to view active bridge routes and liquidity volume.
                                            </div>
                                        ) : bridgeRoutes.length === 0 ? (
                                            <div className="p-6 text-center text-slate-500 text-sm">
                                                No bridge routes recorded yet. Routes will populate as cross-chain transactions are ingested.
                                            </div>
                                        ) : (
                                            <>
                                                <div className="p-6 space-y-4">
                                                    {displayedBridgeRoutes.map((route, i) => (
                                                        <div key={route.chain || i} className="flex items-center justify-between border-b border-slate-700/50 pb-3 last:border-b-0 last:pb-0">
                                                            <div className="flex items-center gap-3">
                                                                <div className={`w-3 h-3 rounded-full ${['bg-blue-500', 'bg-yellow-500', 'bg-purple-500', 'bg-emerald-500', 'bg-red-500'][i % 5]}`}></div>
                                                                <div>
                                                                    <span className="text-slate-200 font-medium">{route.chain}</span>
                                                                    <div className="text-xs text-slate-500">
                                                                        {route.transactions ?? 0} txs • {Number(route.volume || 0).toLocaleString()} QIE volume{(route.asset_volumes || []).filter(asset => asset.address || asset.symbol !== 'QIE').map(asset => ` • ${Number(asset.volume).toLocaleString()} ${asset.symbol || 'unknown asset'}`).join('')}
                                                                        {route.flagged > 0 ? ` • ${route.flagged} flagged` : ''}
                                                                    </div>
                                                                </div>
                                                            </div>
                                                            <div className="text-right">
                                                                <span className={`px-2 py-1 rounded border text-xs font-mono uppercase ${route.status === 'active'
                                                                    ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                                                                    : 'bg-slate-900 border-slate-700 text-slate-400'
                                                                    }`}>
                                                                    {route.status === 'active' ? 'Route Active' : route.status}
                                                                </span>
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                                <PaginationControls
                                                    currentPage={bridgePage}
                                                    totalPages={totalBridgePages}
                                                    onPageChange={setBridgePage}
                                                />
                                            </>
                                        )}
                                    </div>
                                </motion.div>
                            )}

                            {/* PROFILE TAB */}
                            {activeSection === 'profile' && (
                                <motion.div
                                    key="profile"
                                    initial={{ opacity: 0, scale: 0.95 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    className="max-w-3xl mx-auto"
                                >
                                    <div className="bg-slate-800 rounded-2xl border border-slate-700 overflow-hidden shadow-2xl">
                                        <div className="h-32 bg-gradient-to-r from-blue-600 to-purple-600 relative">
                                            <div className="absolute -bottom-12 left-8 w-24 h-24 rounded-full bg-slate-800 p-1">
                                                <div className="w-full h-full rounded-full bg-slate-700 flex items-center justify-center text-4xl">
                                                    🛡️
                                                </div>
                                            </div>
                                        </div>
                                        <div className="pt-16 pb-8 px-8">
                                            <h2 className="text-2xl font-bold text-white">Validator Operator</h2>
                                            <p className="text-slate-400">admin@valiguard.ai</p>
                                            <div className="flex gap-2 mt-4">
                                                <span className="px-3 py-1 rounded-full bg-green-500/10 text-green-400 text-xs border border-green-500/20">Active Validator</span>
                                                <span className="px-3 py-1 rounded-full bg-blue-500/10 text-blue-400 text-xs border border-blue-500/20">QIE Network</span>
                                            </div>

                                            <div className="mt-6 border-t border-slate-700 pt-6 space-y-3">
                                                <div className="flex justify-between text-sm">
                                                    <span className="text-slate-400">Connected Wallet</span>
                                                    <span className="font-mono text-slate-200">
                                                        {walletAddress ? `${walletAddress.substring(0, 12)}...${walletAddress.slice(-6)}` : 'Not connected'}
                                                    </span>
                                                </div>
                                                <div className="flex justify-between text-sm">
                                                    <span className="text-slate-400">Auth Token Status</span>
                                                    <span className="text-emerald-400 font-medium">
                                                        {isAuthed ? 'JWT Authenticated (UC-01)' : 'Unauthenticated'}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </motion.div>
                            )}

                        </AnimatePresence>
                    </div>
                </div>
            </main>
        </div>
    );
}

function PaginationControls({ currentPage, totalPages, onPageChange }) {
    if (totalPages <= 1) return null;

    const pages = [];
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, startPage + 4);
    for (let p = startPage; p <= endPage; p++) {
        pages.push(p);
    }

    return (
        <div className="px-6 py-4 bg-slate-900/40 border-t border-slate-700 flex items-center justify-between">
            <span className="text-xs text-slate-400">
                Page <span className="font-semibold text-white">{currentPage}</span> of <span className="font-semibold text-white">{totalPages}</span>
            </span>
            <div className="flex items-center gap-1.5">
                <button
                    onClick={() => onPageChange(Math.max(1, currentPage - 1))}
                    disabled={currentPage <= 1}
                    className="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:pointer-events-none transition-colors"
                    title="Previous Page"
                >
                    <ChevronLeft className="w-4 h-4" />
                </button>
                {pages.map(p => (
                    <button
                        key={p}
                        onClick={() => onPageChange(p)}
                        className={`px-3 py-1 rounded-lg text-xs font-semibold transition-colors ${p === currentPage
                            ? 'bg-blue-600 text-white shadow'
                            : 'bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700'
                            }`}
                    >
                        {p}
                    </button>
                ))}
                <button
                    onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
                    disabled={currentPage >= totalPages}
                    className="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:pointer-events-none transition-colors"
                    title="Next Page"
                >
                    <ChevronRight className="w-4 h-4" />
                </button>
            </div>
        </div>
    );
}

function MetricCard({ label, value, icon: Icon, color, description }) {
    const colors = {
        blue: 'text-blue-400 bg-blue-400/10',
        red: 'text-red-400 bg-red-400/10',
        green: 'text-green-400 bg-green-400/10',
        purple: 'text-purple-400 bg-purple-400/10',
    };

    return (
        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700 hover:border-slate-600 transition-all hover:translate-y-[-2px] hover:shadow-lg">
            <div className="flex justify-between items-start mb-4">
                <div>
                    <p className="text-slate-400 text-sm font-medium">{label}</p>
                    <h3 className="text-3xl font-bold text-white mt-1">{value}</h3>
                    {description && <p className="text-xs text-slate-400 mt-2">{description}</p>}
                </div>
                <div className={`p-3 rounded-xl ${colors[color]}`}>
                    <Icon className="w-6 h-6" />
                </div>
            </div>
            <div className="w-full bg-slate-700 h-1.5 rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${color === 'red' ? 'bg-red-500' : 'bg-blue-500'} w-[70%]`}></div>
            </div>
        </div>
    );
}