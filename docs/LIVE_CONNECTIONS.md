# Live mainnet monitoring

These fixes retain the proposal's node orchestration, mainnet/mempool ingestion,
ML risk scoring, alerts, WebSocket feed, bridge analytics, and historical auditing.
Node setup and validator registration tools remain available. Dashboard login
uses a MetaMask nonce signature followed by a JWT; no wallet password or private
key is requested by the application. The obsolete key-export helper was removed.

## Configured sources

| Purpose | Connection |
| --- | --- |
| Tendermint blocks, mempool, node status, voting power | `https://rpc.cosmos.directory/qie` |
| EVM blocks, receipts, pending transactions, balances | `https://rpc1mainnet.qie.digital` |
| Explorer transaction and token metadata | `https://mainnet.qie.digital/api/v2` |
| Staking data | `https://rest.cosmos.directory/qie` |
| Validator directory | `https://validators.cosmos.directory/chains/qie` |

The configured network is `qie_1990-1` (EVM chain ID `1990`). Official network
details: https://docs.qie.digital/getting-started-with-qie-blockchain/4.-access-mainnet-or-testnet

`QIE_RPC_PROTOCOL=tendermint` allows HTTPS gateways without assuming port 26657.
Use `http://localhost:26657` and `http://localhost:8545` to monitor your own node.
A public gateway's health describes that gateway, not a validator running locally.
TLS certificates are verified. Connection failures do not produce sample records.

## Run and verify

From the repository root:

```powershell
.\venv\Scripts\python.exe scripts/check_live_connections.py
.\venv\Scripts\python.exe start_project.py --no-browser
```

The checker only reads network data; it never opens the database or broadcasts a
transaction. Exit code 0 means all ten checks passed. An empty mempool or empty
block is a valid response. A failed check reports an error, not an empty success.

The launcher migrates the database before startup. Relative SQLite paths resolve
against the repository root, so migration and application processes use the same
file. Existing records are retained. Legacy amounts without reliable asset
metadata remain labelled unknown; new observations can enrich those records.

Open `http://localhost:3001`, connect MetaMask, and sign the login message. Protected
REST calls and the Socket.IO handshake require the JWT. Expired socket sessions
are disconnected and the frontend reauthenticates before reconnecting. The HTTP
simulator also signs in using a temporary wallet; run it only in explicit demo mode.

## Data meaning

- Amounts retain their asset symbol and contract address. Native QIE volume is
  summed separately from token quantities; route tables also display token totals.
- ML amount/frequency baselines are maintained separately for each asset.
- ML latency is measured by the backend. Peak observed TPS is the largest count
  of stored transactions in one second for the selected UTC day; it is not a claim
  about total network capacity. Unavailable metrics display an unavailable state.
- A missing model returns HTTP 503 with `MODEL_UNAVAILABLE` and `valid: null` from
  validation. It does not mark the transaction successful.
- Repeated external scoring requests cannot overwrite an already ingested hash.
- Block catch-up processes up to 100 consecutive blocks per poll, retains the
  remaining backlog, and advances only after yielded transactions are persisted.
  The current cursors are in memory; restart catch-up from the prior process is
  not yet durable. Explorer history is a recent feed, not a full-chain backfill.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest backend -q
cd frontend
npm test
npm run build
```

`pytest.ini` disables only Web3's unused `pytest_ethereum` plugin, whose automatic
import conflicts with the installed `eth_typing`. Application tests still run.
