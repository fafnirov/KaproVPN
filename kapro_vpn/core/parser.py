"""Parsers for proxy share URLs into sing-box outbound dicts.

Supported schemes: trojan, vless, vmess, ss (Shadowsocks), hysteria2 / hy2,
wireguard. Each parser returns a `(display_name, outbound_dict)` tuple, where
`outbound_dict` is shaped for direct insertion into sing-box's
`outbounds[]` array (the `tag` field is added by the config generator).

WireGuard is special because there's no widely-adopted share-URL standard:
configs are distributed as .conf INI files. We accept either:
  - the raw INI text (auto-detected by the `[Interface]` header) pasted
    into any URL/config input, OR
  - a `wireguard://<base64-encoded-conf>#name` URL we synthesise from
    the INI on save, so storage is round-trip stable and looks like
    every other config in the list.
"""
from __future__ import annotations

import base64
import configparser
import io
import json
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse, quote


class ParseError(ValueError):
    pass


@dataclass
class ProxyConfig:
    """User-facing record of a parsed proxy URL."""
    name: str
    protocol: str            # trojan, vless, vmess, shadowsocks, hysteria2
    raw_url: str
    outbound: dict[str, Any] = field(default_factory=dict)


# --- helpers --------------------------------------------------------------

def _b64_decode_padded(s: str) -> bytes:
    """Base64-decode, fixing padding and supporting URL-safe alphabet."""
    s = s.strip().replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    return base64.b64decode(s + "=" * pad)


def _first_qs(qs: dict[str, list[str]], *keys: str, default: str = "") -> str:
    for k in keys:
        if k in qs and qs[k]:
            return qs[k][0]
    return default


def _split_alpn(value: str) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def _truthy(value: str) -> bool:
    return value.lower() in ("1", "true", "yes")


def _build_tls(
    server_name: str,
    insecure: bool = False,
    alpn: Optional[list[str]] = None,
    utls_fp: str = "",
    reality_pbk: str = "",
    reality_sid: str = "",
) -> dict[str, Any]:
    tls: dict[str, Any] = {"enabled": True}
    if server_name:
        tls["server_name"] = server_name
    if insecure:
        tls["insecure"] = True
    if alpn:
        tls["alpn"] = alpn
    if utls_fp:
        tls["utls"] = {"enabled": True, "fingerprint": utls_fp}
    if reality_pbk:
        tls["reality"] = {
            "enabled": True,
            "public_key": reality_pbk,
            "short_id": reality_sid or "",
        }
    return tls


def _build_transport(
    net: str,
    qs: dict[str, list[str]],
    host_header_fallback: str = "",
) -> Optional[dict[str, Any]]:
    """Build sing-box transport object from query string. None = plain TCP."""
    net = (net or "tcp").lower()
    if net in ("", "tcp", "raw"):
        return None
    if net == "ws":
        path = _first_qs(qs, "path", default="/")
        host = _first_qs(qs, "host", default=host_header_fallback)
        t: dict[str, Any] = {"type": "ws", "path": path}
        if host:
            t["headers"] = {"Host": host}
        return t
    if net == "grpc":
        service = _first_qs(qs, "serviceName", "servicename", "path")
        return {"type": "grpc", "service_name": service}
    if net in ("h2", "http"):
        host = _first_qs(qs, "host", default=host_header_fallback)
        path = _first_qs(qs, "path", default="/")
        t = {"type": "http", "path": path}
        if host:
            t["host"] = [h.strip() for h in host.split(",") if h.strip()]
        return t
    if net == "httpupgrade":
        path = _first_qs(qs, "path", default="/")
        host = _first_qs(qs, "host", default=host_header_fallback)
        t = {"type": "httpupgrade", "path": path}
        if host:
            t["host"] = host
        return t
    return None


# --- trojan ---------------------------------------------------------------

