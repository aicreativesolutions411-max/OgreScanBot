from __future__ import annotations

import aiohttp


class PumpFunClient:
    def __init__(self) -> None:
        timeout = aiohttp.ClientTimeout(total=10)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        await self._session.close()

    async def metadata(self, mint: str) -> dict:
        url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
        try:
            async with self._session.get(url) as response:
                if response.status >= 400:
                    return {}
                data = await response.json(content_type=None)
        except aiohttp.ClientError:
            return {}
        return data if isinstance(data, dict) else {}
