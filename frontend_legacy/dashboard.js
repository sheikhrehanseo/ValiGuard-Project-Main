/**
 * dashboard.js
 * Dashboard controller for ValiGuard AI
 * 
 * Manages:
 * - Chart initialization and data updates
 * - Real-time data fetching
 * - UI element updates
 * - Event handling
 */

class DashboardController {
    constructor() {
        this.charts = {};
        this.refreshInterval = 30000;  // 30 seconds
        this.refreshTimers = new Map();
        this.isInitialized = false;
    }

    /**
     * Initialize dashboard on page load
     */
    async init() {
        console.log('[Dashboard] Initializing...');

        try {
            // Wait for DOM to be ready
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', () => this.init());
                return;
            }

            // Check API health
            const isHealthy = await api.healthCheck();
            if (!isHealthy) {
                this.showAlert('Warning: API server not responding', 'warning');
            }

            // Initialize components
            this.initEventListeners();
            this.initCharts();
            this.setupWebSocket();

            // Initial data load
            await this.loadDashboardData();

            // Setup auto-refresh
            this.startAutoRefresh();

            this.isInitialized = true;
            console.log('[Dashboard] Ready');
        } catch (error) {
            console.error('[Dashboard] Initialization error:', error);
            this.showAlert(`Error initializing dashboard: ${error.message}`, 'error');
        }
    }

    /**
     * EVENT LISTENERS
     */

    initEventListeners() {
        // Navigation
        document.querySelectorAll('[data-nav]').forEach(el => {
            el.addEventListener('click', (e) => this.handleNavClick(e));
        });

        // Network selector
        const networkSelector = document.getElementById('networkSelector');
        if (networkSelector) {
            networkSelector.addEventListener('change', (e) => this.handleNetworkChange(e));
        }

        // Export button
        const exportBtn = document.getElementById('exportBtn');
        if (exportBtn) {
            exportBtn.addEventListener('click', () => this.exportData());
        }

        // Refresh button
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.forceRefresh());
        }

        // Mobile menu toggle
        const menuToggle = document.getElementById('menuToggle');
        if (menuToggle) {
            menuToggle.addEventListener('click', () => this.toggleMobileMenu());
        }
    }

    handleNavClick(event) {
        const target = event.currentTarget.getAttribute('data-nav');
        console.log(`[Navigation] Clicked: ${target}`);

        // Hide all sections
        document.querySelectorAll('.section-content').forEach(el => el.classList.add('hidden'));

        // Show target section if it exists
        const targetSection = document.getElementById(`${target}Section`) || document.getElementById(`${target.replace(/-([a-z])/g, (g) => g[1].toUpperCase())}Section`);
        if (targetSection) {
            targetSection.classList.remove('hidden');
        } else {
            // Fallback for sections like 'user-profile' mapping to 'userProfileSection'
            const camelCaseTarget = target.replace(/-([a-z])/g, (g) => g[1].toUpperCase());
            const camelSection = document.getElementById(`${camelCaseTarget}Section`);
            if (camelSection) camelSection.classList.remove('hidden');
        }

        // Update active state
        document.querySelectorAll('[data-nav]').forEach(el => {
            el.classList.remove('bg-blue-600', 'text-white');
            el.classList.add('text-gray-300');
        });
        // Add active style to current button (check if it's a button, not link)
        if (event.currentTarget.tagName === 'BUTTON') {
            event.currentTarget.classList.remove('text-gray-300');
            event.currentTarget.classList.add('bg-blue-600', 'text-white');
        }
    }

    handleNetworkChange(event) {
        const network = event.target.value;
        console.log(`[Network] Changed to: ${network}`);
        localStorage.setItem('selectedNetwork', network);
        this.forceRefresh();
    }

    toggleMobileMenu() {
        const menu = document.querySelector('[data-mobile-menu]');
        if (menu) {
            menu.classList.toggle('hidden');
        }
    }

    /**
     * DATA LOADING
     */

    async loadDashboardData() {
        console.log('[Dashboard] Loading data...');

        try {
            const stats = await api.getDashboardStats();
            this.updateMetrics(stats);

            const transactions = await api.getRecentTransactions(10);
            this.updateTransactionsTable(transactions);

            const anomalyData = await api.getAnomalyStats();
            this.updateCharts(anomalyData);

            const validatorStats = await api.getValidatorStats();
            this.updateValidatorPanel(validatorStats);
        } catch (error) {
            console.error('[Dashboard] Error loading data:', error);
            this.showAlert(`Error loading dashboard data: ${error.message}`, 'error');
        }
    }

    /**
     * UPDATE METRICS
     */

    updateMetrics(stats) {
        console.log('[Metrics] Updating...', stats);

        // Active bridges
        const activeBridges = document.getElementById('activeBridges');
        if (activeBridges && stats.stats?.active_bridges) {
            activeBridges.textContent = api.formatNumber(stats.stats.active_bridges);
        }

        // Anomalies (24h)
        const anomalies = document.getElementById('anomalies24h');
        if (anomalies && stats.stats?.anomalies_24h) {
            anomalies.textContent = api.formatNumber(stats.stats.anomalies_24h);
        }

        // Validation rate
        const validationRate = document.getElementById('validationRate');
        if (validationRate && stats.stats?.validation_rate) {
            const rate = (stats.stats.validation_rate * 100).toFixed(2);
            validationRate.textContent = `${rate}%`;
        }

        // Model accuracy
        const accuracy = document.getElementById('modelAccuracy');
        if (accuracy && stats.model?.accuracy) {
            const acc = (stats.model.accuracy * 100).toFixed(2);
            accuracy.textContent = `${acc}%`;
        }

        // QIE Node Status
        if (stats.node) {
            this.updateQieNodeStatus(stats.node);
        }
    }

    updateQieNodeStatus(nodeData) {
        // Node status indicator
        const statusIndicator = document.getElementById('nodeStatus');
        if (statusIndicator && nodeData.is_synced) {
            statusIndicator.className = 'w-3 h-3 bg-green-400 rounded-full animate-pulse';
        } else if (statusIndicator) {
            statusIndicator.className = 'w-3 h-3 bg-yellow-400 rounded-full animate-pulse-slow';
        }

        // Block height
        const blockHeight = document.getElementById('blockHeight');
        if (blockHeight && nodeData.height) {
            blockHeight.textContent = api.formatNumber(nodeData.height);
        }

        // Node status panel
        const nodeMoniker = document.getElementById('nodeMoniker');
        if (nodeMoniker && nodeData.moniker) {
            nodeMoniker.textContent = nodeData.moniker;
        }

        const syncStatus = document.getElementById('syncStatus');
        if (syncStatus) {
            const status = nodeData.is_synced ? 'Synced' : `Syncing (${(nodeData.catching_up * 100).toFixed(1)}%)`;
            syncStatus.textContent = status;
        }

        const nodeVersion = document.getElementById('nodeVersion');
        if (nodeVersion && nodeData.version) {
            nodeVersion.textContent = nodeData.version;
        }

        const rpcPort = document.getElementById('rpcPort');
        if (rpcPort && nodeData.rpc_port) {
            rpcPort.textContent = nodeData.rpc_port;
        }

        const p2pPort = document.getElementById('p2pPort');
        if (p2pPort && nodeData.p2p_port) {
            p2pPort.textContent = nodeData.p2p_port;
        }
    }

    /**
     * CHART UPDATES
     */

    initCharts() {
        console.log('[Charts] Initializing...');

        // Transaction Volume Chart
        const txCtx = document.getElementById('txVolumeChart');
        if (txCtx) {
            this.charts.txVolume = new Chart(txCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Transaction Volume (24h)',
                        data: [],
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        tension: 0.4,
                        fill: true,
                        pointRadius: 4,
                        pointBackgroundColor: '#3b82f6',
                        pointBorderColor: '#ffffff',
                        pointBorderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: {
                            display: true,
                            labels: { color: '#9ca3af', font: { size: 12 } }
                        }
                    },
                    scales: {
                        y: {
                            ticks: { color: '#9ca3af' },
                            grid: { color: '#374151' }
                        },
                        x: {
                            ticks: { color: '#9ca3af' },
                            grid: { color: '#374151' }
                        }
                    }
                }
            });
        }

        // Anomaly Distribution Chart
        const anomalyCtx = document.getElementById('anomalyDistChart');
        if (anomalyCtx) {
            this.charts.anomalyDist = new Chart(anomalyCtx, {
                type: 'doughnut',
                data: {
                    labels: ['Normal', 'Low Risk', 'Medium Risk', 'High Risk'],
                    datasets: [{
                        data: [70, 15, 10, 5],
                        backgroundColor: [
                            '#10b981',
                            '#f59e0b',
                            '#ef4444',
                            '#7c3aed'
                        ],
                        borderColor: '#1f2937',
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: {
                            display: true,
                            labels: { color: '#9ca3af', font: { size: 12 } }
                        }
                    }
                }
            });
        }
    }

    updateCharts(anomalyData) {
        console.log('[Charts] Updating with data:', anomalyData);

        // Update transaction volume
        if (this.charts.txVolume && anomalyData?.hourly_volumes) {
            const volumes = anomalyData.hourly_volumes;
            this.charts.txVolume.data.labels = volumes.map((_, i) => `${i}:00`);
            this.charts.txVolume.data.datasets[0].data = volumes;
            this.charts.txVolume.update();
        }

        // Update anomaly distribution
        if (this.charts.anomalyDist && anomalyData?.anomaly_distribution) {
            const dist = anomalyData.anomaly_distribution;
            this.charts.anomalyDist.data.datasets[0].data = [
                dist.normal || 0,
                dist.low || 0,
                dist.medium || 0,
                dist.high || 0
            ];
            this.charts.anomalyDist.update();
        }
    }

    /**
     * TRANSACTIONS TABLE
     */

    updateTransactionsTable(transactions) {
        console.log('[Transactions] Updating table with', transactions.length, 'items');

        const tbody = document.querySelector('[data-transactions-table] tbody');
        if (!tbody) return;

        tbody.innerHTML = transactions.slice(0, 10).map(tx => `
            <tr class="border-b border-gray-700 hover:bg-gray-750 transition">
                <td class="px-4 py-3 text-sm">
                    <span class="font-mono text-blue-400">${api.truncateAddress(tx.hash || tx.tx_hash)}</span>
                </td>
                <td class="px-4 py-3 text-sm">
                    <span class="font-mono text-green-400">${api.truncateAddress(tx.from_chain || tx.source_chain)}</span>
                    → 
                    <span class="font-mono text-purple-400">${api.truncateAddress(tx.to_chain || tx.dest_chain)}</span>
                </td>
                <td class="px-4 py-3 text-sm text-gray-400">${api.formatNumber(tx.amount || 0)} ${tx.token || 'QIE'}</td>
                <td class="px-4 py-3 text-sm">
                    <span class="px-2 py-1 rounded text-xs font-medium ${this.getStatusBadgeClass(tx.status)}">
                        ${tx.status || 'pending'}
                    </span>
                </td>
                <td class="px-4 py-3 text-xs text-gray-500">${api.formatTimestamp(tx.timestamp)}</td>
            </tr>
        `).join('');
    }

    getStatusBadgeClass(status) {
        const statusMap = {
            'confirmed': 'bg-green-900 text-green-200',
            'pending': 'bg-yellow-900 text-yellow-200',
            'failed': 'bg-red-900 text-red-200',
            'anomaly': 'bg-purple-900 text-purple-200'
        };
        return statusMap[status?.toLowerCase()] || 'bg-gray-700 text-gray-200';
    }

    /**
     * VALIDATOR PANEL
     */

    updateValidatorPanel(validatorStats) {
        console.log('[Validators] Updating panel...', validatorStats);

        const validatorList = document.querySelector('[data-validators-list]');
        if (!validatorList || !validatorStats?.validators) return;

        validatorList.innerHTML = validatorStats.validators.slice(0, 5).map(validator => `
            <div class="border border-gray-700 rounded-lg p-3 hover:border-blue-500 transition cursor-pointer">
                <div class="flex justify-between items-start">
                    <div>
                        <p class="font-semibold text-sm">${validator.moniker || 'Unknown'}</p>
                        <p class="font-mono text-xs text-gray-500">${api.truncateAddress(validator.operator_address)}</p>
                    </div>
                    <span class="px-2 py-1 text-xs rounded font-medium ${validator.status === 'BOND_STATUS_BONDED' ? 'bg-green-900 text-green-200' : 'bg-gray-700 text-gray-300'}">
                        ${validator.status === 'BOND_STATUS_BONDED' ? 'Active' : 'Inactive'}
                    </span>
                </div>
                <div class="mt-2 grid grid-cols-2 gap-2 text-xs">
                    <div>
                        <p class="text-gray-500">Power</p>
                        <p class="font-mono text-green-400">${api.formatNumber(validator.tokens || 0)}</p>
                    </div>
                    <div>
                        <p class="text-gray-500">Commission</p>
                        <p class="font-mono text-blue-400">${(validator.commission?.commission_rates?.rate * 100 || 0).toFixed(2)}%</p>
                    </div>
                </div>
            </div>
        `).join('');
    }

    /**
     * AUTO-REFRESH
     */

    startAutoRefresh() {
        console.log('[AutoRefresh] Starting (interval: ' + this.refreshInterval + 'ms)');

        // Main dashboard refresh
        this.refreshTimers.set('main', setInterval(() => {
            this.loadDashboardData().catch(error => {
                console.error('[AutoRefresh] Error:', error);
            });
        }, this.refreshInterval));

        // Node status refresh (faster)
        this.refreshTimers.set('node', setInterval(() => {
            api.getQieNodeStatus()
                .then(response => {
                    if (response.data?.node) {
                        this.updateQieNodeStatus(response.data.node);
                    }
                })
                .catch(error => console.warn('[Node Refresh] Error:', error));
        }, 10000));  // Every 10 seconds
    }

    stopAutoRefresh() {
        this.refreshTimers.forEach((timer, key) => {
            clearInterval(timer);
            console.log(`[AutoRefresh] Stopped: ${key}`);
        });
        this.refreshTimers.clear();
    }

    forceRefresh() {
        console.log('[Dashboard] Force refresh initiated');
        api.clearCache();
        this.loadDashboardData();
    }

    /**
     * WEBSOCKET
     */

    setupWebSocket() {
        api.on('ws:connected', () => {
            console.log('[WebSocket] Connected');
            this.showAlert('Connected to real-time updates', 'success');
        });

        api.on('transaction:update', (txData) => {
            console.log('[WebSocket] Transaction update:', txData);
            this.showNotification('New Transaction', `${txData.from_chain} → ${txData.to_chain}`);
        });

        api.on('anomaly:detected', (anomalyData) => {
            console.log('[WebSocket] Anomaly detected:', anomalyData);
            this.showNotification('Anomaly Alert', `Risk Score: ${anomalyData.risk_score}`, 'warning');
        });

        api.on('alert:received', (alertData) => {
            console.log('[WebSocket] Alert received:', alertData);
            this.showNotification('Security Alert', alertData.message, 'error');
        });

        api.on('ws:disconnected', () => {
            console.warn('[WebSocket] Disconnected');
        });

        api.on('ws:error', (error) => {
            console.error('[WebSocket] Error:', error);
        });

        // Attempt connection (optional - only if backend supports WS)
        try {
            api.connectWebSocket();
        } catch (error) {
            console.log('[WebSocket] Not available (polling fallback active)');
        }
    }

    /**
     * UI UTILITIES
     */

    showAlert(message, type = 'info') {
        const alertDiv = document.createElement('div');
        alertDiv.className = `fixed top-4 right-4 px-4 py-3 rounded-lg text-white text-sm z-50 ${type === 'error' ? 'bg-red-600' :
                type === 'warning' ? 'bg-yellow-600' :
                    type === 'success' ? 'bg-green-600' :
                        'bg-blue-600'
            }`;
        alertDiv.textContent = message;

        document.body.appendChild(alertDiv);

        setTimeout(() => {
            alertDiv.style.opacity = '0';
            alertDiv.style.transition = 'opacity 0.3s ease-out';
            setTimeout(() => alertDiv.remove(), 300);
        }, 3000);
    }

    showNotification(title, message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `fixed bottom-4 right-4 bg-gray-800 border-l-4 rounded p-4 text-white text-sm z-50 ${type === 'error' ? 'border-red-500' :
                type === 'warning' ? 'border-yellow-500' :
                    'border-blue-500'
            }`;
        notification.innerHTML = `
            <p class="font-semibold">${title}</p>
            <p class="text-gray-300">${message}</p>
        `;

        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.opacity = '0';
            notification.style.transition = 'opacity 0.3s ease-out';
            setTimeout(() => notification.remove(), 300);
        }, 5000);
    }

    /**
     * DATA EXPORT
     */

    async exportData() {
        try {
            const transactions = await api.getRecentTransactions(100);
            const stats = await api.getDashboardStats();

            const data = {
                exportDate: new Date().toISOString(),
                stats,
                transactions
            };

            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `valiguard-export-${Date.now()}.json`;
            a.click();
            URL.revokeObjectURL(url);

            this.showAlert('Data exported successfully', 'success');
        } catch (error) {
            console.error('[Export] Error:', error);
            this.showAlert(`Export failed: ${error.message}`, 'error');
        }
    }
}

// Global dashboard instance
const dashboard = new DashboardController();

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => dashboard.init());
} else {
    dashboard.init();
}
