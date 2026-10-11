"use client";

import { useState, useEffect, useCallback } from 'react';
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
    TrendingUp,
    Boxes,
    Newspaper,
    Filter,
    Search,
    RefreshCw,
    X,
    Lock
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

import WalletConnect from '../components/WalletConnect';
import { authedFetch, isAuthenticated } from '../lib/api';
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
    low: { bg: 'bg-blue-500/10', border: 'border-blue-500/50', text: 'text-blue-400', icon: CheckCircle, label: 'Low' },
};

function formatTimeAgo(timestamp) {
    if (!timestamp) return '—';
    const parsed = new Date(timestamp);
    if (Number.isNaN(parsed.getTime())) return '—';

    const seconds = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
}

export default function Dashboard() {
    const isDemoModeEnabled = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

    const [activeSection, setActiveSection] = useState('dashboard');
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [selectedNetwork, setSelectedNetwork] = useState('qie');
    const [selectedNews, setSelectedNews] = useState(null);

    // Feature Toggle: REAL is the default. MOCK survives ONLY behind NEXT_PUBLIC_DEMO_MODE=true.
    const [dataSource, setDataSource] = useState(
        isDemoModeEnabled ? 'MOCK' : 'REAL'
    );
    const [walletAddress, setWalletAddress] = useState(null);
    const [backendStatus, setBackendStatus] = useState('unknown'); // 'online', 'offline', 'unknown'

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
    const [validatorStats, setValidatorStats] = useState({
        total_validators: null,
        active_validators: null,
        avg_uptime: null,
        top_validators: []
    });

    // Live WebSocket & Transaction State
    const [liveAlerts, setLiveAlerts] = useState([]);
    const [transactions, setTransactions] = useState([]);
    const [, setAgeTick] = useState(Date.now());

    // Alerts Tab Search & History
    const [alertHistory, setAlertHistory] = useState([]);
    const [alertFilterSeverity, setAlertFilterSeverity] = useState('');
    const [alertFilterResolved, setAlertFilterResolved] = useState('');
    const [alertFilterTxHash, setAlertFilterTxHash] = useState('');
    const [alertFilterFrom, setAlertFilterFrom] = useState('');
    const [alertFilterTo, setAlertFilterTo] = useState('');
    const [alertsLoading, setAlertsLoading] = useState(false);

    useEffect(() => {
        const interval = setInterval(() => setAgeTick(Date.now()), 1000);
        return () => clearInterval(interval);
    }, []);

    const handleWalletConnect = (address) => {
        setWalletAddress(address);
    };

    // Open endpoint node status fetch (public, no auth needed)
    const fetchPublicNodeStatus = useCallback(async () => {
        try {
            const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
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
                setBackendStatus('offline');
            }
        } catch (error) {
            console.warn("Public node status unavailable:", error);
            setBackendStatus('offline');
        }
    }, []);

    // Authenticated data fetcher (runs only when wallet is connected)
    const fetchProtectedRealData = useCallback(async () => {
        const authed = typeof window !== 'undefined' && (!!walletAddress || isAuthenticated());
        if (!authed) return;

        try {
            setBackendStatus('online');

            // 1. Fetch Daily Stats
            const statsRes = await authedFetch('/api/v1/analytics/daily-stats');
            if (statsRes.ok) {
                const statsData = await statsRes.json();
                if (statsData.success) {
                    setDailyStats(statsData.data);
                    setStats(prev => ({
                        ...prev,
                        anomalies24h: statsData.data.anomalies_detected ?? prev.anomalies24h,
                        validationRate: statsData.data.validation_success_rate ?? null
                    }));
                }
            }

            // 2. Fetch Model Accuracy
            const modelRes = await authedFetch('/api/v1/analytics/model-accuracy');
            if (modelRes.ok) {
                const modelData = await modelRes.json();
                if (modelData.success) {
                    setStats(prev => ({
                        ...prev,
                        modelAccuracy: modelData.data.accuracy ?? null,
                    }));
                }
            }

            // 3. Fetch Validator Stats
            const valRes = await authedFetch('/api/v1/analytics/validator-stats');
            if (valRes.ok) {
                const valData = await valRes.json();
                if (valData.success) {
                    setValidatorStats(valData.data);
                    setStats(prev => ({
                        ...prev,
                        activeBridges: valData.data.active_validators ?? prev.activeBridges
                    }));
                }
            }

            // 4. Fetch Transaction History
            const histRes = await authedFetch('/api/v1/bridge/history?limit=15');
            if (histRes.ok) {
                const histData = await histRes.json();
                if (histData.success && Array.isArray(histData.data.transactions)) {
                    const mappedTxs = histData.data.transactions.map(tx => {
                        const txHash = tx.tx_hash || tx.transaction_hash || '';
                        const value = tx.value ?? tx.amount;
                        return {
                            hash: txHash ? `${txHash.substring(0, 10)}...` : '—',
                            full_hash: txHash,
                            type: 'BridgeValidation',
                            timestamp: tx.timestamp || tx.created_at,
                            from: tx.sender || '—',
                            amt: value == null ? '—' : `${value} QIE`,
                            severity: tx.severity,
                            raw_entry: tx.raw_entry,
                            status: tx.status
                        };
                    });
                    setTransactions(mappedTxs);
                }
            }

            // 5. Fetch Volume History for Traffic Chart (last 7 days)
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
                    count: (res.success && res.data?.total_transactions) ? res.data.total_transactions : 0
                };
            });
            setVolumeHistory(history);

        } catch (error) {
            console.error("Protected telemetry fetch error:", error);
            setBackendStatus('offline');
        }
    }, [walletAddress]);

    // Fetch Alerts with filter criteria
    const fetchFilteredAlerts = useCallback(async () => {
        const authed = typeof window !== 'undefined' && (!!walletAddress || isAuthenticated());
        if (!authed) return;

        setAlertsLoading(true);
        try {
            const params = new URLSearchParams();
            if (alertFilterSeverity) params.set('severity', alertFilterSeverity);
            if (alertFilterResolved) params.set('resolved', alertFilterResolved);
            if (alertFilterTxHash.trim()) params.set('tx_hash', alertFilterTxHash.trim());
            if (alertFilterFrom) params.set('from', alertFilterFrom);
            if (alertFilterTo) params.set('to', alertFilterTo);
            params.set('limit', '50');

            const res = await authedFetch(`/api/v1/alerts?${params.toString()}`);
            if (res.ok) {
                const data = await res.json();
                if (data.success && Array.isArray(data.data.items)) {
                    setAlertHistory(data.data.items);
                }
            }
        } catch (error) {
            console.error("Failed to query alerts:", error);
        } finally {
            setAlertsLoading(false);
        }
    }, [walletAddress, alertFilterSeverity, alertFilterResolved, alertFilterTxHash, alertFilterFrom, alertFilterTo]);

    // Handle Alert Resolution
    const handleResolveAlert = async (alertId) => {
        try {
            const res = await authedFetch(`/api/v1/alerts/${alertId}/resolve`, { method: 'PATCH' });
            if (res.ok) {
                setLiveAlerts(prev => prev.map(a => a.id === alertId ? { ...a, is_resolved: true } : a));
                setAlertHistory(prev => prev.map(a => a.id === alertId ? { ...a, is_resolved: true } : a));
            }
        } catch (err) {
            console.error("Failed to resolve alert:", err);
        }
    };

    // Periodic Polling Effect
    useEffect(() => {
        let interval;

        if (dataSource === 'MOCK' && isDemoModeEnabled) {
            // Deterministic Demo Simulation (deterministic tick)
            setBackendStatus('online');
            setNodeStatus({
                synced: true,
                height: 1245032,
                moniker: 'ValiGuard AI Validator (demo)',
                network: 'demo'
            });
            setStats({
                activeBridges: 4,
                anomalies24h: 1,
                validationRate: 98.5,
                modelAccuracy: 94.2
            });
            let tick = 0;
            interval = setInterval(() => {
                tick += 1;
                setNodeStatus(prev => ({ ...prev, height: (prev.height || 1245000) + 1 }));
            }, 3000);
        } else {
            // REAL Mode: always fetch open node status
            fetchPublicNodeStatus();

            // If authenticated, poll protected endpoints
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

    // WebSocket live feed (REAL data source: open by design, stays active pre-auth)
    useEffect(() => {
        if (dataSource !== 'REAL') return;

        const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
        const socket = io(API_BASE, { transports: ['websocket', 'polling'] });

        socket.on('connect', () => {
            setBackendStatus('online');
        });
        socket.on('disconnect', () => {
            // socket disconnected
        });

        socket.on('new_transaction', (tx) => {
            setTransactions(prev => [{
                hash: tx.tx_hash ? `${tx.tx_hash.substring(0, 10)}...` : '—',
                full_hash: tx.tx_hash,
                type: 'BridgeValidation',
                timestamp: tx.timestamp || tx.created_at,
                from: tx.sender || '—',
                amt: tx.value == null ? '—' : `${tx.value} QIE`,
                severity: tx.severity,
                raw_entry: tx.raw_entry,
                status: tx.status,
            }, ...prev.slice(0, 14)]);
        });

        socket.on('new_anomaly', (anomaly) => {
            setStats(prev => ({ ...prev, anomalies24h: (prev.anomalies24h || 0) + 1 }));
            setTransactions(prev => prev.map(tx => (
                tx.full_hash === anomaly.tx_hash
                    ? { ...tx, severity: anomaly.severity }
                    : tx
            )));
        });

        socket.on('new_alert', (alert) => {
            setLiveAlerts(prev => [{
                ...alert,
                timestamp: alert.timestamp || alert.created_at,
            }, ...prev].slice(0, 20));
        });

        socket.on('alert_resolved', (resolved) => {
            setLiveAlerts(prev => prev.filter(alert => (
                alert.id !== resolved.alert_id && alert.tx_hash !== resolved.tx_hash
            )));
            setAlertHistory(prev => prev.map(alert => (
                alert.id === resolved.alert_id ? { ...alert, is_resolved: true } : alert
            )));
        });

        socket.on('node_status', (ns) => {
            setNodeStatus(prev => ({
                ...prev,
                height: ns.height ?? prev.height,
                synced: !!ns.healthy,
            }));
        });

        return () => socket.disconnect();
    }, [dataSource]);

    // Honest Derived Metrics
    const isAuthed = typeof window !== 'undefined' && (!!walletAddress || isAuthenticated());
    const totalTransactions24h = dailyStats?.total_transactions ?? null;
    const derivedTps = (typeof totalTransactions24h === 'number' && totalTransactions24h > 0)
        ? (totalTransactions24h / 86400).toFixed(4)
        : '—';

    // Real Severity Distribution Computations
    const severityCounts = dailyStats?.severity_counts || { low: 0, medium: 0, high: 0, critical: 0 };
    const totalSeverityDetections = (severityCounts.low || 0) + (severityCounts.medium || 0) + (severityCounts.high || 0) + (severityCounts.critical || 0);

    const severityPercentages = totalSeverityDetections > 0 ? {
        low: Math.round(((severityCounts.low || 0) / totalSeverityDetections) * 100),
        medium: Math.round(((severityCounts.medium || 0) / totalSeverityDetections) * 100),
        high: Math.round(((severityCounts.high || 0) / totalSeverityDetections) * 100),
        critical: Math.round(((severityCounts.critical || 0) / totalSeverityDetections) * 100),
    } : { low: 0, medium: 0, high: 0, critical: 0 };

    const hasTrafficVolume = volumeHistory.some(v => v.count > 0);

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
                        {/* Data Source Display */}
                        {isDemoModeEnabled ? (
                            <div className="flex items-center bg-slate-900 rounded-lg p-1 border border-slate-700 mr-2">
                                <button
                                    onClick={() => setDataSource('MOCK')}
                                    className={`px-3 py-1 rounded-md text-xs font-bold transition-all ${dataSource === 'MOCK' ? 'bg-blue-600 text-white shadow' : 'text-slate-500 hover:text-slate-300'}`}
                                >
                                    MOCK
                                </button>
                                <button
                                    onClick={() => setDataSource('REAL')}
                                    className={`px-3 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-2 ${dataSource === 'REAL' ? 'bg-green-600 text-white shadow' : 'text-slate-500 hover:text-slate-300'}`}
                                >
                                    REAL
                                </button>
                            </div>
                        ) : (
                            <div className="flex items-center gap-2 bg-slate-900/80 border border-emerald-500/30 px-3 py-1.5 rounded-lg text-xs font-semibold text-emerald-400 mr-2">
                                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                                REAL MODE
                            </div>
                        )}

                        {/* Wallet Connect Button */}
                        <WalletConnect onConnect={handleWalletConnect} />

                        <div className="hidden md:flex items-center bg-slate-900 rounded-lg p-1 border border-slate-700">
                            {['qie', 'qie-testnet', 'eth'].map(net => (
                                <button
                                    key={net}
                                    onClick={() => setSelectedNetwork(net)}
                                    className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${selectedNetwork === net ? 'bg-slate-700 text-white shadow' : 'text-slate-500 hover:text-slate-300'
                                        }`}
                                >
                                    {net.toUpperCase()}
                                </button>
                            ))}
                        </div>

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
                                        <MetricCard label="Anomalies (24h)" value={stats.anomalies24h ?? '—'} icon={AlertTriangle} color="red" />
                                        <MetricCard label="Validation Rate" value={stats.validationRate == null ? '—' : `${stats.validationRate}%`} icon={CheckCircle} color="green" />
                                        <MetricCard label="Model Accuracy" value={stats.modelAccuracy == null ? '—' : `${stats.modelAccuracy}%`} icon={TrendingUp} color="purple" />
                                    </div>

                                    {/* Charts Area */}
                                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                                        {/* 1. Transaction Volume Chart (backed by /api/v1/analytics/daily-stats) */}
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

                                        {/* 2. Real Risk Distribution (computed from daily-stats severity_counts) */}
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
                                                    </div>
                                                ) : totalSeverityDetections === 0 ? (
                                                    <div className="h-full flex flex-col items-center justify-center text-slate-500 text-center p-4">
                                                        <AlertTriangle className="w-8 h-8 mb-2 opacity-30" />
                                                        <p className="text-sm font-medium">No risk evaluations recorded</p>
                                                        <p className="text-xs text-slate-600 mt-1">Severity percentages calculate upon scoring.</p>
                                                    </div>
                                                ) : (
                                                    [
                                                        { label: 'Low Risk', key: 'low', color: 'bg-blue-500', pct: severityPercentages.low, count: severityCounts.low },
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

                            {/* TRANSACTIONS TAB */}
                            {activeSection === 'transactions' && (
                                <motion.div
                                    key="transactions"
                                    initial={{ opacity: 0, y: 20 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, y: -20 }}
                                    className="bg-slate-800 rounded-2xl border border-slate-700 overflow-hidden shadow-xl"
                                >
                                    <div className="p-6 border-b border-slate-700 flex justify-between items-center">
                                        <h3 className="text-xl font-bold text-white">Transactions Feed</h3>
                                        <span className="text-xs text-slate-400">Live WebSockets + History</span>
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
                                                {transactions.length === 0 ? (
                                                    <tr>
                                                        <td colSpan={7} className="p-8 text-center text-slate-400">
                                                            No transactions recorded yet. Transactions will appear in real time as processed.
                                                        </td>
                                                    </tr>
                                                ) : (
                                                    transactions.map((tx, i) => (
                                                        <tr key={tx.full_hash || i} className="hover:bg-slate-700/30 transition-colors">
                                                            <td className="p-4 font-mono text-blue-400">{tx.hash}</td>
                                                            <td className="p-4"><span className="px-2 py-1 rounded bg-slate-700 text-xs">{tx.type}</span></td>
                                                            <td className="p-4 text-slate-400">{formatTimeAgo(tx.timestamp)}</td>
                                                            <td className="p-4 font-mono text-slate-400">{tx.from}</td>
                                                            <td className="p-4 font-medium">{tx.amt}</td>
                                                            <td className="p-4">
                                                                <div className="flex items-center gap-1">
                                                                    {tx.raw_entry && (
                                                                        <span className="px-2 py-1 rounded bg-slate-700 text-slate-300 text-xs font-semibold">RAW</span>
                                                                    )}
                                                                    {tx.status === 'pending' && (
                                                                        <span className="px-2 py-1 rounded bg-amber-500/20 text-amber-400 text-xs font-semibold animate-pulse">PENDING</span>
                                                                    )}
                                                                    {!tx.raw_entry && tx.status !== 'pending' && (
                                                                        <span className="text-slate-500">—</span>
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
                                </motion.div>
                            )}

                            {/* VALIDATORS TAB (backed by /api/v1/analytics/validator-stats) */}
                            {activeSection === 'validators' && (
                                <motion.div
                                    key="validators"
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="space-y-6"
                                >
                                    <div className="flex justify-between items-center">
                                        <h3 className="text-xl font-bold text-white">Network Validators</h3>
                                        <span className="text-xs text-slate-400 font-mono">/api/v1/analytics/validator-stats</span>
                                    </div>

                                    {!isAuthed ? (
                                        <div className="bg-slate-800 p-12 rounded-2xl border border-slate-700 text-center flex flex-col items-center">
                                            <Lock className="w-10 h-10 mb-3 text-slate-500" />
                                            <h4 className="text-lg font-bold text-white">Connect Wallet to View Validators</h4>
                                            <p className="text-sm text-slate-400 mt-1 max-w-md">Validator stake distribution, voting power, and RPC telemetry require authentication.</p>
                                        </div>
                                    ) : (!validatorStats.top_validators || validatorStats.top_validators.length === 0) ? (
                                        <div className="bg-slate-800 p-12 rounded-2xl border border-slate-700 text-center text-slate-400">
                                            No validators found in the database.
                                        </div>
                                    ) : (
                                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                            {validatorStats.top_validators.map((v, i) => (
                                                <div key={v.address || i} className="bg-slate-800 p-6 rounded-2xl border border-slate-700 hover:border-blue-500/50 transition-all">
                                                    <div className="flex items-center justify-between mb-4">
                                                        <div className="flex items-center gap-3">
                                                            <div className="w-10 h-10 rounded-full bg-slate-700 flex items-center justify-center text-lg">
                                                                🛡️
                                                            </div>
                                                            <div>
                                                                <h4 className="font-bold text-white">{v.name || `Validator ${i + 1}`}</h4>
                                                                <div className="text-xs text-slate-400 font-mono">
                                                                    {(v.address || '').substring(0, 10)}...{(v.address || '').slice(-4)}
                                                                </div>
                                                            </div>
                                                        </div>
                                                        <div className="flex items-center gap-1.5">
                                                            {/* Honesty badge for voting power source (rpc | db) */}
                                                            <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-slate-900 text-slate-300 border border-slate-700" title={`Voting power source: ${v.source}`}>
                                                                {v.source || 'db'}
                                                            </span>
                                                            <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${v.is_active ? 'bg-green-500/10 text-green-400 border border-green-500/20' : 'bg-slate-700 text-slate-400'}`}>
                                                                {v.is_active ? 'Active' : 'Inactive'}
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
                                                            <span className={v.uptime != null && v.uptime >= 95 ? 'text-green-400 font-mono' : 'text-yellow-400 font-mono'}>
                                                                {v.uptime != null ? `${v.uptime}%` : '—'}
                                                            </span>
                                                        </div>
                                                        <div className="flex justify-between text-xs text-slate-500 pt-1">
                                                            <span>Transactions: {v.transactions ?? '—'}</span>
                                                            <span>Alerts: {v.alerts ?? '—'}</span>
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
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
                                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-400">
                                        QIE Ecosystem Updates 📰
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

                                    {/* News Modal */}
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

                            {/* ALERTS TAB & AUDIT SEARCH UI (Step 9) */}
                            {activeSection === 'alerts' && (
                                <motion.div
                                    key="alerts"
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="space-y-6"
                                >
                                    {/* Alert Filter Toolbar backed by /api/v1/alerts */}
                                    <div className="bg-slate-800 p-5 rounded-2xl border border-slate-700 space-y-4 shadow-xl">
                                        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-slate-700/60 pb-3">
                                            <div className="flex items-center gap-2">
                                                <Filter className="w-4 h-4 text-blue-400" />
                                                <h3 className="font-semibold text-white text-base">Alert History Audit Filters</h3>
                                            </div>
                                            <span className="text-xs text-slate-400 font-mono">GET /api/v1/alerts</span>
                                        </div>

                                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
                                            {/* Severity Filter */}
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
                                                    <option value="low">Low</option>
                                                </select>
                                            </div>

                                            {/* Resolution Filter */}
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

                                            {/* Tx Hash Filter */}
                                            <div className="lg:col-span-2">
                                                <label className="text-xs text-slate-400 block mb-1">Transaction Hash</label>
                                                <div className="relative">
                                                    <input
                                                        type="text"
                                                        value={alertFilterTxHash}
                                                        onChange={e => setAlertFilterTxHash(e.target.value)}
                                                        placeholder="Filter by tx hash..."
                                                        className="w-full bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 px-3 py-2 pl-8 outline-none focus:border-blue-500 font-mono"
                                                    />
                                                    <Search className="w-4 h-4 text-slate-500 absolute left-2.5 top-2.5" />
                                                </div>
                                            </div>

                                            {/* Filter Actions */}
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
                                                    }}
                                                    className="bg-slate-700 hover:bg-slate-600 text-slate-300 px-3 py-2 rounded-lg text-sm transition-colors"
                                                    title="Reset filters"
                                                >
                                                    Reset
                                                </button>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Alert Items List */}
                                    {!isAuthed ? (
                                        <div className="bg-slate-800 p-8 rounded-2xl border border-slate-700 text-center flex flex-col items-center">
                                            <Lock className="w-8 h-8 mb-2 text-slate-500" />
                                            <p className="text-sm font-medium text-slate-300">Connect wallet to search and audit alert history</p>
                                            <p className="text-xs text-slate-500 mt-1">Live WebSocket alerts remain visible above; persisted database search requires authentication.</p>
                                        </div>
                                    ) : alertsLoading ? (
                                        <div className="p-8 text-center text-slate-400">Loading alerts from database...</div>
                                    ) : (alertHistory.length === 0 && liveAlerts.length === 0) ? (
                                        <div className="bg-slate-800 border border-slate-700 p-8 rounded-2xl text-center text-slate-400">
                                            No alerts match the selected criteria.
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            {(alertHistory.length > 0 ? alertHistory : liveAlerts).map((alert, i) => {
                                                const sev = (alert.severity || 'low').toLowerCase();
                                                const style = SEVERITY_STYLES[sev] || SEVERITY_STYLES.low;
                                                const Icon = style.icon;
                                                const isResolved = !!alert.is_resolved;

                                                return (
                                                    <div
                                                        key={alert.id || alert.tx_hash || i}
                                                        className={`${style.bg} ${style.border} border p-5 rounded-2xl flex flex-col md:flex-row md:items-center justify-between gap-4 transition-all`}
                                                    >
                                                        <div className="flex items-start gap-4">
                                                            <div className={`p-2 rounded-xl bg-slate-900/50 shrink-0 mt-0.5`}>
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

                                                                {/* Reasoning Display (page.js:827-834 contract preserved) */}
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

                                                        {/* Resolution Button */}
                                                        {alert.id && !isResolved && (
                                                            <div className="md:self-center shrink-0">
                                                                <button
                                                                    onClick={() => handleResolveAlert(alert.id)}
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
                                </motion.div>
                            )}

                            {/* ANALYTICS TAB */}
                            {activeSection === 'analytics' && (
                                <motion.div
                                    key="analytics"
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="space-y-6"
                                >
                                    {/* Analytics Summary Cards (Honest Real Metrics) */}
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                            <div className="text-slate-400 text-sm mb-1">Average Anomaly Score</div>
                                            <div className="text-3xl font-bold text-white">
                                                {dailyStats?.avg_anomaly_score != null ? dailyStats.avg_anomaly_score : '—'}
                                            </div>
                                            <div className="text-xs text-slate-500 mt-2">Aggregated 24h risk mean</div>
                                        </div>

                                        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                            <div className="text-slate-400 text-sm mb-1">Derived 24h TPS</div>
                                            <div className="text-3xl font-bold text-white">
                                                {derivedTps}
                                            </div>
                                            <div className="text-xs text-slate-500 mt-2">Computed as: total_transactions / 86400</div>
                                        </div>

                                        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                            <div className="text-slate-400 text-sm mb-1">Total Daily Transactions</div>
                                            <div className="text-3xl font-bold text-white">
                                                {dailyStats?.total_transactions != null ? dailyStats.total_transactions : '—'}
                                            </div>
                                            <div className="text-xs text-slate-500 mt-2">Committed ledger transactions</div>
                                        </div>
                                    </div>

                                    {/* Main Network Traffic Chart (Derivation from daily-stats, never random) */}
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

                                    {/* Cross-Chain Bridge Breakdown */}
                                    <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                        <h3 className="text-lg font-bold mb-4 text-white">Cross-Chain Bridge Routes</h3>
                                        <div className="space-y-4">
                                            {['Ethereum', 'BSC', 'Polygon', 'Avalanche'].map((chain, i) => (
                                                <div key={chain} className="flex items-center justify-between border-b border-slate-700/50 pb-3">
                                                    <div className="flex items-center gap-3">
                                                        <div className={`w-3 h-3 rounded-full ${['bg-blue-500', 'bg-yellow-500', 'bg-purple-500', 'bg-red-500'][i]}`}></div>
                                                        <span className="text-slate-300 font-medium">{chain}</span>
                                                    </div>
                                                    <div className="text-right">
                                                        <span className="px-2 py-1 rounded bg-slate-900 border border-slate-700 text-xs font-mono text-slate-300">
                                                            Route Active
                                                        </span>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
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

function MetricCard({ label, value, icon: Icon, color }) {
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
