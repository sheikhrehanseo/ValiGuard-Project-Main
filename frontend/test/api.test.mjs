import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('parallel expired requests all wait for one wallet authentication', async () => {
    const source = await readFile(new URL('../src/lib/api.js', import.meta.url), 'utf8');
    const api = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
    const storage = new Map([['valiguard_jwt', 'expired']]);
    globalThis.window = {};
    globalThis.localStorage = {
        getItem: key => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, value),
        removeItem: key => storage.delete(key),
    };
    let nonceRequests = 0;
    globalThis.fetch = async (url, options) => {
        if (url.endsWith('/request-nonce')) {
            nonceRequests++;
            await new Promise(resolve => setTimeout(resolve, 20));
            return { ok: true, json: async () => ({ data: { nonce: 'nonce', message: 'sign' } }) };
        }
        if (url.endsWith('/verify')) return { ok: true, json: async () => ({ data: { token: 'fresh' } }) };
        return { status: options.headers.Authorization === 'Bearer fresh' ? 200 : 401 };
    };
    api.setWalletContext({ address: 'wallet', signMessage: async () => 'signature' });
    const results = await Promise.all([api.authedFetch('/one'), api.authedFetch('/two'), api.authedFetch('/three')]);
    assert.deepEqual(results.map(response => response.status), [200, 200, 200]);
    assert.equal(nonceRequests, 1);
    api.clearWalletContext();
    api.setToken(null);
    assert.equal((await api.authedFetch('/logged-out')).status, 401);
    assert.equal(nonceRequests, 1);
});
