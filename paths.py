"""Project paths for local runs and Google Colab + Shared Drive data."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Code location (e.g. /content/Daikin-Storage on Colab, or this repo locally).
CODE_DIR = Path(__file__).resolve().parent

# Shared Drive folder with input/, processing/, and output/.
COLAB_DRIVE_ROOT = Path(
    "/content/drive/Shareddrives/FA Ops Europe: Rate Maintenance Team "
    "/Documents/AI Adoption RMT/RMT_Daikin/RMT_Storage"
)

ENV_DRIVE_ROOT = "DAIKIN_STORAGE_DRIVE_ROOT"
ENV_USE_DRIVE = "DAIKIN_STORAGE_USE_DRIVE"


def is_colab() -> bool:
    """Return True when running inside Google Colab."""
    return "google.colab" in sys.modules


def get_drive_root() -> Path:
    """Return the configured Shared Drive data root."""
    override = os.environ.get(ENV_DRIVE_ROOT, "").strip()
    if override:
        return Path(override)
    return COLAB_DRIVE_ROOT


def use_drive_data() -> bool:
    """
    Return True when input/output/processing should live on Shared Drive.

    Enabled automatically on Colab, or when DAIKIN_STORAGE_USE_DRIVE=1, or when
    DAIKIN_STORAGE_DRIVE_ROOT is set.
    """
    flag = os.environ.get(ENV_USE_DRIVE, "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if os.environ.get(ENV_DRIVE_ROOT, "").strip():
        return True
    return is_colab()


def get_data_root() -> Path:
    """Return the root folder that contains input/, processing/, and output/."""
    if use_drive_data():
        return get_drive_root()
    return CODE_DIR


def resolve_paths() -> tuple[Path, Path, Path, Path, Path, Path]:
    """Return input, processing, output, rate card, agreement, and mappings paths."""
    data_root = get_data_root()
    input_dir = data_root / "input"
    processing_dir = data_root / "processing"
    output_dir = data_root / "output"
    rate_card_input_dir = input_dir / "Rate Card"
    rate_agreement_input_dir = input_dir / "Rate Agreement"
    cost_mappings_path = input_dir / "cost_mappings.txt"
    return (
        input_dir,
        processing_dir,
        output_dir,
        rate_card_input_dir,
        rate_agreement_input_dir,
        cost_mappings_path,
    )


(
    INPUT_DIR,
    PROCESSING_DIR,
    OUTPUT_DIR,
    RATE_CARD_INPUT_DIR,
    RATE_AGREEMENT_INPUT_DIR,
    COST_MAPPINGS_PATH,
) = resolve_paths()


def configure(
    drive_root: Path | str | None = None,
    *,
    use_drive: bool | None = None,
) -> None:
    """Reconfigure data paths (call before running the pipeline if overriding defaults)."""
    global INPUT_DIR, PROCESSING_DIR, OUTPUT_DIR
    global RATE_CARD_INPUT_DIR, RATE_AGREEMENT_INPUT_DIR, COST_MAPPINGS_PATH

    if drive_root is not None:
        os.environ[ENV_DRIVE_ROOT] = str(drive_root)
    if use_drive is not None:
        os.environ[ENV_USE_DRIVE] = "1" if use_drive else "0"

    (
        INPUT_DIR,
        PROCESSING_DIR,
        OUTPUT_DIR,
        RATE_CARD_INPUT_DIR,
        RATE_AGREEMENT_INPUT_DIR,
        COST_MAPPINGS_PATH,
    ) = resolve_paths()
    sync_dependent_modules()


def sync_dependent_modules() -> None:
    """Push updated paths into modules that cache them at import time."""
    import cost_mappings
    import rate_agreement_loader
    import rate_card_loader
    import rate_cost_applier

    cost_mappings.DEFAULT_MAPPINGS_PATH = COST_MAPPINGS_PATH
    rate_card_loader.INPUT_DIR = RATE_CARD_INPUT_DIR
    rate_agreement_loader.INPUT_DIR = RATE_AGREEMENT_INPUT_DIR
    rate_cost_applier.AGREEMENT_INPUT_DIR = RATE_AGREEMENT_INPUT_DIR
    rate_cost_applier.RATE_CARD_PROCESSING_DIR = PROCESSING_DIR
    rate_cost_applier.OUTPUT_DIR = OUTPUT_DIR


def ensure_colab_drive_mounted() -> Path:
    """
    Mount Google Drive on Colab when needed and verify the data root exists.

    Call this once at the start of a Colab session before running the pipeline.
    """
    global INPUT_DIR, PROCESSING_DIR, OUTPUT_DIR
    global RATE_CARD_INPUT_DIR, RATE_AGREEMENT_INPUT_DIR, COST_MAPPINGS_PATH

    if is_colab() and not Path("/content/drive").exists():
        from google.colab import drive

        drive.mount("/content/drive")

    (
        INPUT_DIR,
        PROCESSING_DIR,
        OUTPUT_DIR,
        RATE_CARD_INPUT_DIR,
        RATE_AGREEMENT_INPUT_DIR,
        COST_MAPPINGS_PATH,
    ) = resolve_paths()
    sync_dependent_modules()

    data_root = get_data_root()

    if use_drive_data() and not data_root.exists():
        raise FileNotFoundError(
            "Shared Drive data folder not found:\n"
            f"  {data_root}\n\n"
            "Expected subfolders:\n"
            f"  {data_root / 'input' / 'Rate Card'}\n"
            f"  {data_root / 'input' / 'Rate Agreement'}\n"
            f"  {data_root / 'input' / 'cost_mappings.txt'}\n"
            f"  {data_root / 'processing'}\n"
            f"  {data_root / 'output'}\n\n"
            f"Override with env var {ENV_DRIVE_ROOT} if your path differs."
        )

    for folder in (RATE_CARD_INPUT_DIR, RATE_AGREEMENT_INPUT_DIR, PROCESSING_DIR, OUTPUT_DIR):
        folder.mkdir(parents=True, exist_ok=True)

    return data_root


def print_path_layout() -> None:
    """Print the active path layout (useful in Colab)."""
    mode = "Shared Drive" if use_drive_data() else "local"
    print(f"Path mode: {mode}")
    print(f"  Code:              {CODE_DIR}")
    print(f"  Data root:         {get_data_root()}")
    print(f"  Rate card input:   {RATE_CARD_INPUT_DIR}")
    print(f"  Agreement input:   {RATE_AGREEMENT_INPUT_DIR}")
    print(f"  Cost mappings:     {COST_MAPPINGS_PATH}")
    print(f"  Processing:        {PROCESSING_DIR}")
    print(f"  Output:            {OUTPUT_DIR}")
