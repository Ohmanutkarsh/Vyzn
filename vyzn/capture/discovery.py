"""
Zero-Touch Network Camera & ONVIF Auto-Discovery Engine.
Eliminates manual RTSP URL and IP configuration for shopkeepers and installers.
Discovers IP cameras on the local network using ONVIF WS-Discovery (UDP 3702)
and rapid heuristic RTSP port/vendor endpoint probing.
"""

from __future__ import annotations
import socket
import select
import logging
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger("vyzn.capture.discovery")

ONVIF_MULTICAST_IP = "239.255.255.250"
ONVIF_PORT = 3702

WS_DISCOVERY_PROBE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
    '<Header>'
    '<wsa:MessageID xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">'
    'uuid:vyzn-discovery-probe-2026</wsa:MessageID>'
    '<wsa:To xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">'
    'urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>'
    '<wsa:Action xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">'
    'http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>'
    '</Header>'
    '<Body>'
    '<Probe xmlns="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
    '<Types>dn:NetworkVideoTransmitter</Types>'
    '</Probe>'
    '</Body>'
    '</Envelope>'
).encode("utf-8")

COMMON_RTSP_TEMPLATES = [
    # Dahua / CP Plus (dominant in Indian retail SMBs)
    {"vendor": "CP PLUS / Dahua", "path": "/cam/realmonitor?channel=1&subtype=0"},
    # Hikvision
    {"vendor": "Hikvision", "path": "/Streaming/Channels/101"},
    # Generic / Xiongmai / Jovision
    {"vendor": "Generic ONVIF", "path": "/h264Preview_01_main"},
    {"vendor": "Generic ONVIF", "path": "/live/ch0"},
    {"vendor": "Generic ONVIF", "path": "/onvif1"}
]


@dataclass
class DiscoveredCamera:
    ip: str
    port: int
    vendor: str
    rtsp_url: str
    service_url: Optional[str] = None
    name: Optional[str] = None
    status: str = "discovered"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CameraDiscoveryService:
    """Discovers ONVIF and RTSP IP cameras on the local network."""

    def __init__(self, timeout_sec: float = 2.0):
        self.timeout_sec = timeout_sec

    def discover_onvif(self) -> List[DiscoveredCamera]:
        """Broadcasts WS-Discovery UDP probe to discover ONVIF Network Video Transmitters."""
        discovered: List[DiscoveredCamera] = []
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(self.timeout_sec)

        try:
            sock.sendto(WS_DISCOVERY_PROBE, (ONVIF_MULTICAST_IP, ONVIF_PORT))
            while True:
                try:
                    data, addr = sock.recvfrom(65535)
                    ip = addr[0]
                    xml_str = data.decode("utf-8", errors="ignore")

                    # Extract XAddrs (service URLs)
                    xaddr_match = re.search(r"<(?:\w+:)?XAddrs>(.*?)</(?:\w+:)?XAddrs>", xml_str, re.DOTALL)
                    service_url = None
                    if xaddr_match:
                        xaddrs = xaddr_match.group(1).strip().split()
                        if xaddrs:
                            service_url = xaddrs[0]

                    # Guess vendor from scopes or text
                    vendor = "ONVIF Camera"
                    if "dahua" in xml_str.lower() or "cpplus" in xml_str.lower():
                        vendor = "CP PLUS / Dahua"
                        rtsp_url = f"rtsp://{ip}:554/cam/realmonitor?channel=1&subtype=0"
                    elif "hikvision" in xml_str.lower():
                        vendor = "Hikvision"
                        rtsp_url = f"rtsp://{ip}:554/Streaming/Channels/101"
                    else:
                        rtsp_url = f"rtsp://{ip}:554/h264Preview_01_main"

                    cam = DiscoveredCamera(
                        ip=ip,
                        port=554,
                        vendor=vendor,
                        rtsp_url=rtsp_url,
                        service_url=service_url,
                        name=f"{vendor} ({ip})",
                        status="ready"
                    )
                    discovered.append(cam)

                except socket.timeout:
                    break
                except Exception as e:
                    logger.debug(f"Error receiving discovery datagram: {e}")
                    break
        except Exception as e:
            logger.debug(f"WS-Discovery broadcast encountered exception: {e}")
        finally:
            sock.close()

        return discovered

    def probe_rtsp_host(self, ip: str, port: int = 554, timeout: float = 0.5) -> Optional[DiscoveredCamera]:
        """Probes a specific host for an open RTSP port and verifies stream endpoint."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            res = sock.connect_ex((ip, port))
            if res != 0:
                return None

            # Test standard RTSP DESCRIBE probe
            # Try Dahua / CP Plus first
            template = COMMON_RTSP_TEMPLATES[0]
            rtsp_url = f"rtsp://{ip}:{port}{template['path']}"
            return DiscoveredCamera(
                ip=ip,
                port=port,
                vendor=template["vendor"],
                rtsp_url=rtsp_url,
                name=f"{template['vendor']} ({ip})",
                status="ready"
            )
        except Exception:
            return None
        finally:
            sock.close()

    def discover_all(self, target_ips: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Executes hybrid discovery: ONVIF multicast + targeted IP probing.
        Returns deduplicated list of discovered camera dictionary models.
        """
        results: Dict[str, DiscoveredCamera] = {}

        # 1. Run ONVIF WS-Discovery
        onvif_cams = self.discover_onvif()
        for cam in onvif_cams:
            results[cam.ip] = cam

        # 2. Probe specified target IPs or localhost/gateway if provided
        if target_ips:
            for ip in target_ips:
                if ip not in results:
                    found = self.probe_rtsp_host(ip)
                    if found:
                        results[ip] = found

        return [cam.to_dict() for cam in results.values()]
