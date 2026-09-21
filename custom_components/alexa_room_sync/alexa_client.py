"""Alexa smart-home group calls over the Alexa Devices integration's session."""

from __future__ import annotations

from typing import Any

from yarl import URL

from .reconcile import AlexaEndpoint, AlexaGroup

URI_GROUPS = "api/phoenix/group"
URI_GRAPHQL = "nexus/v1/graphql"
ECHO_CATEGORIES = {"ALEXA_VOICE_ENABLED"}
APP_USER_AGENT = "AmazonWebView/AmazonAlexa/2.2.663733.0/iOS/18.5/iPhone"

ENDPOINTS_QUERY = """query Endpoints {
  endpoints {
    items {
      friendlyName
      displayCategories { primary { value } }
      legacyAppliance { applianceId friendlyName isEnabled }
    }
  }
}"""


class UnexpectedResponseError(Exception):
    """Alexa returned a shape this client does not understand."""


class AlexaGroupClient:
    """Read inventory and write groups using an already authenticated AmazonEchoApi."""

    def __init__(self, api: Any) -> None:
        """Borrow the http wrapper and session state from the Alexa Devices API object."""
        self._http = api._http_wrapper  # noqa: SLF001
        self._state = api._session_state_data  # noqa: SLF001

    def _url(self, path: str) -> URL:
        return URL.joinpath(self._state.alexa_website_url, path)

    async def _get(self, path: str) -> Any:
        _, resp = await self._http.session_request("GET", self._url(path))
        return await self._http.response_to_json(resp, path)

    # The nexus GraphQL endpoint only answers to the Alexa app user agent.
    async def _graphql(self, operation: str, query: str) -> Any:
        _, resp = await self._http.session_request(
            "POST",
            self._url(URI_GRAPHQL),
            input_data={"operationName": operation, "query": query},
            json_data=True,
            extended_headers={"User-Agent": APP_USER_AGENT},
        )
        return await self._http.response_to_json(resp, operation)

    # Group writes come back 200 with an empty or non-JSON body; only the status matters.
    async def _write(self, method: str, path: str, payload: Any) -> Any:
        _, resp = await self._http.session_request(method, self._url(path), input_data=payload, json_data=True)
        try:
            return await self._http.response_to_json(resp, path, content_type=None)
        except ValueError:
            return {}

    async def endpoints(self) -> list[AlexaEndpoint]:
        """Every smart-home endpoint Alexa knows about."""
        data = await self._graphql("Endpoints", ENDPOINTS_QUERY)
        items = data.get("data", {}).get("endpoints", {}).get("items")
        if not isinstance(items, list):
            raise UnexpectedResponseError(f"Unexpected endpoints response: {str(data)[:300]}")
        result = []
        for item in items:
            legacy = item.get("legacyAppliance") or {}
            appliance_id = legacy.get("applianceId")
            if not appliance_id:
                continue
            category = ((item.get("displayCategories") or {}).get("primary") or {}).get("value")
            result.append(
                AlexaEndpoint(
                    appliance_id=appliance_id,
                    name=item.get("friendlyName") or legacy.get("friendlyName") or appliance_id,
                    is_echo=category in ECHO_CATEGORIES,
                    enabled=legacy.get("isEnabled") is not False,
                )
            )
        return result

    async def raw_groups(self) -> Any:
        """The untouched group response, for diagnostics."""
        return await self._get(URI_GROUPS)

    async def groups(self) -> list[AlexaGroup]:
        """Alexa rooms and device groups."""
        data = await self.raw_groups()
        items = data.get("applianceGroups") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise UnexpectedResponseError(f"Unexpected group response: {str(data)[:300]}")
        result = []
        for group in items:
            group_id = (group.get("applianceGroupIdentifier") or {}).get("value") or group.get("groupId") or group.get("id")
            name = group.get("applianceGroupName") or group.get("name")
            appliance_ids = group.get("applianceIds", group.get("applianceGroupMembers"))
            if not group_id or not name or not isinstance(appliance_ids, list):
                raise UnexpectedResponseError(f"Group record has an unexpected shape: {str(group)[:300]}")
            result.append(AlexaGroup(id=group_id, name=name, appliance_ids=list(appliance_ids)))
        return result

    async def create_group(self, name: str, appliance_ids: list[str]) -> str | None:
        """Create a room; returns its id when Alexa includes one in the response."""
        data = await self._write("POST", URI_GROUPS, {"name": name, "type": "SPACE", "applianceIds": appliance_ids})
        if not isinstance(data, dict):
            return None
        return (data.get("applianceGroupIdentifier") or {}).get("value") or data.get("groupId") or data.get("id")

    async def update_group(self, group_id: str, name: str, appliance_ids: list[str]) -> None:
        """Replace a room's name and full membership."""
        await self._write("PUT", f"{URI_GROUPS}/{group_id}", {"name": name, "applianceIds": appliance_ids})
