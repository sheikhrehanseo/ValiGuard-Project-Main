# ValiGuard AI 🛡️
> **Advanced QIE Blockchain Validator & Security Monitoring Dashboard**

![ValiGuard AI Dashboard](https://github.com/sunnyshin8/ValiGuard-AI/raw/main/frontend/public/dashboard-preview.png)

**ValiGuard AI** is a next-generation validator dashboard that combines real-time blockchain monitoring with AI-powered anomaly detection. It is designed to secure the QIE network by identifying suspicious transaction patterns across bridges.

### ✨ Key Features
*   **QIE Validator:** Full validator node setup and management
*   **Real-time Monitoring:** Track validator status, voting power, and uptime
*   **AI Anomaly Detection:** ML-powered transaction analysis for risk assessment
*   **Cross-Chain Analytics:** Visual insights into bridge traffic and liquidity
*   **Database Layer:** SQLAlchemy models for bridges, transactions, validators, alerts
*   **Live Transaction Feed:** Dynamic updates of mainnet activity

---

## 🚀 Quick Start

### Prerequisites
*   Python 3.12+
*   Node.js 16+
*   WSL2 (for Windows users)

### Installation & Setup

1.  **Clone the repository**
    ```bash
    git clone https://github.com/sunnyshin8/ValiGuard-AI.git
    cd ValiGuard-AI
    ```

2.  **Setup Python Environment**
    ```bash
    python -m venv venv
    venv\Scripts\activate  # Windows
    pip install -r requirements.txt
    ```

3.  **Setup Frontend Dependencies**
    ```bash
    cd frontend
    npm install
    cd ..
    ```

### ⚡ Run ValiGuard (Canonical One-Command Launcher)

The canonical way to launch the full stack (Flask backend on port 5000, Alembic migrations, Next.js frontend on port 3001, and optional live traffic simulation) is using the project venv Python:

```powershell
# Windows (canonical venv command)
.\venv\Scripts\python.exe start_project.py --demo --simulate
```

```bash
# Linux / WSL
./venv/bin/python start_project.py --demo --simulate
```

> **Note on Environment Robustness:** If `start_project.py` is invoked with another Python interpreter (e.g. `python start_project.py --demo --simulate`), it automatically detects the project `.\venv` and re-execs into it. If dependencies are missing, it runs an upfront preflight check with clear remediation instructions rather than crashing with a raw traceback.

**Available Launcher Flags:**
*   `--demo`: Runs without a live QIE node (node status reports offline honestly, no background RPC spam).
*   `--simulate`: Starts the HTTP traffic generator to simulate live mainnet transaction streams.
*   `--no-browser`: Prevents auto-opening the dashboard in your default browser.

---

### 🛠️ Alternative: Manual Service Startup

If you prefer initializing and running services individually:

1.  **Initialize Database**
    ```bash
    python backend/manage_db.py init
    python backend/manage_db.py seed
    ```

2.  **Setup QIE Validator**
    ```bash
    # Setup node
    python backend/qie_setup_manager.py setup
    
    # Register validator
    python backend/qie_validator_manager.py full
    ```

3.  **Run Backend**
    ```bash
    python backend/app.py
    ```

4.  **Run Frontend**
    ```bash
    cd frontend
    npm run dev
    ```

---

## 🏗️ Architecture

*   **Frontend:** Next.js, Tailwind CSS, React
*   **Backend:** Flask (Python), SQLAlchemy, Alembic
*   **Database:** SQLite (dev), PostgreSQL (prod)
*   **Blockchain:** QIE Network V3 Mainnet
*   **ML:** TensorFlow, scikit-learn
*   **Validator:** QIE Node (qied)

---

## 📚 Documentation

- [Database Schema](docs/DATABASE_SCHEMA.md)
- [QIE Validator Setup](docs/QIE_VALIDATOR_COMPLETE_GUIDE.md)
- [Implementation Guide](docs/IMPLEMENTATION_GUIDE.md)

---

## 🤝 Contributing

Contributions are welcome! Please open an issue or submit a pull request.

---

*Built with ❤️ for the QIE Community*