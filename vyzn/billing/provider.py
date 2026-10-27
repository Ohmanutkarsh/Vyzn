"""
PaymentProvider interface and ManualUpiProvider implementation for VYZN Netra.
Decouples payment generation behind a lightweight interface so gateways can replace it.
"""

from __future__ import annotations
import os
import io
import base64
import urllib.parse
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import qrcode


class PaymentProvider(ABC):
    """Abstract interface for payment generation."""

    @abstractmethod
    def build_payment(self, order: Dict[str, Any]) -> Dict[str, str]:
        """
        Builds payment payload for a given quota order.
        Returns:
            {
                "upi_link": str,
                "qr": str  # Base64 data URI or SVG
            }
        """
        pass


def generate_qr_data_uri(text: str) -> str:
    """Renders a text string into a clean base64 PNG data URI using qrcode."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


class ManualUpiProvider(PaymentProvider):
    """
    Personal UPI QR payment provider with manual verification.
    Formats UPI deeplink:
    upi://pay?pa=<UPI_VPA>&pn=<UPI_PAYEE_NAME>&am=<rupees, 2 decimals>&tn=<order_code>&cu=INR
    """

    def __init__(self, vpa: Optional[str] = None, payee_name: Optional[str] = None):
        self.vpa = (vpa or os.environ.get("UPI_VPA", "vyzn@upi")).strip()
        self.payee_name = (payee_name or os.environ.get("UPI_PAYEE_NAME", "VYZN Technologies")).strip()

    def build_payment(self, order: Dict[str, Any]) -> Dict[str, str]:
        # Rupee calculation from paise (2 decimal places)
        amount_paise = int(order.get("amount_paise", 0))
        amount_rupees = amount_paise / 100.0
        amount_str = f"{amount_rupees:.2f}"
        order_code = str(order.get("order_code", "")).strip()

        # URL-encoded query parameters
        params = {
            "pa": self.vpa,
            "pn": self.payee_name,
            "am": amount_str,
            "tn": order_code,
            "cu": "INR"
        }
        query_string = urllib.parse.urlencode(params)
        upi_link = f"upi://pay?{query_string}"

        qr_data_uri = generate_qr_data_uri(upi_link)
        return {
            "upi_link": upi_link,
            "qr": qr_data_uri
        }
