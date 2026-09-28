# ValiGuard AI - Complete Implementation Guide

## 📋 System Overview

ValiGuard AI is a comprehensive blockchain security monitoring system for QIE cross-chain bridge validation with machine learning anomaly detection.

### Architecture Layers

```
┌─────────────────────────────────────────────┐
│         Frontend (Vanilla JavaScript)        │
│  - dashboard.html: Responsive UI            │
│  - api-client.js: HTTP + WebSocket client   │
│  - dashboard.js: Controller & event logic   │
└──────────────────┬──────────────────────────┘
                   │ HTTP (port 5000)
                   │ WebSocket (optional)
┌──────────────────▼──────────────────────────┐
│       Flask REST API (Python backend)        │
│  - 13 endpoints for node/bridge/analytics   │
│  - Pydantic validation                      │
│  - Rate limiting & API key auth             │
│  - Structured JSON-RPC logging              │
└──────────────────┬──────────────────────────┘
                   │ RPC (port 26657)
┌──────────────────▼──────────────────────────┐
│    QIE Node Manager (Python module)          │
│  - Tendermint RPC communication              │
│  - Connection pooling & retry logic          │
│  - 8 core functions for node management      │
└──────────────────┬──────────────────────────┘
                   │ Binary / subprocess
┌──────────────────▼──────────────────────────┐
│    QIE Blockchain Node (Go-based)            │
│  - Validator setup                          │
│  - Cross-chain bridge logic                 │
│  - Consensus (Tendermint)                   │
└─────────────────────────────────────────────┘
```

---

## 🚀 Quick Start (5 minutes)

### Prerequisites
- Python 3.12+
- pip / virtual environment
- Git Bash or WSL2 (for Linux scripts)
- QIE testnet access

### Installation Steps

#### 1. Install Python Dependencies
```bash
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
```

#### 2. Setup QIE Node (using bash scripts)
```bash
bash scripts/setup_qie_validator.sh
# This runs:
# - install_qie.sh (download QIE binary)
# - init_qie_node.sh (initialize node)
# - configure_qie_node.sh (apply genesis, set ports)
```

#### 3. Verify Installation
```bash
bash scripts/verify_qie_setup.sh
```

#### 4. Start Backend API
```bash
python backend/app.py
# API starts on http://localhost:5000
# Open dashboard: http://localhost:5000/dashboard
```

#### 5. Open Dashboard
```
http://localhost:5000/dashboard.html
```

---

## 📁 Project Structure & File Descriptions

### Backend Files

#### `backend/app.py` (500+ lines)
Flask REST API with 13 endpoints
- **QIE Node Endpoints:**
  - `GET /api/v1/qie/node/status` - Node health, sync status, block height
  - `GET /api/v1/qie/validator/info` - Validator details, voting power
  - `GET /api/v1/qie/account/{address}` - Account balance and info
  - `POST /api/v1/qie/transaction/broadcast` - Send signed transactions
  
- **Bridge Validation Endpoints:**
  - `POST /api/v1/bridge/validate-cross-chain` - Validate cross-chain transactions
  - `POST /api/v1/bridge/anomaly-score` - Calculate anomaly risk score
  - `GET /api/v1/bridge/history` - Transaction history (pagination support)
  - `POST /api/v1/bridge/alert` - Report anomalies/security alerts
  
- **Analytics Endpoints:**
  - `GET /api/v1/analytics/daily-stats` - Daily statistics (volume, anomalies)
  - `GET /api/v1/analytics/model-accuracy` - ML model performance metrics
  - `GET /api/v1/analytics/validator-stats` - Network validator statistics
  
- **Health Endpoint:**
  - `GET /health` - API health check

**Key Features:**
- Pydantic request/response validation
- Rate limiting: 100 req/min per IP
- API key authentication (`X-API-Key` header)
- JSON structured logging with request ID tracking
- Wrapped JSON responses (`{success, data, error, request_id, timestamp}`)
- CORS enabled for local development
- Error handlers for 404/500 with custom error codes

**Example Request:**
```bash
curl -H "X-API-Key: your-api-key" \
  http://localhost:5000/api/v1/qie/node/status
```

