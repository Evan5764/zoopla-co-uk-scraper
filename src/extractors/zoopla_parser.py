thonimport logging
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger("zoopla_parser")

@dataclass
class PropertyListing:
    title: str
    uprn: Optional[str]
    address: Optional[str]
    epc: Optional[str]
    epcRating: Optional[str]
    bedrooms: Optional[int]
    bathrooms: Optional[int]
    livingroom: Optional[int]
    price: Optional[str]
    description: Optional[str]
    coordinates: Optional[Dict[str, Any]]
    category: Optional[str]
    type: Optional[str]
    agent: Optional[str]
    agentPhone: Optional[str]
    images: List[str]
    priceHistory: List[Dict[str, Any]]
    pointsOfInterest: List[Dict[str, Any]]
    propertyType: Optional[str]
    postalCode: Optional[str]
    features: List[str]
    url: Optional[str]

class ZooplaScraper:
    """
    A lightweight HTML scraper tailored to Zoopla listing pages.

    It focuses on robustness and graceful degradation: the scraper will attempt
    to extract as much information as possible, but will not fail outright if a
    specific field cannot be parsed.
    """

    def __init__(
        self,
        base_url: str = "https://www.zoopla.co.uk",
        user_agent: str = "ZooplaScraperBot/1.0",
        timeout: int = 10,
        request_delay_seconds: float = 1.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.request_delay_seconds = request_delay_seconds

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "en-GB,en;q=0.9",
            }
        )

    # ------------- HTTP helpers -------------

    def _safe_get(self, url: str) -> Optional[str]:
        try:
            logger.debug("Fetching URL: %s", url)
            resp = self.session.get(url, timeout=self.timeout)
            time.sleep(self.request_delay_seconds)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            logger.warning("Request failed for %s: %s", url, exc)
            return None

    # ------------- Public API -------------

    def scrape_search(
        self,
        search_url: str,
        max_results: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Scrape a Zoopla search result page and return a list of property
        dictionaries.

        If max_results is provided, the scraper will stop once the limit is
        reached. Pagination support can be added by the caller by passing
        multiple URLs.
        """
        html = self._safe_get(search_url)
        if html is None:
            return []

        soup = BeautifulSoup(html, "lxml")
        cards = self._find_listing_cards(soup)

        listings: List[Dict[str, Any]] = []
        for card in cards:
            if max_results is not None and len(listings) >= max_results:
                break

            summary = self._parse_listing_card(card, search_url)
            if not summary.url:
                listings.append(asdict(summary))
                continue

            # Fetch details for richer metadata
            detail_html = self._safe_get(summary.url)
            if detail_html:
                detail_soup = BeautifulSoup(detail_html, "lxml")
                self._enrich_from_detail_page(summary, detail_soup)

            listings.append(asdict(summary))

        return listings

    # ------------- Parsing helpers -------------

    def _find_listing_cards(self, soup: BeautifulSoup) -> Iterable[Tag]:
        """
        Try multiple strategies to locate listing containers on the page.
        """
        selectors = [
            "article[data-testid*=listing]",
            "div[data-testid*=listing]",
            "div[class*=ListingCard]",
            "article",
        ]
        for sel in selectors:
            cards = soup.select(sel)
            if cards:
                logger.debug("Found %d cards with selector '%s'", len(cards), sel)
                return cards
        logger.debug("No listing cards found using predefined selectors.")
        return []

    def _parse_listing_card(
        self,
        card: Tag,
        base_page_url: str,
    ) -> PropertyListing:
        title = self._extract_text(
            card,
            selectors=[
                "h2[data-testid*=listing-title]",
                "h2",
                "h3",
            ],
        )

        price = self._extract_text(
            card,
            selectors=[
                "p[data-testid*=listing-price]",
                "div[data-testid*=listing-price]",
                "span[class*=price]",
            ],
        )

        address = self._extract_text(
            card,
            selectors=[
                "p[data-testid*=listing-description]",
                "address",
                "span[class*=address]",
            ],
        )

        # Detect detail URL
        url = None
        link_tag = card.find("a", href=True)
        if link_tag:
            url = self._normalize_url(link_tag["href"], base_page_url)

        category = None
        type_ = None
        property_type = None
        category_text = self._extract_text(
            card,
            selectors=["span[data-testid*=badge]", "span[class*=category]"],
        )
        if category_text:
            lowered = category_text.lower()
            if "rent" in lowered:
                category = "rent"
            elif "sale" in lowered or "buy" in lowered:
                category = "sale"

        # Attempt to guess property type
        property_type_text = self._extract_text(
            card,
            selectors=["span[class*=property-type]", "span[data-testid*=property-type]"],
        )
        if property_type_text:
            property_type = property_type_text.strip()
            type_ = property_type

        agent = self._extract_text(
            card,
            selectors=["p[data-testid*=listing-agent]", "span[class*=agent]"],
        )

        bedrooms = self._extract_int_from_text(
            card,
            ["li[data-testid*=bed]", "span[class*=bedrooms]"],
        )
        bathrooms = self._extract_int_from_text(
            card,
            ["li[data-testid*=bath]", "span[class*=bathrooms]"],
        )

        listing = PropertyListing(
            title=title or "",
            uprn=None,
            address=address,
            epc=None,
            epcRating=None,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            livingroom=None,
            price=price,
            description=None,
            coordinates=None,
            category=category,
            type=type_,
            agent=agent,
            agentPhone=None,
            images=[],
            priceHistory=[],
            pointsOfInterest=[],
            propertyType=property_type,
            postalCode=None,
            features=[],
            url=url,
        )

        return listing

    def _enrich_from_detail_page(
        self,
        listing: PropertyListing,
        soup: BeautifulSoup,
    ) -> None:
        """
        Use the property detail page to populate richer fields such as
        description, EPC rating, agent phone, features, and coordinates.
        """
        description = self._extract_text(
            soup,
            selectors=[
                "p[data-testid*=listing-description]",
                "div[data-testid*=description] p",
                "div[class*=description] p",
            ],
        )
        if description:
            listing.description = description.strip()

        # EPC rating and image if present
        epc_rating = self._extract_text(
            soup,
            selectors=[
                "span[data-testid*=epc-rating]",
                "span[class*=epc-rating]",
            ],
        )
        if epc_rating:
            listing.epcRating = epc_rating.strip()

        epc_img = soup.select_one("img[src*='epc']")
        if epc_img and epc_img.get("src"):
            listing.epc = self._normalize_url(epc_img["src"], self.base_url)

        # Agent phone
        agent_phone = self._extract_text(
            soup,
            selectors=[
                "a[href^='tel:']",
                "span[class*=agent-phone]",
            ],
        )
        if agent_phone:
            listing.agentPhone = agent_phone.strip()

        # Address
        address = self._extract_text(
            soup,
            selectors=[
                "address",
                "p[data-testid*=address]",
            ],
        )
        if address:
            listing.address = address.strip()

        # Postal code heuristic
        listing.postalCode = self._extract_postcode(address or "")

        # Features list
        features: List[str] = []
        for sel in [
            "ul[data-testid*=features] li",
            "ul[class*=features] li",
        ]:
            for li in soup.select(sel):
                text = li.get_text(strip=True)
                if text and text not in features:
                    features.append(text)
        listing.features = features

        # Images
        images: List[str] = []
        for img in soup.select("img[src]"):
            src = img["src"]
            if any(x in src for x in ["lid.zoocdn.com", "zoocdn.com"]):
                images.append(self._normalize_url(src, self.base_url))
        listing.images = list(dict.fromkeys(images))

        # Coordinates from script tags (very heuristic)
        coords = self._extract_coordinates_from_scripts(soup)
        if coords:
            listing.coordinates = coords

    # ------------- Low-level extraction helpers -------------

    def _extract_text(self, root: Tag, selectors: List[str]) -> Optional[str]:
        for sel in selectors:
            el = root.select_one(sel)
            if el:
                text = el.get_text(" ", strip=True)
                if text:
                    return text
        return None

    def _extract_int_from_text(self, root: Tag, selectors: List[str]) -> Optional[int]:
        text = self._extract_text(root, selectors)
        if not text:
            return None
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None

    def _normalize_url(self, href: str, base: str) -> str:
        href = href.strip()
        if href.startswith("//"):
            parsed_base = urlparse(base)
            href = f"{parsed_base.scheme}:{href}"
        return urljoin(base, href)

    def _extract_postcode(self, text: str) -> Optional[str]:
        if not text:
            return None
        # Very simple UK postcode heuristic: look for pattern like "SE1 2AA"
        import re

        pattern = r"\b[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2}\b"
        match = re.search(pattern, text.upper())
        if match:
            return match.group(0).strip()
        return None

    def _extract_coordinates_from_scripts(
        self,
        soup: BeautifulSoup,
    ) -> Optional[Dict[str, Any]]:
        import json
        import re

        scripts = soup.find_all("script")
        for script in scripts:
            content = script.string or ""
            if not content:
                continue
            if "latitude" in content and "longitude" in content:
                try:
                    # Try JSON object detection
                    json_candidates = re.findall(r"\{.*?\}", content, re.DOTALL)
                    for candidate in json_candidates:
                        if "latitude" in candidate and "longitude" in candidate:
                            data = json.loads(candidate)
                            lat = data.get("latitude")
                            lon = data.get("longitude")
                            if lat and lon:
                                return {
                                    "latitude": str(lat),
                                    "longitude": str(lon),
                                }
                except Exception:  # noqa: BLE001
                    # Best-effort fallback with regex
                    lat_match = re.search(
                        r"latitude['\"]?\s*:\s*([0-9.\-]+)",
                        content,
                    )
                    lon_match = re.search(
                        r"longitude['\"]?\s*:\s*([0-9.\-]+)",
                        content,
                    )
                    if lat_match and lon_match:
                        return {
                            "latitude": lat_match.group(1),
                            "longitude": lon_match.group(1),
                        }
        return None