def parse_trojan(url: str) -> ProxyConfig:
    u = urlparse(url)
    if u.scheme != "trojan":
        raise ParseError(f"Not a trojan URL: {url}")
    if not u.username or not u.hostname or not u.port:
        raise ParseError("trojan URL needs password@host:port")

    qs = parse_qs(u.query)
    sni = _first_qs(qs, "sni", "peer", default=u.hostname)
    alpn = _split_alpn(_first_qs(qs, "alpn"))
    insecure = _truthy(_first_qs(qs, "allowInsecure", "insecure", default="0"))
    utls_fp = _first_qs(qs, "fp")
    net = _first_qs(qs, "type", default="tcp")

    outbound: dict[str, Any] = {
        "type": "trojan",
        "server": u.hostname,
        "server_port": u.port,
        "password": unquote(u.username),
        "tls": _build_tls(sni, insecure=insecure, alpn=alpn, utls_fp=utls_fp),
    }
    transport = _build_transport(net, qs, host_header_fallback=u.hostname)
    if transport:
        outbound["transport"] = transport

    name = unquote(u.fragment) or f"trojan-{u.hostname}"
    return ProxyConfig(name=name, protocol="trojan", raw_url=url, outbound=outbound)


# --- vless ----------------------------------------------------------------

def parse_vless(url: str) -> ProxyConfig:
    u = urlparse(url)
    if u.scheme != "vless":
        raise ParseError(f"Not a vless URL: {url}")
    if not u.username or not u.hostname or not u.port:
        raise ParseError("vless URL needs uuid@host:port")

    qs = parse_qs(u.query)
    security = _first_qs(qs, "security", default="none").lower()
    sni = _first_qs(qs, "sni", "peer", default=u.hostname)
    alpn = _split_alpn(_first_qs(qs, "alpn"))
    insecure = _truthy(_first_qs(qs, "allowInsecure", "insecure", default="0"))
    utls_fp = _first_qs(qs, "fp")
    flow = _first_qs(qs, "flow")
    net = _first_qs(qs, "type", default="tcp")

    outbound: dict[str, Any] = {
        "type": "vless",
        "server": u.hostname,
        "server_port": u.port,
        "uuid": u.username,
    }
    if flow:
        outbound["flow"] = flow

    if security in ("tls", "reality"):
        reality_pbk = _first_qs(qs, "pbk") if security == "reality" else ""
        reality_sid = _first_qs(qs, "sid") if security == "reality" else ""
        outbound["tls"] = _build_tls(
            sni, insecure=insecure, alpn=alpn,
            utls_fp=utls_fp,
            reality_pbk=reality_pbk, reality_sid=reality_sid,
        )

    transport = _build_transport(net, qs, host_header_fallback=u.hostname)
    if transport:
        outbound["transport"] = transport

    name = unquote(u.fragment) or f"vless-{u.hostname}"
    return ProxyConfig(name=name, protocol="vless", raw_url=url, outbound=outbound)


# --- vmess ----------------------------------------------------------------

def parse_vmess(url: str) -> ProxyConfig:
    if not url.startswith("vmess://"):
        raise ParseError(f"Not a vmess URL: {url}")
    payload = url[len("vmess://"):]

    try:
        decoded = _b64_decode_padded(payload).decode("utf-8", errors="replace")
        data = json.loads(decoded)
    except Exception as e:
        raise ParseError(f"vmess payload is not base64 JSON: {e}") from e

    server = str(data.get("add") or "").strip()
    port = int(data.get("port") or 0)
    uuid = str(data.get("id") or "").strip()
    if not (server and port and uuid):
        raise ParseError("vmess JSON missing add/port/id")

    alter_id = int(data.get("aid") or 0)
    security = str(data.get("scy") or "auto")
    net = str(data.get("net") or "tcp")
    tls_flag = str(data.get("tls") or "").lower() == "tls"
    sni = str(data.get("sni") or data.get("host") or server)
    alpn = _split_alpn(str(data.get("alpn") or ""))
    utls_fp = str(data.get("fp") or "")

    outbound: dict[str, Any] = {
        "type": "vmess",
        "server": server,
        "server_port": port,
        "uuid": uuid,
        "security": security,
        "alter_id": alter_id,
    }
    if tls_flag:
        outbound["tls"] = _build_tls(sni, alpn=alpn, utls_fp=utls_fp)

    qs_like: dict[str, list[str]] = {
        "path": [str(data.get("path", "/"))],
        "host": [str(data.get("host", ""))],
        "serviceName": [str(data.get("path", ""))],
    }
    transport = _build_transport(net, qs_like, host_header_fallback=server)
    if transport:
        outbound["transport"] = transport

    name = str(data.get("ps") or f"vmess-{server}")
    return ProxyConfig(name=name, protocol="vmess", raw_url=url, outbound=outbound)