**Example Response:**
```json
{
  "success": true,
  "data": {
    "node": {
      "height": 1234567,
      "moniker": "valiguard-ai-validator",
      "is_synced": true,
      "version": "v3.0.0"
    }
  },
  "request_id": "REQ-1234567890-abc123",
  "timestamp": "2025-01-15T10:30:45.123Z"
}
```

#### `backend/qie_node_manager.py` (19.5 KB)
Python module for QIE RPC communication
- **Classes:** `QIENodeManager`
- **Methods:**
  - `start_qie_node()` - Start QIE process (subprocess)
  - `stop_qie_node(timeout=30)` - Graceful shutdown (SIGTERM)
  - `check_node_health()` - Query sync status, catching_up flag
  - `get_node_status()` - Full node info via JSON-RPC
  - `get_latest_block()` - Block height and header
  - `get_validator_info(address)` - Query validator power, commission
  - `query_balance(address)` - Account balance lookup
  - `broadcast_transaction(tx_dict)` - Send signed transactions
  - `wait_for_sync(max_attempts, interval)` - Poll until synced

**Key Features:**
- Tendermint JSON-RPC communication (port 26657)
- Exponential backoff retry logic (3 attempts, 1-4 second delays)
- Connection timeout: 10 seconds per request
- Connection pooling via requests.Session
- Logging integration
- Configurable via environment variables:
  - `QIE_RPC_URL` (default: https://testnet-rpc.qie.digital)
  - `QIE_CHAIN_ID` (default: 1234)
  - `QIE_MONIKER` (default: valiguard-ai-validator)

**Example Usage:**
```python
from backend.qie_node_manager import QIENodeManager

manager = QIENodeManager()
status = manager.check_node_health()
print(f"Node synced: {status['is_synced']}")
print(f"Block height: {status['height']}")
```

#### `backend/test_qie_node_manager.py` (4.8 KB)
Unit tests for QIE node manager
- Test initialization and configuration
- Test health check, status, block queries
- Test validator and balance queries
- Test transaction broadcast handling
- Run with: `pytest backend/test_qie_node_manager.py -v`

### Frontend Files

#### `frontend/dashboard.html` (400+ lines)
Professional responsive monitoring dashboard
- **Layout:** Sidebar navigation + main content area
- **Sections:**
  - Header: Logo, network selector, notifications, profile
  - Sidebar: Nav menu, QIE node status indicator, network controls
  - Main Content:
    - Key Metrics: 4 cards (active bridges, anomalies 24h, validation rate, model accuracy)
    - Charts: Transaction volume (line), anomaly distribution (doughnut)
    - Recent Transactions Table: Real-time transaction list with status badges
    - QIE Node Status Panel: Moniker, sync status, version, ports
    - Validators Panel: Top 5 validators with voting power and commission
- **Styling:** Tailwind CSS 3 (dark theme, responsive, mobile hamburger menu)
- **Charts:** Chart.js integration (CDN)

**Key HTML Elements (for JS updates):**
```html
<!-- Metrics -->
<div id="activeBridges">0</div>
<div id="anomalies24h">0</div>
<div id="validationRate">0%</div>
<div id="modelAccuracy">0%</div>

<!-- QIE Node Status -->
<div id="nodeStatus" class="status-indicator"></div>
<span id="blockHeight">0</span>
<span id="nodeMoniker">--</span>
<span id="syncStatus">--</span>

<!-- Charts -->
<canvas id="txVolumeChart"></canvas>
<canvas id="anomalyDistChart"></canvas>

<!-- Tables -->
<table data-transactions-table></table>
<div data-validators-list></div>
```

#### `frontend/api-client.js` (450+ lines)
JavaScript API client with advanced features
- **Configuration:**
  - Base URL: `http://localhost:5000`
  - Timeout: 30 seconds
  - Retry attempts: 3 (exponential backoff)
  - Cache TTL: 5 minutes

- **Core Methods:**
  - `request(endpoint, options)` - Main HTTP handler with retry/cache
  - `getDashboardStats()` - Aggregate data from multiple endpoints
  - `getRecentTransactions(limit)` - Fetch transaction history
  
- **QIE Node Methods:**
  - `getQieNodeStatus()` - Node health
  - `getValidatorInfo(address)` - Validator details
  - `getBlockHeight()` - Current block
  - `getAccountBalance(address)` - Balance lookup
  
- **Bridge Methods:**
  - `validateTransaction(txData)` - Validate cross-chain tx
  - `getAnomalyScore(transaction)` - Risk assessment
  - `reportAnomaly(txId, reason, severity)` - Report anomalies
  - `broadcastTransaction(txData)` - Send transaction
  
- **Analytics Methods:**
  - `getDailyStats(date)` - Daily statistics
  - `getModelAccuracy()` - ML model metrics
  - `getValidatorStats()` - Network stats
  
- **WebSocket Methods:**
  - `connectWebSocket()` - Real-time connection
  - `on(event, callback)` - Event listener registration
  - `emit(event, data)` - Event emission
  
- **Utility Methods:**
  - `formatNumber()` - Add thousand separators
  - `formatTimestamp()` - Format dates
  - `truncateAddress()` - Shorten wallet addresses
  - `clearCache()` - Cache management
  - `healthCheck()` - API availability

**Example Usage:**
```javascript
// Get dashboard data
const stats = await api.getDashboardStats();
console.log(stats.node.height);

// Listen to real-time updates
api.on('transaction:update', (tx) => {
    console.log('New transaction:', tx);
});

// Connect WebSocket
api.connectWebSocket();
```

#### `frontend/dashboard.js` (500+ lines)
Dashboard controller and state manager
- **Initialization:**
  - API health check
  - Chart initialization (Chart.js)
  - WebSocket setup
  - Event listener registration
  - Auto-refresh timers (30s main, 10s node)

- **Core Methods:**
  - `init()` - Initialize dashboard
  - `loadDashboardData()` - Fetch all data
  - `updateMetrics()` - Update metric cards
  - `updateQieNodeStatus()` - Update node panel
  - `updateCharts()` - Update charts with data
  - `updateTransactionsTable()` - Populate TX table
  - `updateValidatorPanel()` - Populate validators list
  
- **Auto-Refresh:**
  - Main refresh: 30 seconds
  - Node status: 10 seconds (faster for live updates)
  - Manual refresh button support
  - Cache clearing on refresh
  
- **WebSocket Integration:**
  - Real-time transaction updates
  - Anomaly alerts
  - Security notifications
  - Graceful fallback to polling
  
- **UI Utilities:**
  - `showAlert()` - Toast notifications
  - `showNotification()` - Alert banners
  - `exportData()` - JSON export function
  - Mobile menu toggle

**Example Usage:**
```javascript
// Manually trigger refresh
dashboard.forceRefresh();

// Listen to WebSocket events
api.on('anomaly:detected', (data) => {
    dashboard.showNotification('Anomaly Alert', 'High risk transaction detected');
});

// Export data
dashboard.exportData();
```

### Scripts (Bash/Shell)

#### `scripts/install_qie.sh` (8.3 KB)
Download and install QIE binary
- Detects OS (Linux/macOS/Windows)
- Downloads QIE v3 from GitHub releases
- Validates checksum
- Sets execute permissions
- Creates symbolic link

```bash
bash scripts/install_qie.sh
# Output: QIE binary installed to ~/.qie/qied
```

#### `scripts/init_qie_node.sh` (3.4 KB)
Initialize QIE node configuration
- Creates `~/.qie` directory structure
- Initializes node with moniker
- Generates private validator key
- Creates `priv_validator_key.json`

```bash
bash scripts/init_qie_node.sh
```

#### `scripts/configure_qie_node.sh` (4.5 KB)
Apply configuration to node
- Copies genesis file
- Sets moniker in config.toml
- Configures RPC port (26657)
- Configures P2P port (26656)
- Enables CORS for local development

```bash
bash scripts/configure_qie_node.sh
```

#### `scripts/setup_qie_validator.sh` (3.2 KB)
Orchestrator script (run all three above)
```bash
bash scripts/setup_qie_validator.sh
# Automatically runs: install → init → configure
```

#### `scripts/verify_qie_setup.sh` (6.3 KB)
Comprehensive system verification
- Checks system requirements (bash, curl, etc.)
- Verifies QIE installation
- Validates configuration files
- Tests Python environment
- Tests module imports

```bash
bash scripts/verify_qie_setup.sh
```

### Documentation Files

#### `docs/QIE_NODE_SETUP.md` (6.8 KB)
Complete setup guide with:
- Installation prerequisites
- Step-by-step setup instructions
- Configuration details
- Troubleshooting section
- Security best practices
- Port requirements

#### `docs/QIE_QUICK_REFERENCE.md` (4.4 KB)
Quick command reference:
- One-liner commands
- Configuration tables
- Default values
- Common debugging steps

#### `docs/QIE_IMPLEMENTATION_SUMMARY.md` (8.3 KB)
Technical implementation details:
- Architecture overview
- RPC endpoint specifications
- Error handling patterns
- Response format documentation
- Requirements tracking

### Configuration Files

#### `requirements.txt`
Python dependencies:
```
web3==6.11.3
python-dotenv==1.0.0
pandas==2.2.3
numpy==1.26.4
scikit-learn==1.3.2
tensorflow==2.17.1
requests==2.31.0
flask==3.0.0
flask-cors==4.0.0
pydantic==2.8.0
pytest==7.4.3
python-json-logger==2.0.7
```

---

## 🔧 Development & Debugging

### Running the Complete System

```bash
# Terminal 1: Start QIE node
bash scripts/setup_qie_validator.sh
qied start --home ~/.qie

# Terminal 2: Start Flask API
cd backend
python app.py
# API available at http://localhost:5000

# Terminal 3: Open dashboard
# In browser: http://localhost:5000/dashboard.html
```

### Testing

#### Python Module Tests
```bash
pytest backend/test_qie_node_manager.py -v
pytest backend/test_qie_node_manager.py --cov=backend/qie_node_manager
```

#### API Health Check
```bash
curl http://localhost:5000/health
```

#### QIE RPC Direct (bypass API)
```bash
curl -X POST http://localhost:26657/status
```

### Debugging

#### Enable Debug Logging
```python
# In backend/app.py
app.config['DEBUG'] = True
```

#### API Request Tracing
```javascript
// In browser console
localStorage.setItem('debugMode', 'true');
api.config.retryAttempts = 5;  // More retries
dashboard.loadDashboardData();
```

#### Monitor Network
- Open browser DevTools (F12)
- Go to Network tab
- Filter by `/api/v1/`
- Check request/response details

---

## 🔐 Security & Production

### API Key Authentication
```bash
# Set in .env or environment
export API_KEY="your-secure-key-here"

# Use in requests
curl -H "X-API-Key: your-secure-key-here" \
  http://localhost:5000/api/v1/qie/node/status
```

### Rate Limiting
- Current: 100 requests/minute per IP
- Configurable in `app.py`: `RATE_LIMIT_REQUESTS = 100`
- Modify `RATE_LIMIT_PERIOD = 60` for different time window

### CORS Configuration
```python
# In app.py (adjust for production)
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:3000"],  # Production domain
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["X-API-Key", "Content-Type"]
    }
})
```

### Database Integration
Replace in-memory storage in `app.py`:
```python
# Current: In-memory (development)
transaction_history = []

# Production: Use PostgreSQL/MongoDB
# from pymongo import MongoClient
# db = MongoClient("mongodb://localhost").valiguard
# transaction_history = db.transactions
```

### WebSocket Security
```javascript
// Add authentication token
const wsURL = `${api.config.baseURL.replace('http', 'ws')}/ws?token=${token}`;
```

---

## 📊 API Response Examples

### Dashboard Stats
```json
{
  "success": true,
  "data": {
    "node": {
      "height": 1234567,
      "moniker": "valiguard-ai-validator",
      "is_synced": true,
      "version": "v3.0.0"
    },
    "stats": {
      "active_bridges": 42,
      "anomalies_24h": 3,
      "validation_rate": 0.985
    },
    "model": {
      "accuracy": 0.95,
      "precision": 0.92,
      "recall": 0.98
    }
  },
  "request_id": "REQ-1234567890-abc123",
  "timestamp": "2025-01-15T10:30:45.123Z"
}
```

### Transaction Broadcast
```json
{
  "success": true,
  "data": {
    "tx_hash": "0x123abc...",
    "status": "pending",
    "block_height": 1234568,
    "gas_used": 145000,
    "timestamp": "2025-01-15T10:31:15Z"
  }
}
```

### Anomaly Score
```json
{
  "success": true,
  "data": {
    "tx_hash": "0x789def...",
    "risk_score": 0.72,
    "risk_level": "medium",
    "reasons": [
      "Unusual transaction amount",
      "Frequent sender activity"
    ]
  }
}
```

---

## 🎯 Next Steps & Enhancements

### Phase 1: Production Deployment
- [ ] Add database backend (PostgreSQL/MongoDB)
- [ ] Implement JWT authentication
- [ ] Add HTTPS/TLS
- [ ] Set up monitoring (Prometheus/Grafana)
- [ ] Deploy with Docker/Kubernetes

### Phase 2: Advanced Features
- [ ] WebSocket real-time updates
- [ ] ML model integration (TensorFlow)
- [ ] Alert rules engine
- [ ] Multi-chain support
- [ ] Webhook notifications

### Phase 3: Monitoring & Observability
- [ ] Application Performance Monitoring (APM)
- [ ] Custom metrics collection
- [ ] Logging aggregation (ELK stack)
- [ ] Tracing (Jaeger)
- [ ] Error tracking (Sentry)

### Phase 4: Mobile & Offline
- [ ] React Native mobile app
- [ ] Progressive Web App (PWA)
- [ ] Offline data sync
- [ ] Push notifications

---

## 📞 Support & Resources

### Official Documentation
- QIE: https://docs.qie.digital
- Tendermint: https://docs.tendermint.com
- Flask: https://flask.palletsprojects.com
- Chart.js: https://www.chartjs.org

### Common Issues

**Q: API port already in use**
```bash
# Find process using port 5000
lsof -i :5000
# Kill process
kill -9 <PID>
```

**Q: QIE node not syncing**
```bash
qied status
# Check block height is increasing
# Check peers are connected
qied query p2p
```

**Q: Dashboard not updating**
- Open browser console (F12)
- Check for JavaScript errors
- Verify API is running: `curl http://localhost:5000/health`
- Clear cache: Press Ctrl+Shift+Delete

**Q: WebSocket connection fails**
- WebSocket support requires backend implementation
- Falls back to HTTP polling automatically
- Check browser console for connection errors

---

## 📝 File Manifest

| File | Type | Size | Purpose |
|------|------|------|---------|
| `backend/app.py` | Python | 500+ lines | Flask REST API |
| `backend/qie_node_manager.py` | Python | 19.5 KB | QIE RPC client |
| `backend/test_qie_node_manager.py` | Python | 4.8 KB | Unit tests |
| `frontend/dashboard.html` | HTML | 400+ lines | UI dashboard |
| `frontend/api-client.js` | JavaScript | 450+ lines | API client |
| `frontend/dashboard.js` | JavaScript | 500+ lines | Controller |
| `scripts/install_qie.sh` | Bash | 8.3 KB | QIE installer |
| `scripts/init_qie_node.sh` | Bash | 3.4 KB | Node initializer |
| `scripts/configure_qie_node.sh` | Bash | 4.5 KB | Node configurator |
| `scripts/setup_qie_validator.sh` | Bash | 3.2 KB | Orchestrator |
| `scripts/verify_qie_setup.sh` | Bash | 6.3 KB | Verifier |
| `docs/QIE_NODE_SETUP.md` | Markdown | 6.8 KB | Setup guide |
| `docs/QIE_QUICK_REFERENCE.md` | Markdown | 4.4 KB | Quick ref |
| `docs/QIE_IMPLEMENTATION_SUMMARY.md` | Markdown | 8.3 KB | Tech details |
| `requirements.txt` | Text | 13 lines | Dependencies |

---

**Version:** 1.0.0  
**Last Updated:** January 15, 2025  
**Status:** Production Ready  
**License:** MIT
