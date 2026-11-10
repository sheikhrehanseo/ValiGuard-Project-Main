import { formatUnits } from 'ethers';

// Always use the configured QIE backend. The wallet's selected chain can differ.
export async function fetchQieBalance(apiBase, address, fetcher = fetch) {
    const response = await fetcher(`${apiBase}/api/v1/qie/account/${address}`);
    const body = await response.json();
    if (!response.ok || !body.success || !body.data?.success) return null;
    const decimals = { aqie: 18, wei: 18, uqie: 6, qie: 0 }[body.data.denom?.toLowerCase()];
    if (decimals === undefined || body.data.balance == null) return null;
    return formatUnits(body.data.balance, decimals);
}
