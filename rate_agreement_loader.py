from pathlib import Path

import pandas as pd

from paths import PROCESSING_DIR, RATE_AGREEMENT_INPUT_DIR

INPUT_DIR = RATE_AGREEMENT_INPUT_DIR
RATE_CARD_SHEET = "Rate card"


def list_rate_agreement_files() -> list[Path]:
    """Return available .xlsx files in the input/rate agreement folder."""
    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"Input folder not found: {INPUT_DIR}")

    files = sorted(INPUT_DIR.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"No .xlsx files found in: {INPUT_DIR}")

    return files


def choose_rate_agreement_file() -> Path:
    """Prompt the user to choose a rate agreement file from the input folder."""
    files = list_rate_agreement_files()

    print("Available rate agreement files:")
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


def read_rate_card_sheet(file_path: Path, sheet_name: str = RATE_CARD_SHEET) -> pd.DataFrame:
    """Read the 'rate card' tab from a rate agreement xlsx file."""
    with pd.ExcelFile(file_path, engine="openpyxl") as workbook:
        available_sheets = workbook.sheet_names
        if sheet_name not in available_sheets:
            raise ValueError(
                f"Sheet '{sheet_name}' not found in '{file_path.name}'. "
                f"Available sheets: {', '.join(available_sheets)}"
            )

    return pd.read_excel(file_path, sheet_name=sheet_name, engine="openpyxl")


def save_df_to_processing(df: pd.DataFrame, source_file: Path) -> Path:
    """Save the rate card DataFrame to the processing folder as xlsx."""
    PROCESSING_DIR.mkdir(parents=True, exist_ok=True)

    output_name = f"{source_file.stem}_rate_card_processed.xlsx"
    output_path = PROCESSING_DIR / output_name

    df.to_excel(output_path, sheet_name=RATE_CARD_SHEET, index=False, engine="openpyxl")
    return output_path


def load_rate_agreement_to_processing(
    file_path: Path | None = None,
    sheet_name: str = RATE_CARD_SHEET,
) -> tuple[pd.DataFrame, Path]:
    """
    Load the rate card tab from a rate agreement file and save it to processing.

    If file_path is None, the user is prompted to choose from input/rate agreement.
    """
    selected_file = file_path or choose_rate_agreement_file()
    df = read_rate_card_sheet(selected_file, sheet_name=sheet_name)
    output_path = save_df_to_processing(df, selected_file)
    return df, output_path


def main() -> None:
    df, output_path = load_rate_agreement_to_processing()

    print(f"\nLoaded '{RATE_CARD_SHEET}' tab: {len(df)} rows, {len(df.columns)} columns")
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()