# --- shadowsocks ----------------------------------------------------------

def parse_shadowsocks(url: str) -> ProxyConfig:
    if not url.startswith("ss://"):
        raise ParseError(f"Not an ss URL: {url}")

    after = url[len("ss://"):]
    name = ""
    if "#" in after:
        after, frag = after.split("#", 1)
        name = unquote(frag)

    query = ""
    if "?" in after:
        after, query = after.split("?", 1)

    method = password = host = ""
    port = 0

    if "@" in after:
        # SIP002: base64-or-plain(method:password) @ host:port
        userinfo, hostport = after.rsplit("@", 1)
        try:
            decoded = _b64_decode_padded(userinfo).decode("utf-8")
            if ":" in decoded:
                method, password = decoded.split(":", 1)
            else:
                method, password = decoded, ""
        except Exception:
            # Some clients URL-encode method:password without base64
            decoded = unquote(userinfo)
            if ":" in decoded:
                method, password = decoded.split(":", 1)
        if ":" in hostport:
            host, port_s = hostport.rsplit(":", 1)
            port = int(port_s)
    else:
        # Legacy: base64(method:password@host:port)
        try:
            decoded = _b64_decode_padded(after).decode("utf-8")
        except Exception as e:
            raise ParseError(f"ss legacy payload is not base64: {e}") from e
        if "@" not in decoded or ":" not in decoded:
            raise ParseError("ss legacy URL malformed")
        cred, hostport = decoded.rsplit("@", 1)
        if ":" in cred:
            method, password = cred.split(":", 1)
        host, port_s = hostport.rsplit(":", 1)
        port = int(port_s)

    if not (method and host and port):
        raise ParseError("ss URL missing method/host/port")

    outbound: dict[str, Any] = {
        "type": "shadowsocks",
        "server": host,
        "server_port": port,
        "method": method,
        "password": password,
    }

    qs = parse_qs(query)
    plugin = _first_qs(qs, "plugin")
    if plugin:
        if ";" in plugin:
            name_part, opts = plugin.split(";", 1)
            outbound["plugin"] = name_part
            outbound["plugin_opts"] = opts
        else:
            outbound["plugin"] = plugin

    return ProxyConfig(
        name=name or f"ss-{host}", protocol="shadowsocks",
        raw_url=url, outbound=outbound,
    )


# --- hysteria2 ------------------------------------------------------------

def parse_hysteria2(url: str) -> ProxyConfig:
    u = urlparse(url)
    if u.scheme not in ("hysteria2", "hy2"):
        raise ParseError(f"Not a hysteria2 URL: {url}")
    if not u.hostname or not u.port:
        raise ParseError("hysteria2 URL needs host:port")

    qs = parse_qs(u.query)
    password = unquote(u.username) if u.username else _first_qs(qs, "auth")
    sni = _first_qs(qs, "sni", "peer", default=u.hostname)
    alpn = _split_alpn(_first_qs(qs, "alpn", default="h3"))
    insecure = _truthy(_first_qs(qs, "insecure", default="0"))
    obfs = _first_qs(qs, "obfs")
    obfs_password = _first_qs(qs, "obfs-password")

    outbound: dict[str, Any] = {
        "type": "hysteria2",
        "server": u.hostname,
        "server_port": u.port,
        "password": password,
        "tls": _build_tls(sni, insecure=insecure, alpn=alpn or ["h3"]),
    }
    if obfs:
        outbound["obfs"] = {"type": obfs, "password": obfs_password}

    name = unquote(u.fragment) or f"hy2-{u.hostname}"
    return ProxyConfig(name=name, protocol="hysteria2", raw_url=url, outbound=outbound)


