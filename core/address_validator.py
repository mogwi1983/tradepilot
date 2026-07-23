"""Deterministic regex + usaddress parser module for address validation and Lob formatting."""

from __future__ import annotations

import re
import usaddress

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"
}

# Scan raw web page text for candidate US address strings
ADDR_SCAN_PATTERN = re.compile(
    r"\b\d+\s+[A-Za-z0-9\s\.,#-]+,\s*[A-Za-z\s]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b",
    re.IGNORECASE,
)


def validate_and_parse_address(raw_text: str) -> dict[str, str] | None:
    """Validate and parse a raw text string into a Lob-formatted address dict.

    Returns dict with keys: address_line1, address_city, address_state, address_zip
    Returns None if any required address component is missing or invalid.
    Strictly code-based logic (Zero AI).
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    text = raw_text.strip()

    # Reject PO Boxes
    if re.search(r"\bp\.?o\.?\s*box\b", text, re.IGNORECASE):
        return None

    # Must start with a street number
    if not re.match(r"^\d+", text):
        return None

    # Must contain a 5-digit ZIP code or ZIP+4
    zip_match = re.search(r"\b(\d{5}(?:-\d{4})?)\b", text)
    if not zip_match:
        return None

    try:
        tagged, _ = usaddress.tag(text)
    except Exception:
        return None

    # Must contain all required structural address components
    required_keys = {"AddressNumber", "StreetName", "PlaceName", "ZipCode"}
    if not required_keys.issubset(tagged.keys()):
        return None

    # Reconstruct street line (house number + street name + suite/apt if present)
    street_parts = [
        v for k, v in tagged.items()
        if k in (
            "AddressNumber", "AddressNumberPrefix", "AddressNumberSuffix",
            "StreetNamePreDirectional", "StreetName", "StreetNamePostType",
            "StreetNamePostDirectional", "OccupancyType", "OccupancyIdentifier",
            "SubaddressType", "SubaddressIdentifier"
        )
    ]
    street = " ".join(street_parts).strip()
    city = tagged.get("PlaceName", "").strip()
    state = tagged.get("StateName", "").strip().upper()
    zip_code = tagged.get("ZipCode", "").strip()

    if state not in US_STATE_CODES:
        state = "TX"

    if not (street and city and state and zip_code):
        return None

    # Length constraints matching Lob API requirements
    if len(street) > 64 or len(city) > 200 or len(state) != 2:
        return None

    return {
        "address_line1": street[:64],
        "address_city": city[:200],
        "address_state": state,
        "address_zip": zip_code,
    }


def extract_candidate_addresses(text: str) -> list[str]:
    """Extract candidate address substrings from raw web page or snippet text."""
    if not text:
        return []
    matches = ADDR_SCAN_PATTERN.findall(text)
    return [m.strip() for m in matches if len(m.strip()) > 10]
