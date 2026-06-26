import logging
from collections.abc import Mapping
from html import escape
from xml.etree import ElementTree

import httpx

from sonosify.errors import UPnPError

_SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"

logger = logging.getLogger("sonosify.soap")


def build_envelope(service_urn: str, action: str, args: Mapping[str, object] | None = None) -> str:
    body = [
        '<?xml version="1.0"?>',
        f'<s:Envelope xmlns:s="{_SOAP_ENV_NS}" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">',
        "<s:Body>",
        f'<u:{action} xmlns:u="{escape(service_urn, quote=True)}">',
    ]
    for key, value in sorted((args or {}).items()):
        safe_key = _safe_tag(key)
        body.append(f"<{safe_key}>{escape(str(value), quote=False)}</{safe_key}>")
    body.extend([f"</u:{action}>", "</s:Body>", "</s:Envelope>"])
    return "".join(body)


def parse_response(raw: str | bytes) -> dict[str, str]:
    root = ElementTree.fromstring(raw)
    body = _find_by_local_name(root, "Body")
    if body is None or not list(body):
        return {}

    response = list(body)[0]
    return {_local_name(child.tag): "".join(child.itertext()) for child in list(response)}


def parse_upnp_error(raw: str | bytes) -> UPnPError | None:
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return None

    upnp = _find_by_local_name(root, "UPnPError")
    if upnp is None:
        return None

    code = ""
    description = ""
    for child in list(upnp):
        name = _local_name(child.tag)
        if name == "errorCode":
            code = (child.text or "").strip()
        elif name == "errorDescription":
            description = (child.text or "").strip()
    if not code and not description:
        return None
    return UPnPError(code=code, description=description)


async def soap_call(
    client: httpx.AsyncClient,
    endpoint_url: str,
    service_urn: str,
    action: str,
    args: Mapping[str, object] | None = None,
) -> dict[str, str]:
    envelope = build_envelope(service_urn, action, args)
    logger.debug("-> POST %s %s#%s\n%s", endpoint_url, service_urn, action, envelope)
    response = await client.post(
        endpoint_url,
        content=envelope,
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"{service_urn}#{action}"',
        },
    )
    logger.debug("<- %s %s#%s\n%s", response.status_code, service_urn, action, response.text)
    if response.status_code == httpx.codes.OK:
        return parse_response(response.content)

    if response.status_code == httpx.codes.INTERNAL_SERVER_ERROR:
        error = parse_upnp_error(response.content)
        if error is not None:
            raise error

    response.raise_for_status()
    return {}


def _find_by_local_name(root: ElementTree.Element, local_name: str) -> ElementTree.Element | None:
    for element in root.iter():
        if _local_name(element.tag) == local_name:
            return element
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _safe_tag(tag: str) -> str:
    return "".join(char for char in tag if char.isalnum() or char in "_-")