# --- wireguard ------------------------------------------------------------

def looks_like_wireguard_conf(text: str) -> bool:
    """True if `text` looks like a WG .conf (has the [Interface] header).

    Cheap precheck so we can detect WG before scheme-dispatch and avoid
    the "Unsupported scheme 'https'" trap for users pasting INI content
    into the wrong field.
    """
    return "[Interface]" in text and "PrivateKey" in text


def _parse_wg_conf(conf_text: str) -> dict[str, Any]:
    """Parse WireGuard INI .conf text into a structured dict.

    Handles the standard wg-quick fields:
      [Interface] PrivateKey, Address, DNS, MTU
      [Peer]      PublicKey, PresharedKey, Endpoint, AllowedIPs, PersistentKeepalive

    Returns the data in a shape close to xray's wireguard outbound
    settings — caller just spreads it into the outbound JSON.
    """
    # configparser is strict by default about duplicate sections and the
    # like — wg-quick files have exactly one [Interface] and one [Peer]
    # for the common case but multiple [Peer]s are legal. We use the
    # `strict=False` toggle so multi-peer files don't error here.
    cp = configparser.RawConfigParser(strict=False)
    try:
        cp.read_file(io.StringIO(conf_text))
    except configparser.Error as e:
        raise ParseError(f"Bad WireGuard config: {e}") from e

    if "Interface" not in cp.sections():
        raise ParseError("WireGuard config missing [Interface] section")
    if "Peer" not in cp.sections():
        raise ParseError("WireGuard config missing [Peer] section")

    iface = cp["Interface"]
    private_key = (iface.get("PrivateKey") or "").strip()
    if not private_key:
        raise ParseError("WireGuard [Interface] needs PrivateKey")

    addresses = [
        a.strip() for a in (iface.get("Address") or "").split(",") if a.strip()
    ]
    if not addresses:
        raise ParseError("WireGuard [Interface] needs Address")

    dns_servers = [
        d.strip() for d in (iface.get("DNS") or "").split(",") if d.strip()
    ]
    try:
        mtu = int(iface.get("MTU") or 1420)
    except ValueError:
        mtu = 1420

    peer = cp["Peer"]
    public_key = (peer.get("PublicKey") or "").strip()
    endpoint = (peer.get("Endpoint") or "").strip()
    if not public_key:
        raise ParseError("WireGuard [Peer] needs PublicKey")
    if not endpoint or ":" not in endpoint:
        raise ParseError("WireGuard [Peer] needs Endpoint host:port")

    server_host, _, server_port_s = endpoint.rpartition(":")
    try:
        server_port = int(server_port_s)
    except ValueError:
        raise ParseError(f"WireGuard Endpoint port not an int: {server_port_s!r}")

    allowed_ips = [
        a.strip() for a in (peer.get("AllowedIPs") or "0.0.0.0/0").split(",") if a.strip()
    ]
    preshared = (peer.get("PresharedKey") or "").strip()
    try:
        keepalive = int(peer.get("PersistentKeepalive") or 0)
    except ValueError:
        keepalive = 0

    return {
        "secret_key": private_key,
        "address": addresses,
        "dns": dns_servers,
        "mtu": mtu,
        "server": server_host,
        "server_port": server_port,
        "public_key": public_key,
        "preshared_key": preshared,
        "allowed_ips": allowed_ips,
        "keepalive": keepalive,
    }


