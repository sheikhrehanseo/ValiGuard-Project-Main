# WebSocket Integration

The Flask backend exposes Socket.IO on the same origin as the REST API. The
Next.js dashboard connects only in `REAL` mode and keeps its five-second REST
poll as a fallback and reconciliation mechanism.

Connected clients join the `dashboard` room and receive these events after the
related database write has committed:

| Event | Payload purpose |
| --- | --- |
| `new_transaction` | A newly persisted bridge transaction |
| `new_anomaly` | The transaction's anomaly score, severity, and reason |
| `new_alert` | A medium, high, or critical anomaly alert |
| `node_status` | Periodic node health and block-height telemetry |
| `alert_resolved` | An alert resolution update |

`backend/socket_manager.py` is the sole publisher for this contract. The
ingestion worker reaches it through the app's post-persistence callback, so a
failed database write cannot create a phantom dashboard event.

When `VALIGUARD_INGESTION_WORKER=1` (the normal runtime setting), traffic sent
to `/api/v1/bridge/anomaly-score`, including
`scripts/generate_mock_traffic.py`, is handed to the ingestion worker before
scoring and persistence. This keeps simulator traffic on the same
worker -> database -> Socket.IO path as RPC transactions. Test imports may set
the worker flag to `0`; in that mode the endpoint retains its synchronous
scoring path.
