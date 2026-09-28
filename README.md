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

### Installation

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

3.  **Initialize Database**
    ```bash
    python backend/manage_db.py init
    python backend/manage_db.py seed
    ```

4.  **Setup QIE Validator**
    ```bash
    # Setup node
    python backend/qie_setup_manager.py setup
    
    # Register validator
    python backend/qie_validator_manager.py full
    ```

5.  **Run Backend**
    ```bash
    python backend/app.py
    ```

6.  **Run Frontend**
    ```bash
    cd frontend
    npm install
    npm run dev
    ```
    
    *The app will open at `http://localhost:3000`*

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