def _wg_synthesize_url(conf_text: str, name: str) -> str:
    """Build the round-trip-stable `wireguard://...#name` URL we store.

    Base64-encoding the whole INI keeps the parsed dict perfectly
    re-derivable without inventing a custom share-URL grammar.
    """
    payload = base64.b64encode(conf_text.encode("utf-8")).decode("ascii")
    frag = quote(name)
    return f"wireguard://{payload}#{frag}"


def wg_conf_from_raw_url(raw_url: str) -> str:
    """Inverse of _wg_synthesize_url — decode back to the original .conf text.

    Used by the xray-config generator to re-parse fields when building
    the runtime config (so we don't have to thread the parsed dict
    through ProxyConfig.outbound).
    """
    if not raw_url.startswith("wireguard://"):
        raise ParseError("Not a wireguard:// URL")
    after = raw_url[len("wireguard://"):]
    payload, _, _ = after.partition("#")
    try:
        return _b64_decode_padded(payload).decode("utf-8")
    except Exception as e:
        raise ParseError(f"WireGuard URL payload not valid base64: {e}") from e


def parse_wireguard(url_or_conf: str) -> ProxyConfig:
    """Accept either raw INI .conf text or a wireguard://<base64>#name URL."""
    text = url_or_conf.strip()
    if text.startswith("wireguard://"):
        conf_text = wg_conf_from_raw_url(text)
        # Preserve the explicit name from the URL fragment, if any
        _, _, frag = text.partition("#")
        url_name = unquote(frag) if frag else ""
    else:
        if not looks_like_wireguard_conf(text):
            raise ParseError(
                "Not a WireGuard config — expected [Interface] section "
                "with PrivateKey, or a wireguard:// URL."
            )
        conf_text = text
        url_name = ""

    data = _parse_wg_conf(conf_text)

    # The outbound dict format is xray-flavoured (we don't translate to
    # sing-box style like the other parsers because we never had a
    # sing-box wireguard implementation). The xray config generator
    # spreads these fields directly.
    outbound: dict[str, Any] = {
        "type": "wireguard",
        "server": data["server"],
        "server_port": data["server_port"],
        "private_key": data["secret_key"],
        "peer_public_key": data["public_key"],
        "address": data["address"],
        "allowed_ips": data["allowed_ips"],
        "mtu": data["mtu"],
    }
    if data["preshared_key"]:
        outbound["preshared_key"] = data["preshared_key"]
    if data["keepalive"]:
        outbound["keepalive"] = data["keepalive"]
    if data["dns"]:
        outbound["dns"] = data["dns"]

    # Pick a friendly default name from the endpoint host. Users almost
    # always rename via the Settings textfield anyway.
    name = url_name or f"wg-{data['server']}"

    # Always store the canonical wireguard://<base64>#name form so the
    # config list serializes/deserializes round-trip cleanly.
    canonical_url = _wg_synthesize_url(conf_text, name)
    return ProxyConfig(name=name, protocol="wireguard",
                       raw_url=canonical_url, outbound=outbound)


# --- dispatcher -----------------------------------------------------------

_PARSERS = {
    "trojan": parse_trojan,
    "vless": parse_vless,
    "vmess": parse_vmess,
    "ss": parse_shadowsocks,
    "hysteria2": parse_hysteria2,
    "hy2": parse_hysteria2,
    "wireguard": parse_wireguard,
    "wg": parse_wireguard,
}


def parse(url: str) -> ProxyConfig:
    text = url.strip()
    # WireGuard .conf detection — must happen before scheme dispatch
    # because the raw INI doesn't start with `scheme://`.
    if looks_like_wireguard_conf(text):
        return parse_wireguard(text)

    scheme = text.split("://", 1)[0].lower() if "://" in text else ""
    parser = _PARSERS.get(scheme)
    if not parser:
        raise ParseError(
            f"Unsupported scheme '{scheme}'. "
            f"Expected one of: {', '.join(_PARSERS)}"
        )
    return parser(text)
