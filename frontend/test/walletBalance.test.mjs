import test from 'node:test';
import assert from 'node:assert/strict';
import { fetchQieBalance } from '../src/lib/walletBalance.mjs';

test('QIE balance uses the configured backend, even with another wallet network selected', async () => {
    globalThis.window = { ethereum: { request: () => { throw new Error('Wrong-chain wallet RPC must not be used'); } } };
    const balance = await fetchQieBalance('http://qie-backend', '0x123', async url => {
        assert.equal(url, 'http://qie-backend/api/v1/qie/account/0x123');
        return { ok: true, json: async () => ({ success: true, data: { success: true, denom: 'aqie', balance: '500000000000000000' } }) };
    });
    assert.equal(balance, '0.5');
    delete globalThis.window;
});

test('unavailable balances stay unknown, while a real zero remains zero', async () => {
    for (const data of [{ success: false, balance: '0', denom: 'aqie' }, { success: true, balance: '100', denom: 'other' }]) {
        assert.equal(await fetchQieBalance('', 'address', async () => ({ ok: true, json: async () => ({ success: true, data }) })), null);
    }
    assert.equal(await fetchQieBalance('', 'address', async () => ({ ok: true, json: async () => ({ success: true, data: { success: true, balance: '0', denom: 'aqie' } }) })), '0.0');
});
