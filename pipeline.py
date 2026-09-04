from __future__ import annotations

import sys
from pathlib import Path

# Colab: code lives here; data lives on Shared Drive (see paths.py).
COLAB_CODE_DIR = Path("/content/Daikin-Storage")


def _bootstrap_import_path() -> Path:
    """Ensure local project imports work for CLI and exec(open(...).read()) on Colab."""
    if COLAB_CODE_DIR.is_dir():
        root = str(COLAB_CODE_DIR)
        if root not in sys.path:
            sys.path.insert(0, root)

    project_root: Path | None = None
    try:
        project_root = Path(__file__).resolve().parent
    except NameError:
        project_root = None

    for candidate in (project_root, COLAB_CODE_DIR, Path.cwd()):
        if candidate is None or not candidate.is_dir():
            continue
        if (candidate / "rate_agreement_loader.py").exists():
            root = str(candidate)
            if root not in sys.path:
                sys.path.insert(0, root)
            return candidate

    raise ModuleNotFoundError(
        "Could not import project modules. Expected Python files in:\n"
        f"  {COLAB_CODE_DIR}\n\n"
        "Upload the Daikin-Storage project there, then run:\n"
        "  exec(open('/content/Daikin-Storage/pipeline.py').read())"
    )


PROJECT_DIR = _bootstrap_import_path()

import argparse
from dataclasses import dataclass

from rate_agreement_loader import (
    RATE_CARD_SHEET as AGREEMENT_SHEET,
    choose_rate_agreement_file,
    load_rate_agreement_to_processing,
)
from rate_card_loader import (
    choose_rate_card_file,
    load_rate_card_to_processing,
    print_rate_card_validation,
    validate_all_rate_cards,
)
from paths import ensure_colab_drive_mounted, print_path_layout
from rate_cost_applier import DEFAULT_SERVICES, apply_rate_card_to_agreement


@dataclass
class PipelineResult:
    rate_card_input: Path
    rate_card_processed: Path
    agreement_input: Path
    agreement_processed: Path
    output_file: Path
    updates: list[dict[str, object]]
    unmatched: list[dict[str, object]]


