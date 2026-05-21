"""
API HTTP client usando httpcloak para fingerprint de navegador.
"""

import json
from typing import Any

import httpcloak

from .crypto import encrypt_api_payload, encrypt_token

BASE_URL = "https://apiconsultapublicarnpdno.segob.gob.mx/api"


class ConsultaAPI:
    def __init__(self, preset: str = "chrome-latest"):
        self.session = httpcloak.Session(preset=preset)
        self._token = None

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

    def get_token(self) -> str:
        """
        Obtiene un JWT de sesion. Replica LA() del frontend:
        POST /api/t/{encrypted} sin body.
        """
        enc = encrypt_token()
        url = f"{BASE_URL}/t/{enc}"
        resp = self.session.post(url, headers=self._headers(with_auth=False))
        data = resp.json()
        if data.get("result", {}).get("success"):
            self._token = data["result"]["data"]
            return self._token
        raise RuntimeError(f"Token error: {data}")

    def get_municipios(self, estado_id: str) -> list[dict]:
        """
        Obtiene municipios para un estado. Replica Y7() del frontend:
        POST /api/p/{encrypted} con body {"id": estado_id}
        """
        enc = encrypt_api_payload("municipios", None, self._token)
        url = f"{BASE_URL}/p/{enc}"
        resp = self.session.post(
            url,
            json={"id": estado_id},
            headers=self._headers(),
        )
        data = resp.json()
        if data.get("result", {}).get("success"):
            return data["result"]["data"]
        raise RuntimeError(f"Municipios error: {data}")

    def get_count(self, filtros: dict) -> int:
        """
        Obtiene el total de registros. Replica Rf() del frontend:
        POST /api/p/{encrypted} con body {rows, page}
        """
        enc = encrypt_api_payload("get_paginador", filtros, self._token)
        url = f"{BASE_URL}/p/{enc}"
        resp = self.session.post(
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
            if isinstance(value, dict) and "code" in value:
                raise RuntimeError(f"Count error: {value.get('code')} - {value}")
            return int(value)
        raise RuntimeError(f"Count error: {data}")

    def search_page(
        self, filtros: dict, rows: int = 50, page: int = 1
    ) -> dict[str, Any]:
        """
        Busqueda de registros (matriz). Replica d0() del frontend:
        POST /api/p/{encrypted} con body {rows, page}
        Los filtros van encriptados en la URL.
        """
        enc = encrypt_api_payload("get_info_matriz", filtros, self._token)
        url = f"{BASE_URL}/p/{enc}"
        resp = self.session.post(
            url,
            json={"rows": rows, "page": page},
            headers=self._headers(),
        )
        data = resp.json()
        if data.get("result", {}).get("success"):
            return data["result"]["data"]
        raise RuntimeError(f"Search error: {data}")

    def get_photo(
        self, idvictimadirecta: str, idreporte: int, iddependenciaorigen: int, sexo: str
    ) -> str | None:
        """
        Obtiene foto de la victima. Replica Ax() del frontend.
        """
        data_send = {
            "idvictimadirecta": idvictimadirecta,
            "idreporte": idreporte,
            "iddependenciaorigen": iddependenciaorigen,
            "sexo": sexo,
        }
        enc = encrypt_api_payload("get_foto_victima", data_send, self._token)
        url = f"{BASE_URL}/p/{enc}"
        resp = self.session.post(
            url,
            json={"dataSend": data_send},
            headers=self._headers(),
        )
        data = resp.json()
        if data.get("result", {}).get("success"):
            return data["result"]["data"]
        return None

    def close(self):
        self.session.close()
