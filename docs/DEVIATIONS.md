# Implementation Deviations

## Raw Tendermint Entries

ValiGuard stores undecoded mempool and block entries in raw-entry mode. The
worker does not perform Cosmos transaction decoding. It stores a SHA-256 hash
of the decoded raw bytes and leaves sender, receiver, value, source chain,
destination chain, and bridge ID NULL when those fields are unavailable.
`sender IS NULL` is the raw-entry marker. Unknown volume is mapped to `0.0`
only for feature extraction; it remains NULL in storage.

## Bridge Scope

Without transaction decoding, the worker monitors all QIE traffic rather than
filtering only bridge transactions. Bridge IDs are linked only when an
API-submitted sender or receiver matches a known bridge address. Bridge-specific
filtering remains future work.

## Migration Compatibility

The raw-entry nullable migration converts only empty sender/receiver strings to
NULL. Existing `value=0.0` and `QIE` chain labels are preserved because they may
be genuine historical values. Downgrading restores legacy sentinels and is
lossy for raw-entry rows.
