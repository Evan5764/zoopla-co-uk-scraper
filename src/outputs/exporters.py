thonimport csv
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

logger = logging.getLogger("exporters")

def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

def _normalise_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert nested structures into JSON strings where necessary to keep
    tabular formats simple.
    """
    normalised: List[Dict[str, Any]] = []
    for record in records:
        flat: Dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, (dict, list)):
                flat[key] = json.dumps(value, ensure_ascii=False)
            else:
                flat[key] = value
        normalised.append(flat)
    return normalised

def export_json(records: List[Dict[str, Any]], path: Path) -> None:
    try:
        _ensure_dir(path.parent)
        with path.open("w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        logger.info("JSON export written to %s", path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to export JSON to %s: %s", path, exc)

def export_csv(records: List[Dict[str, Any]], path: Path) -> None:
    if not records:
        logger.info("No records to export to CSV (%s).", path)
        return

    try:
        _ensure_dir(path.parent)
        flat_records = _normalise_records(records)
        fieldnames = sorted({k for r in flat_records for k in r.keys()})

        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in flat_records:
                writer.writerow(row)

        logger.info("CSV export written to %s", path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to export CSV to %s: %s", path, exc)

def export_excel(records: List[Dict[str, Any]], path: Path) -> None:
    if not records:
        logger.info("No records to export to Excel (%s).", path)
        return

    try:
        import pandas as pd  # type: ignore[import-untyped]
    except ImportError as exc:  # noqa: BLE001
        logger.error(
            "pandas is required for Excel export but is not installed: %s",
            exc,
        )
        return

    try:
        _ensure_dir(path.parent)
        flat_records = _normalise_records(records)
        df = pd.DataFrame(flat_records)
        df.to_excel(path, index=False)
        logger.info("Excel export written to %s", path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to export Excel to %s: %s", path, exc)

def export_xml(records: List[Dict[str, Any]], path: Path) -> None:
    try:
        from xml.etree.ElementTree import Element, SubElement, ElementTree
    except ImportError as exc:  # noqa: BLE001
        logger.error("Failed to import XML modules: %s", exc)
        return

    root = Element("properties")

    for record in records:
        prop_el = SubElement(root, "property")
        for key, value in record.items():
            field = SubElement(prop_el, key)
            if isinstance(value, (dict, list)):
                field.text = json.dumps(value, ensure_ascii=False)
            elif value is not None:
                field.text = str(value)
            else:
                field.text = ""

    try:
        _ensure_dir(path.parent)
        tree = ElementTree(root)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        logger.info("XML export written to %s", path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to export XML to %s: %s", path, exc)

def export_rss(
    records: List[Dict[str, Any]],
    path: Path,
    metadata: Dict[str, str],
) -> None:
    try:
        from xml.etree.ElementTree import Element, SubElement, ElementTree
    except ImportError as exc:  # noqa: BLE001
        logger.error("Failed to import XML modules for RSS: %s", exc)
        return

    channel_title = metadata.get("title", "Zoopla Property Feed")
    channel_link = metadata.get("link", "")
    channel_description = metadata.get("description", "")

    rss = Element("rss")
    rss.set("version", "2.0")

    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = channel_title
    SubElement(channel, "link").text = channel_link
    SubElement(channel, "description").text = channel_description

    for record in records:
        item = SubElement(channel, "item")
        title = record.get("title") or "Property listing"
        link = record.get("url") or channel_link
        description_parts: List[str] = []

        price = record.get("price")
        if price:
            description_parts.append(f"Price: {price}")

        address = record.get("address")
        if address:
            description_parts.append(f"Address: {address}")

        agent = record.get("agent")
        if agent:
            description_parts.append(f"Agent: {agent}")

        features = record.get("features")
        if features:
            if isinstance(features, list):
                features_text = ", ".join(str(f) for f in features)
            else:
                features_text = str(features)
            description_parts.append(f"Features: {features_text}")

        SubElement(item, "title").text = str(title)
        SubElement(item, "link").text = str(link)
        SubElement(item, "description").text = " | ".join(description_parts)

    try:
        _ensure_dir(path.parent)
        tree = ElementTree(rss)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        logger.info("RSS export written to %s", path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to export RSS to %s: %s", path, exc)

def export_datasets(
    all_listings: List[Dict[str, Any]],
    new_listings: List[Dict[str, Any]],
    delisted_listings: List[Dict[str, Any]],
    output_dir: Path,
    base_filename: str,
    formats: List[str],
    rss_metadata: Dict[str, str],
) -> None:
    """
    Export datasets in the requested formats. For each format, the following
    files are written (if there is data):

    - {base_filename}.{ext}               -> all current listings
    - {base_filename}_new.{ext}           -> new listings (if monitoring)
    - {base_filename}_delisted.{ext}      -> delisted listings (if monitoring)
    """
    output_dir = output_dir.resolve()
    _ensure_dir(output_dir)

    for fmt in formats:
        fmt = fmt.lower()
        if fmt == "json":
            export_json(all_listings, output_dir / f"{base_filename}.json")
            if new_listings:
                export_json(
                    new_listings,
                    output_dir / f"{base_filename}_new.json",
                )
            if delisted_listings:
                export_json(
                    delisted_listings,
                    output_dir / f"{base_filename}_delisted.json",
                )
        elif fmt == "csv":
            export_csv(all_listings, output_dir / f"{base_filename}.csv")
            if new_listings:
                export_csv(
                    new_listings,
                    output_dir / f"{base_filename}_new.csv",
                )
            if delisted_listings:
                export_csv(
                    delisted_listings,
                    output_dir / f"{base_filename}_delisted.csv",
                )
        elif fmt in {"xls", "xlsx", "excel"}:
            # Always write .xlsx for Excel
            export_excel(all_listings, output_dir / f"{base_filename}.xlsx")
            if new_listings:
                export_excel(
                    new_listings,
                    output_dir / f"{base_filename}_new.xlsx",
                )
            if delisted_listings:
                export_excel(
                    delisted_listings,
                    output_dir / f"{base_filename}_delisted.xlsx",
                )
        elif fmt == "xml":
            export_xml(all_listings, output_dir / f"{base_filename}.xml")
            if new_listings:
                export_xml(
                    new_listings,
                    output_dir / f"{base_filename}_new.xml",
                )
            if delisted_listings:
                export_xml(
                    delisted_listings,
                    output_dir / f"{base_filename}_delisted.xml",
                )
        elif fmt == "rss":
            export_rss(all_listings, output_dir / f"{base_filename}.rss", rss_metadata)
        else:
            logger.warning("Unsupported export format requested: %s", fmt)