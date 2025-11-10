thonimport argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from extractors.zoopla_parser import ZooplaScraper
from extractors.utils_filters import (
    compute_deltas,
    deduplicate_listings,
    load_snapshot,
    save_snapshot,
)
from outputs.exporters import export_datasets

def setup_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def resolve_paths() -> Dict[str, Path]:
    src_dir = Path(__file__).resolve().parent
    project_root = src_dir.parent
    data_dir = project_root / "data"
    return {
        "src_dir": src_dir,
        "project_root": project_root,
        "data_dir": data_dir,
    }

def parse_args(default_inputs: Path, default_settings: Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Zoopla Real Estate Properties Scraper runner",
    )
    parser.add_argument(
        "--inputs",
        type=str,
        default=str(default_inputs),
        help="Path to inputs JSON file (search URLs and output formats).",
    )
    parser.add_argument(
        "--settings",
        type=str,
        default=str(default_settings),
        help="Path to settings JSON file (scraper configuration).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Optional override for output directory.",
    )
    parser.add_argument(
        "--max-per-search",
        type=int,
        default=None,
        help="Optional override for max listings per search.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        help="Logging level (DEBUG, INFO, WARNING, ERROR). Overrides settings.",
    )
    return parser.parse_args()

def build_scraper(settings: Dict[str, Any]) -> ZooplaScraper:
    base_url = settings.get("base_url", "https://www.zoopla.co.uk")
    user_agent = settings.get(
        "user_agent",
        "ZooplaScraperBot/1.0 (+https://bitbash.dev)",
    )
    timeout = settings.get("timeout", 10)
    delay = settings.get("request_delay_seconds", 1.5)
    return ZooplaScraper(
        base_url=base_url,
        user_agent=user_agent,
        timeout=timeout,
        request_delay_seconds=delay,
    )

def run_scraper(
    inputs_cfg: Dict[str, Any],
    settings: Dict[str, Any],
    paths: Dict[str, Path],
    cli_args: argparse.Namespace,
) -> None:
    logger = logging.getLogger("runner")

    search_urls: List[str] = inputs_cfg.get("search_urls") or []
    if not search_urls:
        logger.error("No search URLs provided in inputs configuration.")
        sys.exit(1)

    output_cfg = inputs_cfg.get("output", {})
    output_dir = (
        Path(cli_args.output_dir)
        if cli_args.output_dir
        else Path(output_cfg.get("directory", paths["data_dir"]))
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    formats: List[str] = output_cfg.get("formats", ["json"])
    formats = [f.lower() for f in formats]

    max_per_search = cli_args.max_per_search or inputs_cfg.get(
        "max_listings_per_search",
        200,
    )

    monitoring_enabled = bool(
        inputs_cfg.get("monitoring", False) or settings.get("monitoring", False)
    )

    snapshot_file = Path(
        settings.get("snapshot_file", paths["data_dir"] / "last_snapshot.json")
    )

    scraper = build_scraper(settings)

    all_listings: List[Dict[str, Any]] = []
    for url in search_urls:
        try:
            logger.info("Scraping listings from %s", url)
            listings = scraper.scrape_search(url, max_results=max_per_search)
            logger.info("Retrieved %d listings from %s", len(listings), url)
            all_listings.extend(listings)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to scrape from %s: %s", url, exc)

    if not all_listings:
        logger.warning("No listings collected from any search URL.")
        return

    unique_listings = deduplicate_listings(all_listings)
    logger.info(
        "Deduplicated %d listings down to %d unique entries.",
        len(all_listings),
        len(unique_listings),
    )

    previous_snapshot: List[Dict[str, Any]] = []
    new_listings: List[Dict[str, Any]] = []
    delisted_listings: List[Dict[str, Any]] = []

    if monitoring_enabled:
        logger.info("Monitoring mode enabled; computing deltas.")
        previous_snapshot = load_snapshot(snapshot_file)
        new_listings, delisted_listings = compute_deltas(
            current=unique_listings,
            previous=previous_snapshot,
        )
        logger.info(
            "Monitoring results: %d new listings, %d delisted.",
            len(new_listings),
            len(delisted_listings),
        )
        save_snapshot(snapshot_file, unique_listings)
    else:
        logger.info("Monitoring mode disabled; skipping delta computation.")

    base_filename = output_cfg.get("base_filename", "zoopla_properties")

    rss_metadata = {
        "title": "Zoopla Property Feed",
        "link": "https://www.zoopla.co.uk",
        "description": "Exported property listings from Zoopla scraper.",
    }

    export_datasets(
        all_listings=unique_listings,
        new_listings=new_listings,
        delisted_listings=delisted_listings,
        output_dir=output_dir,
        base_filename=base_filename,
        formats=formats,
        rss_metadata=rss_metadata,
    )
    logger.info("Export completed. Files written to: %s", output_dir.resolve())

def main() -> None:
    paths = resolve_paths()
    default_inputs = paths["data_dir"] / "inputs.sample.json"
    default_settings = paths["src_dir"] / "config" / "settings.example.json"

    args = parse_args(default_inputs, default_settings)

    try:
        inputs_cfg = load_json(Path(args.inputs))
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to load inputs config: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        settings = load_json(Path(args.settings))
    except FileNotFoundError:
        settings = {}
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to load settings config: {exc}", file=sys.stderr)
        sys.exit(1)

    log_level = args.log_level or settings.get("log_level", "INFO")
    setup_logging(log_level)

    run_scraper(inputs_cfg, settings, paths, args)

if __name__ == "__main__":
    main()