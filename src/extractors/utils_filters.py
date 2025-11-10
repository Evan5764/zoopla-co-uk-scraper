thonimport json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("utils_filters")

def _build_id_key(
    listing: Dict[str, Any],
    id_fields: Tuple[str, ...],
) -> Optional[str]:
    for field in id_fields:
        value = listing.get(field)
        if value:
            return f"{field}:{value}"
    return None

def deduplicate_listings(
    listings: Iterable[Dict[str, Any]],
    id_fields: Tuple[str, ...] = ("uprn", "url"),
) -> List[Dict[str, Any]]:
    """
    Remove duplicate listings based on a prioritized list of identity fields.
    """
    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []

    for listing in listings:
        key = _build_id_key(listing, id_fields)
        if key is None:
            # No identity fields, keep but log
            unique.append(listing)
            continue

        if key in seen:
            continue

        seen.add(key)
        unique.append(listing)

    return unique

def load_snapshot(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        logger.info("Snapshot file %s does not exist; treating as empty.", path)
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        logger.warning("Snapshot file %s did not contain a list; ignoring.", path)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load snapshot %s: %s", path, exc)
        return []

def save_snapshot(path: Path, listings: List[Dict[str, Any]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(listings, f, ensure_ascii=False, indent=2)
        logger.info("Snapshot saved to %s", path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to save snapshot %s: %s", path, exc)

def compute_deltas(
    current: List[Dict[str, Any]],
    previous: List[Dict[str, Any]],
    id_fields: Tuple[str, ...] = ("uprn", "url"),
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Compare current and previous listing snapshots and return a tuple:
    (new_listings, delisted_listings).
    """
    prev_index: Dict[str, Dict[str, Any]] = {}
    for listing in previous:
        key = _build_id_key(listing, id_fields)
        if key:
            prev_index[key] = listing

    curr_index: Dict[str, Dict[str, Any]] = {}
    for listing in current:
        key = _build_id_key(listing, id_fields)
        if key:
            curr_index[key] = listing

    new_listings: List[Dict[str, Any]] = []
    delisted_listings: List[Dict[str, Any]] = []

    for key, listing in curr_index.items():
        if key not in prev_index:
            new_listings.append(listing)

    for key, listing in prev_index.items():
        if key not in curr_index:
            delisted_listings.append(listing)

    return new_listings, delisted_listings