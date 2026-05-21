"""
API HTTP cliente usando httpx sync dentro de asyncio.to_thread().
Soluciona el bug de httpx AsyncClient que se cuelga con URLs encriptadas.
"""
import asyncio
from typing import Any

import httpx

from .crypto import encrypt_api_payload, encrypt_token

BASE_URL = "https://apiconsultapublicarnpdno.segob.gob.mx/api"


class ConsultaAPIHttpx:
    def __init__(self):
        self._client = httpx.Client(timeout=httpx.Timeout(120, connect=30))
        self._token = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self._client.close()

    def _headers(self, with_auth: bool = True) -> dict:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://consultapublicarnpdno.segob.gob.mx",
            "Referer": "https://consultapublicarnpdno.segob.gob.mx/",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
            ),
        }
        if with_auth and self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _new_client(self):
        self._client.close()
        self._client = httpx.Client(timeout=httpx.Timeout(120, connect=30))

    async def refresh(self):
        """Nuevo cliente httpx + nuevo token = sesion fresca para el servidor."""
        self._new_client()
        await self.get_token()

    async def get_token(self) -> str:
        enc = encrypt_token()
        url = f"{BASE_URL}/t/{enc}"
        resp = await asyncio.to_thread(
            self._client.post, url, headers=self._headers(with_auth=False)
        )
        data = resp.json()
        if data.get("result", {}).get("success"):
            self._token = data["result"]["data"]
            return self._token
        raise RuntimeError(f"Token error: {data}")

    async def get_count(self, filtros: dict) -> int:
        enc = encrypt_api_payload("get_paginador", filtros, self._token)
        url = f"{BASE_URL}/p/{enc}"
        resp = await asyncio.to_thread(
            self._client.post,
            url,
            json={"rows": 10, "page": 1},
            headers=self._headers(),
        )
        data = resp.json()
        result = data.get("result", {})
        if result.get("success"):
            value = result["data"]
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    pass
            if isinstance(value, dict):
                if not value:
                    return 0
                if "code" in value:
                    raise RuntimeError(f"Count error: {value.get('code')}")
                if "total" in value:
                    return int(value["total"])
                if "data" in value and isinstance(value["data"], (int, float)):
                    return int(value["data"])
                raise RuntimeError(f"Count unexpected dict: {value}")
            raise RuntimeError(f"Count unexpected type: {type(value)} = {value}")
        raise RuntimeError(f"Count error: {data}")

    async def search_page(
        self, filtros: dict, rows: int = 1000, page: int = 1
    ) -> dict[str, Any]:
        enc = encrypt_api_payload("get_info_matriz", filtros, self._token)
        url = f"{BASE_URL}/p/{enc}"
        resp = await asyncio.to_thread(
            self._client.post,
            url,
            json={"rows": rows, "page": page},
            headers=self._headers(),
        )
        data = resp.json()
        if data.get("result", {}).get("success"):
            return data["result"]["data"]
        raise RuntimeError(f"Search error: {data}")
