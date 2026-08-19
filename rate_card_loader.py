from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from paths import PROCESSING_DIR, RATE_CARD_INPUT_DIR
from rate_card_layouts import list_processable_sheets, validate_rate_card_file

INPUT_DIR = RATE_CARD_INPUT_DIR


@dataclass
class RateCardConversionResult:
    source_file: Path
    processed_file: Path
    sheets: list[str]
    row_counts: dict[str, int]


def list_rate_card_files() -> list[Path]:
    """Return available .xlsx files in the input/Rate Card folder."""
    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"Input folder not found: {INPUT_DIR}")

    files = sorted(INPUT_DIR.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"No .xlsx files found in: {INPUT_DIR}")

    return files


def choose_rate_card_file() -> Path:
    """Prompt the user to choose a rate card file from the input folder."""
    files = list_rate_card_files()

    print("Available rate card files:")
    for index, file_path in enumerate(files, start=1):
        print(f"  {index}. {file_path.name}")

    while True:
        choice = input("Enter file number: ").strip()
        if not choice.isdigit():
            print("Please enter a valid number.")
            continue

        selected_index = int(choice)
        if 1 <= selected_index <= len(files):
            return files[selected_index - 1]

        print(f"Please enter a number between 1 and {len(files)}.")


def list_sheet_names(file_path: Path) -> list[str]:
    """Return all sheet names in an xlsx file."""
    with pd.ExcelFile(file_path, engine="openpyxl") as workbook:
        return workbook.sheet_names


def choose_sheets(file_path: Path) -> list[str]:
    """Prompt the user to choose which sheet(s) to convert."""
    processable = list_processable_sheets(file_path)
    sheets = processable or list_sheet_names(file_path)

    print(f"\nAvailable sheets in '{file_path.name}':")
    for index, name in enumerate(sheets, start=1):
        suffix = "" if name in processable else " (layout not detected)"
        print(f"  {index}. {name}{suffix}")
    print("  a. All listed sheets")

    while True:
        choice = input(
            "Enter sheet number(s), comma-separated (e.g. 1,3), or 'a' for all: "
        ).strip().lower()

        if choice == "a":
            return sheets

        parts = [part.strip() for part in choice.split(",") if part.strip()]
        if not parts or not all(part.isdigit() for part in parts):
            print("Please enter valid sheet numbers or 'a' for all.")
            continue

        selected_indices = [int(part) for part in parts]
        if any(index < 1 or index > len(sheets) for index in selected_indices):
            print(f"Please enter numbers between 1 and {len(sheets)}.")
            continue

        return [sheets[index - 1] for index in selected_indices]


def xlsx_to_dfs(file_path: Path, sheet_names: list[str]) -> dict[str, pd.DataFrame]:
    """Read selected sheets from an xlsx file and return them as DataFrames."""
    sheets: dict[str, pd.DataFrame] = {}

    for sheet_name in sheet_names:
        sheets[sheet_name] = pd.read_excel(
            file_path,
            sheet_name=sheet_name,
            header=None,
            engine="openpyxl",
        )

    return sheets


def save_dfs_to_processing(
    sheets: dict[str, pd.DataFrame],
    source_file: Path,
) -> Path:
    """Save one or more DataFrames to the processing folder as xlsx."""
    PROCESSING_DIR.mkdir(parents=True, exist_ok=True)

    output_name = f"{source_file.stem}_processed.xlsx"
    output_path = PROCESSING_DIR / output_name

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    return output_path


def load_rate_card_to_processing(
    file_path: Path | None = None,
    sheet_names: list[str] | None = None,
) -> tuple[dict[str, pd.DataFrame], Path]:
    """
    Load selected rate card sheet(s) and save them to the processing folder.

    If file_path is None, the user is prompted to choose from input/Rate Card.
    If sheet_names is None, all sheets with a detected layout are loaded.
    """
    selected_file = file_path or choose_rate_card_file()
    selected_sheets = sheet_names or list_processable_sheets(selected_file)

    if not selected_sheets:
        selected_sheets = list_sheet_names(selected_file)

    sheets = xlsx_to_dfs(selected_file, selected_sheets)
    output_path = save_dfs_to_processing(sheets, selected_file)
    return sheets, output_path


def convert_rate_card_file(file_path: Path) -> RateCardConversionResult:
    """Convert one rate card file to the processing folder."""
    sheet_names = list_processable_sheets(file_path)
    if not sheet_names:
        sheet_names = list_sheet_names(file_path)

    sheets = xlsx_to_dfs(file_path, sheet_names)
    output_path = save_dfs_to_processing(sheets, file_path)

    return RateCardConversionResult(
        source_file=file_path,
        processed_file=output_path,
        sheets=sheet_names,
        row_counts={name: len(df) for name, df in sheets.items()},
    )


@dataclass
class RateCardValidationResult:
    source_file: Path
    sheets: list[tuple[str, bool, str, int]]


def validate_all_rate_cards() -> list[RateCardValidationResult]:
    """Check that all rate card files in input can be converted."""
    results: list[RateCardValidationResult] = []

    for file_path in list_rate_card_files():
        sheet_results = validate_rate_card_file(file_path)
        results.append(
            RateCardValidationResult(
                source_file=file_path,
                sheets=sheet_results,
            )
        )

    return results


def print_rate_card_validation(results: list[RateCardValidationResult]) -> None:
    """Print a summary of rate card convertibility checks."""
    for result in results:
        print(f"\n{result.source_file.name}")
        if not result.sheets:
            print("  not convertible")
            continue

        for sheet_name, ok, message, rate_count in result.sheets:
            status = "OK" if ok else "FAIL"
            print(f"  [{status}] {sheet_name}: {message} ({rate_count} rates)")


def convert_all_rate_cards_to_processing() -> list[RateCardConversionResult]:
    """Convert all rate card files from input/Rate Card to processing."""
    results: list[RateCardConversionResult] = []

    for file_path in list_rate_card_files():
        result = convert_rate_card_file(file_path)
        results.append(result)

    return results


def main() -> None:
    sheets, output_path = load_rate_card_to_processing()

    print("\nConverted sheets:")
    for sheet_name, df in sheets.items():
        print(f"  {sheet_name}: {len(df)} rows, {len(df.columns)} columns")

    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