def run_pipeline(
    rate_card_path: Path | None = None,
    rate_card_sheets: list[str] | None = None,
    agreement_path: Path | None = None,
    services: list[str] | None = None,
    warehouse: str | int | None = None,
    *,
    interactive: bool = True,
) -> PipelineResult:
    """
    Run the full rate card processing pipeline end to end.

    1. Validate all rate card files in input/Rate Card
    2. Convert the selected rate card -> processing
    3. Load rate agreement 'Rate card' tab -> processing
    4. Apply rate card costs to the original agreement -> output
    """
    services = services or DEFAULT_SERVICES

    ensure_colab_drive_mounted()
    print_path_layout()
    print()

    print("=" * 60)
    print("STEP 1/4: Validate rate cards in input/Rate Card")
    print("=" * 60)
    validation_results = validate_all_rate_cards()
    print_rate_card_validation(validation_results)

    rate_card_input = rate_card_path or choose_rate_card_file()

    print("\n" + "=" * 60)
    print("STEP 2/4: Convert selected rate card to processing")
    print("=" * 60)
    rate_card_sheets_data, rate_card_processed = load_rate_card_to_processing(
        file_path=rate_card_input,
        sheet_names=rate_card_sheets,
    )

    print("\nConverted sheets:")
    for sheet_name, df in rate_card_sheets_data.items():
        print(f"  {sheet_name}: {len(df)} rows, {len(df.columns)} columns")
    print(f"Saved to: {rate_card_processed}")

    agreement_input = agreement_path or choose_rate_agreement_file()

    print("\n" + "=" * 60)
    print("STEP 3/4: Load rate agreement tab from input/Rate Agreement")
    print("=" * 60)
    agreement_df, agreement_processed = load_rate_agreement_to_processing(
        file_path=agreement_input,
        sheet_name=AGREEMENT_SHEET,
    )

    print(
        f"\nLoaded '{AGREEMENT_SHEET}' tab: "
        f"{len(agreement_df)} rows, {len(agreement_df.columns)} columns"
    )
    print(f"Saved to: {agreement_processed}")

    print("\n" + "=" * 60)
    print("STEP 4/4: Apply rate card costs to rate agreement")
    print("=" * 60)
    print(f"Using rate card: {rate_card_processed.name}")
    output_file, updates, unmatched = apply_rate_card_to_agreement(
        agreement_path=agreement_input,
        rate_card_path=rate_card_processed,
        sheet_name=AGREEMENT_SHEET,
        services=services,
        warehouse=warehouse,
        interactive=interactive,
    )

    print(f"\nApplied costs for services: {', '.join(services)}")
    if updates:
        print("Updated cells:")
        for item in updates:
            source = item.get("match_source", "name")
            if item.get("action") == "highlighted_yellow":
                print(
                    f"  Row {item['row']}, {item['category']}: "
                    f"highlighted yellow (value kept: {item['old_value']})"
                )
            else:
                print(
                    f"  Row {item['row']}, {item['category']} [{source}]: "
                    f"{item['old_value']} -> {item['new_value']}"
                )
    else:
        print("No values were updated.")

    if unmatched:
        print("\nCosts not updated (no mapping/rate match):")
        seen_categories: set[str] = set()
        for item in unmatched:
            category = str(item["category"])
            if category in seen_categories:
                continue
            seen_categories.add(category)
            print(f"  {category}")

    print(f"\nSaved to: {output_file}")

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"Rate card input:        {rate_card_input}")
    print(f"Rate card processing:   {rate_card_processed}")
    print(f"Agreement input:        {agreement_input}")
    print(f"Agreement processing:   {agreement_processed}")
    print(f"Final output:           {output_file}")

    return PipelineResult(
        rate_card_input=rate_card_input,
        rate_card_processed=rate_card_processed,
        agreement_input=agreement_input,
        agreement_processed=agreement_processed,
        output_file=output_file,
        updates=updates,
        unmatched=unmatched,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Daikin Storage rate card processing pipeline end to end.",
    )
    parser.add_argument(
        "--rate-card",
        type=Path,
        help="Path to the rate card xlsx in input/Rate Card (interactive if omitted).",
    )
    parser.add_argument(
        "--rate-card-sheets",
        nargs="+",
        help="Sheet name(s) to load from the rate card file (interactive if omitted).",
    )
    parser.add_argument(
        "--agreement",
        type=Path,
        help="Path to the rate agreement xlsx in input/Rate Agreement (interactive if omitted).",
    )
    parser.add_argument(
        "--services",
        nargs="+",
        default=DEFAULT_SERVICES,
        help=f"Service row(s) to update (default: {', '.join(DEFAULT_SERVICES)}).",
    )
    parser.add_argument(
        "--warehouse",
        help=(
            "Warehouse rate table to use when the rate card has multiple warehouse "
            "columns (name substring or Excel column index, e.g. Bordeaux or 8)."
        ),
    )
    parser.add_argument(
        "--drive-root",
        type=Path,
        help=(
            "Shared Drive data root (input/, processing/, output/). "
            "On Colab the default Shared Drive path is used automatically."
        ),
    )
    return parser.parse_args()


def configure_runtime(drive_root: Path | None = None) -> None:
    """Apply CLI path overrides."""
    from paths import configure

    configure(drive_root=drive_root, use_drive=True if drive_root is not None else None)


def _parse_warehouse_arg(value: str | None) -> str | int | None:
    if value is None:
        return None
    if value.isdigit():
        # CLI users think in 1-based Excel columns; convert to 0-based index.
        return int(value) - 1
    return value


def _has_cli_args() -> bool:
    flags = (
        "--rate-card",
        "--rate-card-sheets",
        "--agreement",
        "--drive-root",
        "--services",
        "--warehouse",
        "-h",
        "--help",
    )
    return any(flag in sys.argv for flag in flags)


def main() -> None:
    """Entry point for CLI and for exec(open('/content/Daikin-Storage/pipeline.py').read())."""
    if _has_cli_args():
        args = parse_args()
        if args.drive_root is not None:
            configure_runtime(args.drive_root)
        run_pipeline(
            rate_card_path=args.rate_card,
            rate_card_sheets=args.rate_card_sheets,
            agreement_path=args.agreement,
            services=args.services,
            warehouse=_parse_warehouse_arg(args.warehouse),
            interactive=args.warehouse is None,
        )
        return

    run_pipeline()


if __name__ == "__main__":
    main()
