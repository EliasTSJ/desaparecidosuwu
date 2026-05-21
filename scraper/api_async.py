"""
API HTTP cliente asincrono usando httpcloak para fingerprint de navegador.
Usa los metodos *_async del Session para concurrencia nativa.
"""

import json
from typing import Any

import httpcloak

from .crypto import encrypt_api_payload, encrypt_token

BASE_URL = "https://apiconsultapublicarnpdno.segob.gob.mx/api"


class ConsultaAPIAsync:
    def __init__(self, preset: str = "chrome-latest"):
        self._session = httpcloak.Session(preset=preset)
        self._token = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self._session.close()

    def _headers(self, with_auth: bool = True) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://consultapublicarnpdno.segob.gob.mx",
            "Referer": "https://consultapublicarnpdno.segob.gob.mx/",
        }
        if with_auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def get_token(self) -> str:
        enc = encrypt_token()
        url = f"{BASE_URL}/t/{enc}"
        resp = await self._session.post_async(
            url,
            headers=self._headers(with_auth=False),
        )
        data = resp.json()
        if data.get("result", {}).get("success"):
            self._token = data["result"]["data"]
            return self._token
        raise RuntimeError(f"Token error: {data}")

    async def get_count(self, filtros: dict) -> int:
        enc = encrypt_api_payload("get_paginador", filtros, self._token)
        url = f"{BASE_URL}/p/{enc}"
        resp = await self._session.post_async(
            url,
            json_data={"rows": 10, "page": 1},
            headers=self._headers(),
        )
        data = resp.json()
        result = data.get("result", {})
        if result.get("success"):
            value = result["data"]
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, dict) and "code" in value:
                raise RuntimeError(f"Count error: {value.get('code')}")
            return int(value)
        raise RuntimeError(f"Count error: {data}")

    async def search_page(
        self, filtros: dict, rows: int = 200, page: int = 1
    ) -> dict[str, Any]:
        enc = encrypt_api_payload("get_info_matriz", filtros, self._token)
        url = f"{BASE_URL}/p/{enc}"
        resp = await self._session.post_async(
            url,
            json_data={"rows": rows, "page": page},
            headers=self._headers(),
        )
        data = resp.json()
        if data.get("result", {}).get("success"):
            return data["result"]["data"]
        raise RuntimeError(f"Search error: {data}")

    def refresh(self):
        """Refresca la sesion TLS: cierra conexiones pero mantiene cache TLS."""
        self._session.refresh()
