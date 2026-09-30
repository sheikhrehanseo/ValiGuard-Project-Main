
"use client";

import { useState, useEffect } from 'react';
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
    MessageSquare,
    Send,
    Newspaper
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

import WalletConnect from '../components/WalletConnect';
import { authedFetch } from '../lib/api';
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

export default function Dashboard() {
    const [activeSection, setActiveSection] = useState('dashboard');
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [selectedNetwork, setSelectedNetwork] = useState('qie');

    // AI Chat State
    const [isChatOpen, setIsChatOpen] = useState(false);
    const [chatInput, setChatInput] = useState('');
    const [chatMessages, setChatMessages] = useState([
        { role: 'ai', text: 'Hello! I am QIE-GPT. I am monitoring the Validator Node and Network Health. Ask me anything!' }
    ]);

    // UI States for Enhancements
    const [trafficRange, setTrafficRange] = useState('24h');
    const [selectedNews, setSelectedNews] = useState(null);

    // Feature Toggle States
    // Feature Toggle States
    const [dataSource, setDataSource] = useState('MOCK'); // 'MOCK' or 'REAL'
    const [walletAddress, setWalletAddress] = useState(null);
    const [backendStatus, setBackendStatus] = useState('unknown'); // 'online', 'offline', 'unknown'

    // Validator State
    const [stats, setStats] = useState({
        activeBridges: 12,
        anomalies24h: 0,
        validationRate: 99.9,
        modelAccuracy: 98.5
    });

    const [nodeStatus, setNodeStatus] = useState({
        synced: true,
        height: 1245032,
        moniker: 'ValiGuard AI Validator',
        network: 'qie-testnet-3'
    });

    // Live WebSocket state (REAL data source)
    const [liveAlerts, setLiveAlerts] = useState([]);
    const [socketStatus, setSocketStatus] = useState('disconnected');

    const [transactions, setTransactions] = useState([
        { hash: "0x7a8b...9c2d", type: "MsgSend", time: "2s ago", from: "qie1...9k2l", amt: "1,500 QIE" },
        { hash: "0x7a8b...9c2d", type: "MsgSend", time: "2s ago", from: "qie1...9k2l", amt: "1,500 QIE" },
        { hash: "0xe3f1...5a8b", type: "MsgDelegate", time: "12s ago", from: "qie1...p4m9", amt: "50,000 QIE" },
        { hash: "0x9c2d...1e4f", type: "MsgVote", time: "45s ago", from: "qie1...x8r2", amt: "-" },
        { hash: "0x4f1a...3b9d", type: "MsgSend", time: "1m ago", from: "qie1...v3n7", amt: "250 QIE" },
        { hash: "0x1e2f...8c4a", type: "MsgWithdraw", time: "2m ago", from: "qie1...k9l2", amt: "12.5 QIE" },
    ]);

    // Wallet Connected Callback
    const handleWalletConnect = (address) => {
        setWalletAddress(address);
    };

    // Real Data Fetching Logic (authenticated via authedFetch — Bearer JWT)
    const fetchRealData = async () => {
        try {
            // Fetch Node Status
            const statusRes = await authedFetch('/api/v1/qie/node/status');
            const statusData = await statusRes.json();

            setBackendStatus('online'); // Connection success

            if (statusData.success) {
                setNodeStatus(prev => ({
                    ...prev,
                    height: statusData.data.node.height || prev.height,
                    synced: statusData.data.node.healthy
                }));
            }

            // Fetch Analytics / Daily Stats (requires auth — 401 falls through)
            const statsRes = await authedFetch('/api/v1/analytics/daily-stats');
            const statsData = await statsRes.json();
            if (statsData.success) {
                setStats(prev => ({
                    ...prev,
                    anomalies24h: statsData.data.anomalies_detected ?? prev.anomalies24h,
                    // validation_success_rate is null on an empty day — keep the previous display value
                    validationRate: statsData.data.validation_success_rate ?? prev.validationRate
                }));
            }

            // Fetch History (Transactions)
            const histRes = await authedFetch('/api/v1/bridge/history?limit=10');
            const histData = await histRes.json();
            if (histData.success) {
                if (histData.data.transactions.length > 0) {
                    const mappedTxs = histData.data.transactions.map(tx => {
                        const txHash = tx.tx_hash || tx.transaction_hash || '';
                        const value = tx.value ?? tx.amount;
                        return {
                        hash: txHash.substring(0, 10) + "...",
                        type: "BridgeValidation",
                        time: "Just now",
                        from: tx.sender ?? "—",
                        amt: value == null ? "—" : value + " Token",
                        severity: tx.severity,
                        raw_entry: tx.raw_entry
                        };
                    });
                    setTransactions(mappedTxs);
                } else {
                    // Keep empty or show 'No Data'
                }
            }

        } catch (error) {
            console.error("Failed to fetch real data:", error);
            setBackendStatus('offline'); // Connection failed
        }
    };

    // Effect for Data Updates (Mock vs Real)
    useEffect(() => {
        let interval;

        if (dataSource === 'MOCK') {
            // Reset to Mock Data if switching back
            setBackendStatus('unknown');
            // --- MOCK LOGIC ---
            interval = setInterval(() => {
                setNodeStatus(prev => ({ ...prev, height: prev.height + 1 }));

                // Add new Transaction
                const newTx = {
                    hash: "0x" + Math.random().toString(16).substr(2, 8) + "..." + Math.random().toString(16).substr(2, 4),
                    type: ["MsgSend", "MsgDelegate", "MsgVote", "MsgWithdraw"][Math.floor(Math.random() * 4)],
                    time: "Just now",
                    from: "qie1..." + Math.random().toString(36).substr(2, 4),
                    amt: (Math.random() * 1000).toFixed(2) + " QIE"
                };

                setTransactions(prev => [newTx, ...prev.slice(0, 9)]);

                // Randomly toggle anomalies rarely
                if (Math.random() > 0.95) {
                    setStats(prev => ({ ...prev, anomalies24h: prev.anomalies24h + 1 }));
                }
            }, 3000);
        } else {
            // --- REAL LOGIC ---
            fetchRealData(); // Initial fetch
            interval = setInterval(fetchRealData, 5000); // Poll every 5s
        }

        return () => clearInterval(interval);
    }, [dataSource]);

    // WebSocket live feed (REAL data source): instant push of transactions,
    // alerts, and node status from the ingestion worker. 5s polling above
    // remains as fallback/reconciliation.
    useEffect(() => {
        if (dataSource !== 'REAL') return;

        const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
        const socket = io(API_BASE, { transports: ['websocket', 'polling'] });

        socket.on('connect', () => setSocketStatus('connected'));
        socket.on('disconnect', () => setSocketStatus('disconnected'));

        socket.on('new_transaction', (tx) => {
            setTransactions(prev => [{
                hash: (tx.tx_hash || '').substring(0, 10) + '...',
                type: 'BridgeValidation',
                time: 'Just now',
                from: (tx.sender || 'network').substring(0, 10) + '...',
                amt: tx.value == null ? '—' : `${tx.value} QIE`,
                severity: tx.severity,
                raw_entry: tx.raw_entry,
            }, ...prev.slice(0, 9)]);
        });

        socket.on('new_alert', (alert) => {
            setLiveAlerts(prev => [alert, ...prev].slice(0, 20));
            setStats(prev => ({ ...prev, anomalies24h: prev.anomalies24h + 1 }));
        });

        socket.on('alert_resolved', (resolved) => {
            setLiveAlerts(prev => prev.filter(alert => (
                alert.id !== resolved.alert_id && alert.tx_hash !== resolved.tx_hash
            )));
        });

        socket.on('node_status', (ns) => {
            setNodeStatus(prev => ({
                ...prev,
                height: ns.height || prev.height,
                synced: ns.healthy,
            }));
        });

        return () => socket.disconnect();
    }, [dataSource]);


    // Handle Chat Submit
    const handleChatSubmit = () => {
        if (!chatInput.trim()) return;

        const newMsgs = [...chatMessages, { role: 'user', text: chatInput }];
        setChatMessages(newMsgs);
        const currentInput = chatInput;
        setChatInput('');

        // AI Response Logic
        setTimeout(() => {
            let response = "I'm processing that request...";
            const lowerInput = currentInput.toLowerCase();

            if (lowerInput.includes('status') || lowerInput.includes('health')) {
                response = "✅ Node Status: HEALTHY. Block height is syncing normally (Height: 14,245,022). No critical alerts.";
            }
            else if (lowerInput.includes('risk') || lowerInput.includes('anomaly')) {
                response = "🛡️ AI Risk Analysis: Current network risk is LOW (0.12%). 0 Anomaly detected in last hour.";
            }
            else if (lowerInput.includes('hello') || lowerInput.includes('hi') || lowerInput.includes('hey')) {
                response = "Hello! I'm QIE-GPT. I can help you with Validator Status, Transaction Audits, Risk Scores, and Bridge Stats. What do you need?";
            }
            else if (lowerInput.includes('last transaction') || lowerInput.includes('latest') || lowerInput.includes('tx')) {
                response = "The latest transaction 0x3f2...9a1 was processed 1.2s ago. Type: Cross-Chain Transfer. Amount: 450 QIE. Destination: Ethereum.";
            }
            else if (lowerInput.includes('transaction') || lowerInput.includes('audit')) {
                response = "I can audit specific transactions for fraud patterns. Please paste a Transaction Hash (e.g., 0x123...) or ask for the 'latest transaction'.";
            }
            else if (lowerInput.includes('balance') || lowerInput.includes('funds')) {
                response = walletAddress
                    ? `💳 Wallet Analysis: Address ${walletAddress.substring(0, 6)}... holds approx 1,000.00 QIE (Demo Balance). No suspicious drains detected.`
                    : "Please connect your wallet first so I can analyze your balance.";
            }
            else if (lowerInput.includes('price') || lowerInput.includes('market')) {
                response = "💰 QIE Token Price: $1.24 (+5.2%). 24h Volume: $12.5M. Market Sentiment: Bullish 🚀";
            }
            else if (lowerInput.includes('bridge') || lowerInput.includes('cross')) {
                response = "🌉 Bridge Status: Operational. All routes (ETH, BSC, SOL) are active. Average finality time: 4.5s.";
            }
            else {
                // Randomized fallback to make it feel less static
                const fallbacks = [
                    "I've logged that query. Could you specify a module? (e.g., 'Risk', 'Bridge', 'Validator')",
                    "I'm scanning the mempool... No specific anomalies found for that keyword.",
                    "Is this regarding a specific Validator or Transaction? Please provide more context.",
                    "My current model is tuned for Blockchain Forensics. Try asking about 'Risk Scores' or 'Latest Transactions'."
                ];
                response = fallbacks[Math.floor(Math.random() * fallbacks.length)];
            }

            setChatMessages([...newMsgs, { role: 'ai', text: response }]);
        }, 800);
    };

    return (
        <div className="flex h-screen bg-slate-900 text-slate-100 font-sans overflow-hidden">

            {/* Sidebar */}
            <motion.aside
                initial={{ x: -300 }}
                animate={{ x: sidebarOpen ? 0 : -300 }}
                className={`fixed md:relative z-40 w-64 h-full bg-slate-800 border-r border-slate-700 flex flex-col transition-transform duration-300`}
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
                            <span className="text-green-400 font-mono">#{nodeStatus.height.toLocaleString()}</span>
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

                        {/* Data Source Toggle */}
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
                                {backendStatus === 'offline' && <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse"></span>}
                                {backendStatus === 'online' && <span className="w-2 h-2 rounded-full bg-green-300"></span>}
                                REAL
                            </button>
                        </div>

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

                        <button className="relative text-slate-400 hover:text-white transition">
                            <Bell className="w-5 h-5" />
                            <span className="absolute -top-1 -right-1 w-2 h-2 bg-red-500 rounded-full animate-ping" />
                        </button>

                        <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 to-cyan-400 border-2 border-slate-800" />
                    </div>
                </header>

                {/* Scrollable Content */}
                <div className="flex-1 overflow-y-auto p-6 md:p-8 scroll-smooth">
                    <div className="max-w-7xl mx-auto space-y-8">

                        {/* Header Section */}
                        <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
                            <div>
                                <h2 className="text-3xl font-bold text-white capitalize">{activeSection.replace('-', ' ')}</h2>
                                <p className="text-slate-400 mt-1">Real-time monitoring and security insights</p>
                            </div>
                            <div className="text-right hidden md:block">
                                <div className="text-sm text-slate-500">Last updated</div>
                                <div className="font-mono text-green-400">Just now</div>
                            </div>
                        </div>

                        {/* Dynamic Content Switching */}
                        <AnimatePresence mode="wait">
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
                                        <MetricCard label="Active Bridges" value={stats.activeBridges} icon={Boxes} color="blue" />
                                        <MetricCard label="Anomalies (24h)" value={stats.anomalies24h} icon={AlertTriangle} color="red" />
                                        <MetricCard label="Validation Rate" value={stats.validationRate + '%'} icon={CheckCircle} color="green" />
                                        <MetricCard label="Model Prediction" value={stats.modelAccuracy + '%'} icon={TrendingUp} color="purple" />
                                    </div>

                                    {/* Charts Area with Mock Visuals */}
                                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                                        <div className="lg:col-span-2 bg-slate-800 rounded-2xl border border-slate-700 p-6 shadow-xl">
                                            <h3 className="text-lg font-semibold mb-4">Transaction Volume (24h)</h3>
                                            <div className="h-64 w-full">
                                                <Line
                                                    data={{
                                                        labels: ['00:00', '02:00', '04:00', '06:00', '08:00', '10:00', '12:00', '14:00', '16:00', '18:00', '20:00', '22:00'],
                                                        datasets: [
                                                            {
                                                                label: 'Transactions',
                                                                data: [65, 59, 80, 81, 56, 55, 40, 70, 45, 90, 100, 85],
                                                                fill: true,
                                                                backgroundColor: 'rgba(59, 130, 246, 0.2)', // blue-500/20
                                                                borderColor: '#3b82f6', // blue-500
                                                                tension: 0.4,
                                                                pointRadius: 0
                                                            }
                                                        ]
                                                    }}
                                                    options={{
                                                        responsive: true,
                                                        maintainAspectRatio: false,
                                                        plugins: {
                                                            legend: {
                                                                display: false
                                                            },
                                                            tooltip: {
                                                                mode: 'index',
                                                                intersect: false,
                                                            }
                                                        },
                                                        scales: {
                                                            x: {
                                                                grid: {
                                                                    display: false,
                                                                    drawBorder: false
                                                                },
                                                                ticks: {
                                                                    color: '#94a3b8' // slate-400
                                                                }
                                                            },
                                                            y: {
                                                                grid: {
                                                                    color: '#334155', // slate-700
                                                                    drawBorder: false
                                                                },
                                                                ticks: {
                                                                    color: '#94a3b8'
                                                                }
                                                            }
                                                        }
                                                    }}
                                                />
                                            </div>
                                        </div>
                                        <div className="bg-slate-800 rounded-2xl border border-slate-700 p-6 shadow-xl">
                                            <h3 className="text-lg font-semibold mb-4">Risk Distribution</h3>
                                            <div className="h-64 flex flex-col justify-center gap-4">
                                                {['Low Risk', 'Medium Risk', 'High Risk', 'Critical Risk'].map((label, i) => (
                                                    <div key={label}>
                                                        <div className="flex justify-between text-sm mb-1 text-slate-400">
                                                            <span>{label}</span>
                                                            <span>{['75%', '15%', '7%', '3%'][i]}</span>
                                                        </div>
                                                        <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                                                            <div
                                                                className={`h-full rounded-full ${['bg-blue-500', 'bg-yellow-500', 'bg-orange-500', 'bg-red-500'][i]}`}
                                                                style={{ width: ['75%', '15%', '7%', '3%'][i] }}
                                                            ></div>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                </motion.div>
                            )}

                            {activeSection === 'transactions' && (
                                <motion.div
                                    key="transactions"
                                    initial={{ opacity: 0, y: 20 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, y: -20 }}
                                    className="bg-slate-800 rounded-2xl border border-slate-700 overflow-hidden shadow-xl"
                                >
                                    <div className="p-6 border-b border-slate-700">
                                        <h3 className="text-xl font-bold">Latest Transactions</h3>
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
                                                {transactions.map((tx, i) => (
                                                    <tr key={i} className="hover:bg-slate-700/30 transition-colors">
                                                        <td className="p-4 font-mono text-blue-400">{tx.hash}</td>
                                                        <td className="p-4"><span className="px-2 py-1 rounded bg-slate-700 text-xs">{tx.type}</span></td>
                                                        <td className="p-4 text-slate-400">{tx.time}</td>
                                                        <td className="p-4 font-mono text-slate-400">{tx.from}</td>
                                                        <td className="p-4 font-medium">{tx.amt}</td>
                                                        <td className="p-4">
                                                            {tx.raw_entry ? (
                                                                <span className="px-2 py-1 rounded bg-slate-700 text-slate-300 text-xs font-semibold">RAW</span>
                                                            ) : <span className="text-slate-500">-</span>}
                                                        </td>
                                                        <td className="p-4">
                                                            {tx.severity ? (
                                                                <span className={`px-2 py-1 rounded text-xs font-semibold ${SEVERITY_STYLES[tx.severity]?.bg || 'bg-slate-700'} ${SEVERITY_STYLES[tx.severity]?.text || 'text-slate-300'}`}>
                                                                    {SEVERITY_STYLES[tx.severity]?.label || tx.severity}
                                                                </span>
                                                            ) : <span className="text-slate-500">-</span>}
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                </motion.div>
                            )}

                            {activeSection === 'validators' && (
                                <motion.div
                                    key="validators"
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
                                >
                                    {[1, 2, 3, 4, 5, 6].map((v) => (
                                        <div key={v} className="bg-slate-800 p-6 rounded-2xl border border-slate-700 hover:border-blue-500/50 transition-all">
                                            <div className="flex items-center gap-4 mb-4">
                                                <div className="w-12 h-12 rounded-full bg-slate-700 flex items-center justify-center text-xl">
                                                    {['👑', '🛡️', '⚡', '🔒', '🌐', '💎'][v - 1]}
                                                </div>
                                                <div>
                                                    <h4 className="font-bold">{['Cosmos Hub', 'Smart Stake', 'ValiGuard AI', 'Everstake', 'Polkachu', 'Imperator'][v - 1]}</h4>
                                                    <div className="text-xs text-slate-400 flex items-center gap-1">
                                                        <div className="w-2 h-2 rounded-full bg-green-500"></div>
                                                        Active
                                                    </div>
                                                </div>
                                            </div>
                                            <div className="space-y-2 text-sm">
                                                <div className="flex justify-between">
                                                    <span className="text-slate-500">Voting Power</span>
                                                    <span className="font-mono">{(Math.random() * 5 + 1).toFixed(2)}%</span>
                                                </div>
                                                <div className="flex justify-between">
                                                    <span className="text-slate-500">Uptime</span>
                                                    <span className="text-green-400">99.9{v}%</span>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </motion.div>
                            )}

                            {/* News Section */}
                            {activeSection === 'news' && (
                                <motion.div
                                    key="news"
                                    initial={{ opacity: 0, y: 20 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, y: -20 }}
                                    className="space-y-6"
                                >
                                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-400">
                                        QIE Ecosystem News 📰
                                    </h2>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                        {[
                                            { title: "QIE V3 Mainnet Upgrade Successful", date: "Today", desc: "The highly anticipated V3 upgrade brings 10x throughput and EVM compatibility enhancement.", tag: "Tech", content: "The QIE Foundation is proud to announce the successful deployment of the V3 Mainnet. This upgrade introduces parallel transaction processing, reducing finality time to under 500ms. Validators are required to upgrade their nodes within 24 hours to maintain consensus participation." },
                                            { title: "ValiGuard AI Partners with QIE Foundation", date: "Today", desc: "ValiGuard AI selected as the official security partner for the cross-chain bridge initiative.", tag: "Partnership", content: "ValiGuard AI has entered a strategic partnership with the QIE Foundation to secure over $500M in cross-chain assets. This collaboration will see the integration of ValiGuard's AI-driven anomaly detection models directly into the QIE Bridge protocol." },
                                            { title: "TVL on QIE Breaches $100M Milestone", date: "Yesterday", desc: "Total Value Locked across DeFi protocols on QIE network has reached a new all-time high.", tag: "Growth", content: "Defying market trends, the Total Value Locked (TVL) on the QIE network surged past $100M this week, driven by the launch of new lending protocols and high-yield farming opportunities. User activity has increased by 300% month-over-month." },
                                            { title: "New Grant Program for AI Developers", date: "2 days ago", desc: "QIE Foundation allocates $5M fund for developers building AI agents on-chain.", tag: "Community", content: "To foster innovation at the intersection of AI and Blockchain, the QIE Foundation has launched a $5M ecosystem grant. The program specifically targets developers building autonomous agents, decentralized inference networks, and AI-governed DAOs." },
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
                                                            ✕
                                                        </button>
                                                        <span className="inline-block w-fit bg-white/20 text-white text-xs px-2 py-1 rounded-full mb-2">{selectedNews.tag}</span>
                                                        <h2 className="text-3xl font-bold text-white mb-1">{selectedNews.title}</h2>
                                                        <p className="text-white/80">{selectedNews.date}</p>
                                                    </div>
                                                    <div className="p-8 space-y-4">
                                                        <p className="text-slate-300 leading-relaxed text-lg">
                                                            {selectedNews.content || selectedNews.desc}
                                                        </p>

                                                        <div className="pt-6 border-t border-slate-800 flex justify-between items-center">
                                                            <button className="text-blue-400 hover:text-blue-300 font-medium flex items-center gap-2">
                                                                Share Article <Send size={16} />
                                                            </button>
                                                            <span className="text-slate-600 text-sm">Read time: 3 min</span>
                                                        </div>
                                                    </div>
                                                </motion.div>
                                            </motion.div>
                                        )}
                                    </AnimatePresence>
                                </motion.div>
                            )}

                            {activeSection === 'alerts' && (
                                <motion.div
                                    key="alerts"
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="space-y-4"
                                >
                                    {liveAlerts.length === 0 && (
                                        <div className="bg-slate-800 border border-slate-700 p-4 rounded-xl text-slate-400 text-sm">
                                            No live alerts yet. Alerts appear here in real time as the ingestion worker scores transactions.
                                        </div>
                                    )}
                                    {liveAlerts.map((alert, i) => {
                                        const style = SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.low;
                                        const Icon = style.icon;
                                        return (
                                            <div key={alert.tx_hash || i} className={`${style.bg} ${style.border} p-4 rounded-xl flex items-start gap-4`}>
                                                <Icon className={`${style.text} w-6 h-6 shrink-0 mt-1`} />
                                                <div>
                                                    <h4 className={`font-bold ${style.text} capitalize`}>
                                                        {style.label} anomaly detected
                                                    </h4>
                                                    <p className="text-slate-300 text-sm mt-1">{alert.message}</p>
                                                    <div className="mt-2 text-xs text-slate-500 flex items-center gap-2">
                                                        <span>{alert.time || 'Just now'}</span>
                                                        <span>•</span>
                                                        <span className="font-mono">{(alert.tx_hash || '').substring(0, 12)}...</span>
                                                        <span>•</span>
                                                        <span>Score: {typeof alert.anomaly_score === 'number' ? alert.anomaly_score.toFixed(1) : alert.anomaly_score}</span>
                                                    </div>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </motion.div>
                            )}

                            {activeSection === 'analytics' && (
                                <motion.div
                                    key="analytics"
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="space-y-6"
                                >
                                    {/* Analytics Summary Cards */}
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                            <div className="text-slate-400 text-sm mb-1">Avg Block Time</div>
                                            <div className="text-3xl font-bold flex items-end gap-2">
                                                2.1s <span className="text-green-400 text-sm mb-1">(-0.2s)</span>
                                            </div>
                                            <div className="w-full bg-slate-700 h-1 mt-4 rounded-full overflow-hidden">
                                                <div className="bg-green-500 h-full w-[85%]"></div>
                                            </div>
                                        </div>
                                        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                            <div className="text-slate-400 text-sm mb-1">Peak TPS (24h)</div>
                                            <div className="text-3xl font-bold flex items-end gap-2">
                                                4,250 <span className="text-blue-400 text-sm mb-1">(+12%)</span>
                                            </div>
                                            <div className="w-full bg-slate-700 h-1 mt-4 rounded-full overflow-hidden">
                                                <div className="bg-blue-500 h-full w-[65%]"></div>
                                            </div>
                                        </div>
                                        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                            <div className="text-slate-400 text-sm mb-1">Total Gas Used</div>
                                            <div className="text-3xl font-bold flex items-end gap-2">
                                                85.2M <span className="text-purple-400 text-sm mb-1">Gwei</span>
                                            </div>
                                            <div className="w-full bg-slate-700 h-1 mt-4 rounded-full overflow-hidden">
                                                <div className="bg-purple-500 h-full w-[45%]"></div>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Main Network Traffic Chart */}
                                    <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-xl">
                                        <div className="flex justify-between items-center mb-6">
                                            <h3 className="text-lg font-bold">Network Traffic Load</h3>
                                            <select
                                                value={trafficRange}
                                                onChange={(e) => setTrafficRange(e.target.value)}
                                                className="bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-400 px-3 py-1 outline-none focus:border-blue-500 transition-colors"
                                            >
                                                <option value="3h">Last 3 Hours</option>
                                                <option value="6h">Last 6 Hours</option>
                                                <option value="24h">Last 24 Hours</option>
                                                <option value="7d">Last 7 Days</option>
                                            </select>
                                        </div>
                                        <div className="h-64 w-full">
                                            <Bar
                                                data={{
                                                    labels: Array.from({ length: 24 }).map((_, i) => `${i}:00`),
                                                    datasets: [
                                                        {
                                                            label: 'Network Traffic (TPS)',
                                                            data: Array.from({ length: 24 }).map(() => Math.floor(Math.random() * 5000) + 1000),
                                                            backgroundColor: '#8b5cf6', // purple-500
                                                            borderRadius: 4,
                                                        }
                                                    ]
                                                }}
                                                options={{
                                                    responsive: true,
                                                    maintainAspectRatio: false,
                                                    plugins: {
                                                        legend: {
                                                            display: false
                                                        },
                                                        tooltip: {
                                                            mode: 'index',
                                                            intersect: false,
                                                        }
                                                    },
                                                    scales: {
                                                        x: {
                                                            grid: {
                                                                display: false,
                                                                drawBorder: false
                                                            },
                                                            ticks: {
                                                                color: '#94a3b8',
                                                                maxTicksLimit: 12
                                                            }
                                                        },
                                                        y: {
                                                            grid: {
                                                                color: '#334155', // slate-700
                                                                drawBorder: false
                                                            },
                                                            ticks: {
                                                                color: '#94a3b8'
                                                            }
                                                        }
                                                    }
                                                }}
                                            />
                                        </div>
                                    </div>

                                    {/* Cross-Chain Bridge Stats */}
                                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                            <h3 className="text-lg font-bold mb-4">Bridge Liquidity</h3>
                                            <div className="space-y-4">
                                                {['Ethereum', 'BSC', 'Polygon', 'Avalanche'].map((chain, i) => (
                                                    <div key={chain} className="flex items-center justify-between">
                                                        <div className="flex items-center gap-3">
                                                            <div className={`w-3 h-3 rounded-full ${['bg-blue-500', 'bg-yellow-500', 'bg-purple-500', 'bg-red-500'][i]}`}></div>
                                                            <span className="text-slate-300 font-medium">{chain}</span>
                                                        </div>
                                                        <div className="text-right">
                                                            <div className="font-mono text-white">${(Math.random() * 5 + 1).toFixed(2)}M</div>
                                                            <div className="text-xs text-slate-500 flex items-center justify-end gap-1">
                                                                <TrendingUp className="w-3 h-3 text-green-500" />
                                                                +{Math.floor(Math.random() * 10)}%
                                                            </div>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>

                                        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
                                            <h3 className="text-lg font-bold mb-4">Contract Calls Distribution</h3>
                                            <div className="flex gap-2 h-4 mb-4 rounded-full overflow-hidden bg-slate-900">
                                                <div className="w-[40%] bg-blue-500 h-full"></div>
                                                <div className="w-[30%] bg-green-500 h-full"></div>
                                                <div className="w-[20%] bg-purple-500 h-full"></div>
                                                <div className="w-[10%] bg-yellow-500 h-full"></div>
                                            </div>
                                            <div className="grid grid-cols-2 gap-4 text-sm">
                                                <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-blue-500"></div> DeFis (40%)</div>
                                                <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-green-500"></div> NFTs (30%)</div>
                                                <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-purple-500"></div> Bridges (20%)</div>
                                                <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-yellow-500"></div> Gaming (10%)</div>
                                            </div>
                                        </div>
                                    </div>
                                </motion.div>
                            )}

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
                                                    👽
                                                </div>
                                            </div>
                                        </div>
                                        <div className="pt-16 pb-8 px-8">
                                            <h2 className="text-2xl font-bold">Validator Operator</h2>
                                            <p className="text-slate-400">admin@valiguard.ai</p>
                                            <div className="flex gap-2 mt-4">
                                                <span className="px-3 py-1 rounded-full bg-green-500/10 text-green-400 text-xs border border-green-500/20">Active Validator</span>
                                                <span className="px-3 py-1 rounded-full bg-blue-500/10 text-blue-400 text-xs border border-blue-500/20">Testnet</span>
                                            </div>
                                        </div>
                                    </div>
                                </motion.div>
                            )}

                        </AnimatePresence>
                    </div>
                </div>

                {/* QIE-GPT Floating Chat */}
                <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end">
                    <AnimatePresence>
                        {isChatOpen && (
                            <motion.div
                                initial={{ opacity: 0, scale: 0.9, y: 20 }}
                                animate={{ opacity: 1, scale: 1, y: 0 }}
                                exit={{ opacity: 0, scale: 0.9, y: 20 }}
                                className="mb-4 w-80 bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl overflow-hidden flex flex-col"
                                style={{ height: '400px' }}
                            >
                                <div className="bg-gradient-to-r from-blue-600 to-purple-600 p-4 flex justify-between items-center">
                                    <div className="flex items-center gap-2">
                                        <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></div>
                                        <span className="font-bold text-white">QIE-GPT Agent</span>
                                    </div>
                                    <button onClick={() => setIsChatOpen(false)} className="text-white/80 hover:text-white">✕</button>
                                </div>

                                <div className="flex-1 p-4 overflow-y-auto space-y-4 text-sm scrollbar-thin scrollbar-thumb-slate-700">
                                    {chatMessages.map((msg, i) => (
                                        <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                            <div className={`max-w-[80%] p-3 rounded-2xl ${msg.role === 'user' ? 'bg-blue-600 text-white rounded-tr-none' : 'bg-slate-800 text-slate-200 rounded-tl-none'}`}>
                                                {msg.text}
                                            </div>
                                        </div>
                                    ))}
                                </div>

                                <div className="p-3 bg-slate-800 border-t border-slate-700 flex gap-2">
                                    <input
                                        type="text"
                                        value={chatInput}
                                        onChange={(e) => setChatInput(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') handleChatSubmit();
                                        }}
                                        placeholder="Ask AI..."
                                        className="flex-1 bg-slate-900 border border-slate-700 rounded-xl px-3 text-slate-200 focus:outline-none focus:border-blue-500"
                                    />
                                    <button onClick={handleChatSubmit} className="bg-blue-600 p-2 rounded-xl text-white hover:bg-blue-700">
                                        <Send size={18} />
                                    </button>
                                </div>
                            </motion.div>
                        )}
                    </AnimatePresence>

                    <button
                        onClick={() => setIsChatOpen(!isChatOpen)}
                        className="bg-gradient-to-r from-blue-600 to-purple-600 p-4 rounded-full shadow-lg text-white hover:scale-110 transition-transform flex items-center gap-2 group"
                    >
                        <MessageSquare size={24} />
                        {!isChatOpen && <span className="max-w-0 overflow-hidden group-hover:max-w-xs transition-all duration-300 whitespace-nowrap px-0 group-hover:px-2">Ask QIE-GPT</span>}
                    </button>
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
