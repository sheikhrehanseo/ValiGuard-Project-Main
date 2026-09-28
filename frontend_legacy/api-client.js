/**
 * api-client.js
 * JavaScript API client for ValiGuard AI frontend
 * 
 * Features:
 * - Fetch-based HTTP client with retry logic
 * - Request caching with TTL
 * - WebSocket for real-time updates
 * - Error handling and timeouts
 * - Request ID tracking
 */

const API_CONFIG = {
    baseURL: 'http://localhost:5000',
    timeout: 30000,  // 30 seconds
    retryAttempts: 3,
    retryDelay: 1000,  // 1 second
    cacheTTL: 5 * 60 * 1000  // 5 minutes
};

class ValiGuardAPI {
    constructor(config = {}) {
        this.config = { ...API_CONFIG, ...config };
        this.cache = new Map();
        this.session = {
            token: localStorage.getItem('auth_token'),
            requestId: this.generateRequestId()
        };
        this.listeners = new Map();
    }

    /**
     * Generate unique request ID
     */
    generateRequestId() {
        return `REQ-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    }

    /**
     * Format timestamp
     */
    formatTimestamp(ts) {
        return new Date(ts).toLocaleString();
    }

    /**
     * Format number with commas
     */
    formatNumber(num) {
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    }

    /**
     * Truncate wallet address
     */
    truncateAddress(addr, start = 6, end = 4) {
        if (!addr || addr.length <= start + end) return addr;
        return `${addr.substring(0, start)}...${addr.substring(addr.length - end)}`;
    }

    /**
     * Make HTTP request with retry logic
     */
    async request(endpoint, options = {}) {
        const {
            method = 'GET',
            body = null,
            headers = {},
            useCache = true,
            retries = this.config.retryAttempts
        } = options;

        const url = `${this.config.baseURL}${endpoint}`;
        const cacheKey = `${method}:${endpoint}`;

        // Check cache for GET requests
        if (method === 'GET' && useCache && this.cache.has(cacheKey)) {
            const cached = this.cache.get(cacheKey);
            if (Date.now() - cached.timestamp < this.config.cacheTTL) {
                console.log(`[Cache HIT] ${cacheKey}`);
                return cached.data;
            }
        }

        const requestInit = {
            method,
            headers: {
                'Content-Type': 'application/json',
                'X-Request-ID': this.generateRequestId(),
                ...headers
            },
            signal: AbortSignal.timeout(this.config.timeout)
        };

        if (body) {
            requestInit.body = typeof body === 'string' ? body : JSON.stringify(body);
        }

        // Add API key if available
        if (this.session.token) {
            requestInit.headers['X-API-Key'] = this.session.token;
        }

        // Retry loop
        for (let attempt = 0; attempt <= retries; attempt++) {
            try {
                console.log(`[REQUEST] ${method} ${endpoint} (attempt ${attempt + 1})`);
                
                const response = await fetch(url, requestInit);
                
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(`HTTP ${response.status}: ${errorData.error || response.statusText}`);
                }

                const data = await response.json();

                // Cache successful GET responses
                if (method === 'GET' && useCache) {
                    this.cache.set(cacheKey, {
                        data,
                        timestamp: Date.now()
                    });
                }

                console.log(`[RESPONSE] ${method} ${endpoint}`, data);
                return data;

            } catch (error) {
                console.warn(`[ERROR] Attempt ${attempt + 1}/${retries + 1}: ${error.message}`);

                if (attempt < retries) {
                    const delay = this.config.retryDelay * Math.pow(2, attempt);
                    await new Promise(resolve => setTimeout(resolve, delay));
                } else {
                    throw new Error(`Failed after ${retries + 1} attempts: ${error.message}`);
                }
            }
        }
    }

    /**
     * DASHBOARD DATA
     */

    async getDashboardStats() {
        // Aggregate data from multiple endpoints
        const [nodeStatus, dailyStats, modelAccuracy] = await Promise.all([
            this.getQieNodeStatus(),
            this.getDailyStats(),
            this.getModelAccuracy()
        ]);

        return {
            node: nodeStatus.data?.node,
            stats: dailyStats.data,
            model: modelAccuracy.data
        };
    }

    async getRecentTransactions(limit = 20) {
        const response = await this.request(`/api/v1/bridge/history?limit=${limit}`);
        return response.data?.transactions || [];
    }

    async getAnomalyStats() {
        const response = await this.request('/api/v1/analytics/daily-stats');
        return response.data;
    }

    /**
     * QIE NODE METHODS
     */

    async getQieNodeStatus() {
        return this.request('/api/v1/qie/node/status');
    }

    async getValidatorInfo(address) {
        return this.request(`/api/v1/qie/validator/info?address=${encodeURIComponent(address)}`);
    }

    async getBlockHeight() {
        const response = await this.request('/api/v1/qie/node/status');
        return response.data?.node?.height || 0;
    }

    async getAccountBalance(address) {
        return this.request(`/api/v1/qie/account/${encodeURIComponent(address)}`);
    }

    /**
     * BRIDGE OPERATIONS
     */

    async validateTransaction(txData) {
        return this.request('/api/v1/bridge/validate-cross-chain', {
            method: 'POST',
            body: txData,
            useCache: false
        });
    }

    async getAnomalyScore(transaction) {
        return this.request('/api/v1/bridge/anomaly-score', {
            method: 'POST',
            body: transaction,
            useCache: false
        });
    }

    async reportAnomaly(txId, reason, severity = 'high') {
        return this.request('/api/v1/bridge/alert', {
            method: 'POST',
            body: {
                transaction_hash: txId,
                reason,
                severity,
                timestamp: new Date().toISOString()
            },
            useCache: false
        });
    }

    async broadcastTransaction(txData) {
        return this.request('/api/v1/qie/transaction/broadcast', {
            method: 'POST',
            body: txData,
            useCache: false
        });
    }

    /**
     * ANALYTICS
     */

    async getDailyStats(date = null) {
        const params = date ? `?date=${date}` : '';
        return this.request(`/api/v1/analytics/daily-stats${params}`);
    }

    async getModelAccuracy() {
        return this.request('/api/v1/analytics/model-accuracy', { useCache: true });
    }

    async getValidatorStats() {
        return this.request('/api/v1/analytics/validator-stats', { useCache: true });
    }

    /**
     * WEBSOCKET METHODS
     */

    connectWebSocket() {
        const wsURL = this.config.baseURL.replace('http', 'ws');
        
        try {
            this.ws = new WebSocket(`${wsURL}/ws`);
            
            this.ws.onopen = () => {
                console.log('[WebSocket] Connected');
                this.emit('ws:connected');
            };
            
            this.ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    this.handleWebSocketMessage(message);
                } catch (e) {
                    console.error('[WebSocket] Parse error:', e);
                }
            };
            
            this.ws.onerror = (error) => {
                console.error('[WebSocket] Error:', error);
                this.emit('ws:error', error);
            };
            
            this.ws.onclose = () => {
                console.log('[WebSocket] Disconnected');
                this.emit('ws:disconnected');
                // Attempt reconnect after 5 seconds
                setTimeout(() => this.connectWebSocket(), 5000);
            };
        } catch (error) {
            console.error('[WebSocket] Connection failed:', error);
        }
    }

    handleWebSocketMessage(message) {
        const { type, data } = message;
        
        switch (type) {
            case 'transaction':
                this.emit('transaction:update', data);
                break;
            case 'anomaly':
                this.emit('anomaly:detected', data);
                break;
            case 'alert':
                this.emit('alert:received', data);
                break;
            case 'node_status':
                this.emit('node:status', data);
                break;
            default:
                console.warn('[WebSocket] Unknown message type:', type);
        }
    }

    /**
     * EVENT SYSTEM
     */

    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, []);
        }
        this.listeners.get(event).push(callback);
    }

    off(event, callback) {
        if (!this.listeners.has(event)) return;
        const listeners = this.listeners.get(event);
        const index = listeners.indexOf(callback);
        if (index > -1) {
            listeners.splice(index, 1);
        }
    }

    emit(event, data) {
        if (!this.listeners.has(event)) return;
        this.listeners.get(event).forEach(callback => {
            try {
                callback(data);
            } catch (error) {
                console.error(`Error in event listener for ${event}:`, error);
            }
        });
    }

    /**
     * CACHE MANAGEMENT
     */

    clearCache(pattern = null) {
        if (!pattern) {
            this.cache.clear();
        } else {
            for (const key of this.cache.keys()) {
                if (key.includes(pattern)) {
                    this.cache.delete(key);
                }
            }
        }
    }

    getCacheStats() {
        return {
            size: this.cache.size,
            keys: Array.from(this.cache.keys())
        };
    }

    /**
     * HEALTH CHECK
     */

    async healthCheck() {
        try {
            const response = await fetch(`${this.config.baseURL}/health`, {
                timeout: 5000
            });
            return response.ok;
        } catch {
            return false;
        }
    }
}

// Create global instance
const api = new ValiGuardAPI();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ValiGuardAPI, api };
}
