from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

MatchFn = Callable[[str], bool]

NOISE_LABELS = {
    "type",
    "um",
    "unit",
    "driver",
    "elements",
    "3pl",
    "english",
    "tarifs 26",
    "control pay / daikin france",
    "control pay",
    "finished products (fp)",
    "costcentre",
    "provider",
    "client",
    "month",
    "year",
}

_DESCRIPTION_HEADER_SKIP = {
    "cost driver",
    "volume",
    "index",
    "driver",
    "unit",
    "um",
    "remarks / questions",
    "index % - 2026",
    "g/l account",
    "gl account",
}

_SECTION_YEAR_HEADERS = {"storage", "handling"}

_TOTAL_ROW_LABELS = {
    "storage total",
    "handling total",
    " total",
    "total",
    "not included",
}


@dataclass
class PriceColumn:
    header_row: int
    col: int
    desc_col: int


@dataclass(frozen=True)
class WarehouseColumn:
    """One warehouse price column in a multi-warehouse rate card sheet."""

    col: int
    label: str


_WAREHOUSE_LABEL_PATTERN = re.compile(
    r"warehouse|sqf\d|ayguemorte|noyelles|bordeaux|lyon",
    re.IGNORECASE,
)


@dataclass
class RateCollector:
    """Collect rate values; the first value wins when a lookup key repeats."""

    values: dict[str, float] = field(default_factory=dict)

    def add(self, description: str, numeric_value: float) -> None:
        for key in _lookup_keys_for_description(description):
            if key in self.values:
                continue
            self.values[key] = numeric_value

    def as_lookup(self) -> dict[str, float]:
        lookup: dict[str, float] = {}
        for key, value in self.values.items():
            lookup[key] = value
            lookup[_normalize_key(key)] = value
        return lookup


@dataclass(frozen=True)
class RateCardLayout:
    """Configuration for reading costs from a specific rate card file layout."""

    layout_id: str
    label: str
    price_label: str
    filename_hints: tuple[str, ...]
    match_text: MatchFn


def _normalize_key(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip().lower())
    text = text.rstrip(":").strip()
    text = re.sub(r"[-–—]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_number(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    text = text.replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def _search_match(pattern: str) -> MatchFn:
    compiled = re.compile(pattern, re.IGNORECASE)

    def matcher(text: str) -> bool:
        return bool(compiled.search(text.strip()))

    return matcher


def _exact_match(pattern: str) -> MatchFn:
    compiled = re.compile(pattern, re.IGNORECASE)

    def matcher(text: str) -> bool:
        normalized = re.sub(r"\s+", " ", text.strip())
        return bool(compiled.fullmatch(normalized))

    return matcher


# Most specific layouts first. Add new layouts to the end of this list.
RATE_CARD_LAYOUTS: tuple[RateCardLayout, ...] = (
    RateCardLayout(
        layout_id="unit_price_2026_2027",
        label="Unit Price 2026/2027 column",
        price_label="Unit Price 2026/2027",
        filename_hints=("utrecht", "1052"),
        match_text=_search_match(r"unit\s*price\s*2026\s*/\s*2027"),
    ),
    RateCardLayout(
        layout_id="tariff_m3_2026",
        label="Tariff / m3 2026 column",
        price_label="Tariff / m3 2026",
        filename_hints=("ceva", "nuevas"),
        match_text=_search_match(r"tariff\s*/\s*m3\s*2026"),
    ),
    RateCardLayout(
        layout_id="new_cost_column",
        label="New Cost column",
        price_label="New Cost",
        filename_hints=("galletti",),
        match_text=_search_match(r"new\s*cost"),
    ),
    RateCardLayout(
        layout_id="economics_column",
        label="Economics column",
        price_label="Economics",
        filename_hints=("denv", "daikin denv"),
        match_text=_search_match(r"economics"),
    ),
    RateCardLayout(
        layout_id="value_column",
        label="Value column",
        price_label="Value",
        filename_hints=("denv", "daikin denv"),
        match_text=_exact_match(r"value"),
    ),
    RateCardLayout(
        layout_id="cost_column",
        label="COST column",
        price_label="COST",
        filename_hints=("revisao", "revisão", "warehousing"),
        match_text=_exact_match(r"cost"),
    ),
    RateCardLayout(
        layout_id="euro_unit_column",
        label="EUR / Unit column",
        price_label="EUR / Unit",
        filename_hints=("appendi", "anex2", "control pay", "daikin warehousing", "warehousing rates", "4010"),
        match_text=_search_match(r"(?:€|euro?)\s*/\s*unit"),
    ),
    RateCardLayout(
        layout_id="price_column",
        label="Price column",
        price_label="Price",
        filename_hints=("ostend", "1002", "tarieven"),
        match_text=_exact_match(r"price"),
    ),
)


def _lookup_keys_for_description(text_value: str) -> list[str]:
    keys = [text_value]

    for match in re.finditer(r"\(([^)]+)\)", text_value):
        keys.append(match.group(1).strip())

    if " - " in text_value:
        for part in text_value.split(" - "):
            keys.append(part.split("(")[0].strip())

    seen: set[str] = set()
    unique_keys: list[str] = []
    for key in keys:
        normalized = _normalize_key(key)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_keys.append(key)

    return unique_keys


def _is_noise_label(text: str) -> bool:
    return _normalize_key(text) in NOISE_LABELS


NIGHT_SHIFT_SUFFIX = " [night shift]"


def _is_night_shift_price_header(text: str) -> bool:
    """Return True for EURO / Unit (with Night Shift) style headers."""
    lowered = _normalize_key(text)
    return "night shift" in lowered or "with night" in lowered


def _price_column_is_night_shift(df: pd.DataFrame, column: PriceColumn) -> bool:
    if column.col >= len(df.columns):
        return False

    cell = df.iloc[column.header_row, column.col]
    if pd.isna(cell):
        return False

    return _is_night_shift_price_header(str(cell))


def _warehouse_label_for_price_col(
    df: pd.DataFrame,
    price_col: int,
    header_row: int,
) -> str:
    """Read the warehouse name associated with a price column."""
    for row_idx in range(min(header_row, 5)):
        for col_idx in (price_col - 1, price_col - 2, price_col):
            if col_idx < 0 or col_idx >= len(df.columns):
                continue

            cell = df.iloc[row_idx, col_idx]
            if pd.isna(cell):
                continue

            text = str(cell).strip()
            if not text or _is_noise_label(text):
                continue

            if _WAREHOUSE_LABEL_PATTERN.search(text):
                return text

    if price_col > 0:
        cell = df.iloc[0, price_col - 1]
        if pd.notna(cell) and str(cell).strip():
            return str(cell).strip()

    return f"Column {price_col + 1}"


def discover_warehouse_columns(
    df: pd.DataFrame,
    layout: RateCardLayout,
    price_columns: list[PriceColumn] | None = None,
) -> list[WarehouseColumn]:
    """Return warehouse price columns when a sheet has multiple warehouse tables."""
    columns = price_columns or _find_all_price_columns(df, layout)
    if len(columns) < 2:
        return []

    warehouses: list[WarehouseColumn] = []
    for column in columns:
        if _price_column_is_night_shift(df, column):
            continue

        label = _warehouse_label_for_price_col(df, column.col, column.header_row)
        warehouses.append(WarehouseColumn(col=column.col, label=label))

    if len(warehouses) < 2:
        return []

    unique_labels = {_normalize_key(warehouse.label) for warehouse in warehouses}
    if len(unique_labels) < 2:
        return []

    return warehouses


def list_warehouse_columns_from_file(rate_card_path: Path) -> list[WarehouseColumn]:
    """List warehouse tables from the first processable sheet in a rate card file."""
    with pd.ExcelFile(rate_card_path, engine="openpyxl") as workbook:
        for sheet_name in workbook.sheet_names:
            df = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
            layout = detect_rate_card_layout(df, rate_card_path.name)
            if layout is None:
                continue

            warehouses = discover_warehouse_columns(df, layout)
            if warehouses:
                return warehouses

    return []


def choose_warehouse_column(warehouses: list[WarehouseColumn]) -> int:
    """Prompt the user to choose one warehouse price table."""
    if not warehouses:
        raise ValueError("No warehouse tables available to choose from.")

    if len(warehouses) == 1:
        return warehouses[0].col

    print("\nMultiple warehouse rate tables found in the rate card:")
    for index, warehouse in enumerate(warehouses, start=1):
        print(f"  {index}. {warehouse.label} (Excel column {warehouse.col + 1})")

    while True:
        choice = input("Enter warehouse table number: ").strip()
        if not choice.isdigit():
            print("Please enter a valid number.")
            continue

        selected_index = int(choice)
        if 1 <= selected_index <= len(warehouses):
            selected = warehouses[selected_index - 1]
            print(f"Using warehouse table: {selected.label}")
            return selected.col

        print(f"Please enter a number between 1 and {len(warehouses)}.")


def resolve_warehouse_price_col(
    warehouses: list[WarehouseColumn],
    warehouse: str | int | None = None,
    *,
    interactive: bool = True,
) -> int | None:
    """Resolve a warehouse selector to a price column index."""
    if not warehouses:
        return None

    if len(warehouses) == 1:
        return warehouses[0].col

    if warehouse is not None:
        if isinstance(warehouse, int):
            for item in warehouses:
                if item.col == warehouse:
                    return warehouse
            valid = ", ".join(str(item.col) for item in warehouses)
            raise ValueError(
                f"Warehouse column {warehouse} not found. Valid columns: {valid}"
            )

        target = _normalize_key(str(warehouse))
        for item in warehouses:
            label = _normalize_key(item.label)
            if target in label or label in target:
                return item.col

        options = ", ".join(item.label for item in warehouses)
        raise ValueError(
            f"No warehouse table matches '{warehouse}'. Available: {options}"
        )

    if interactive:
        return choose_warehouse_column(warehouses)

    options = ", ".join(item.label for item in warehouses)
    raise ValueError(
        "Rate card contains multiple warehouse tables. "
        f"Choose one with --warehouse, e.g. --warehouse \"Bordeaux\". Available: {options}"
    )


def warehouse_label_for_column(
    warehouses: list[WarehouseColumn],
    price_col: int,
) -> str | None:
    """Return the label for a selected warehouse price column."""
    for warehouse in warehouses:
        if warehouse.col == price_col:
            return warehouse.label
    return None


def _find_all_price_columns(df: pd.DataFrame, layout: RateCardLayout) -> list[PriceColumn]:
    """Find every price column for a layout (supports multi-warehouse sheets)."""
    columns: list[PriceColumn] = []
    seen_cols: set[int] = set()

    for row_idx in range(min(40, len(df))):
        row = df.iloc[row_idx]
        for col_idx, cell in enumerate(row):
            if col_idx in seen_cols or not _cell_matches_layout(cell, layout):
                continue

            desc_col = _resolve_description_col(row, col_idx)
            if desc_col == col_idx:
                desc_col = 0

            columns.append(PriceColumn(header_row=row_idx, col=col_idx, desc_col=desc_col))
            seen_cols.add(col_idx)

    return columns


def _read_single_description_cell(df: pd.DataFrame, row_idx: int, desc_col: int) -> str | None:
    if row_idx < 0 or row_idx >= len(df) or desc_col >= len(df.columns):
        return None

    cell = df.iloc[row_idx, desc_col]
    if pd.isna(cell) or not str(cell).strip():
        return None

    text = str(cell).strip()
    if _is_noise_label(text) or _looks_like_type_label(text):
        return None

    normalized = _normalize_key(text)
    if normalized in _TOTAL_ROW_LABELS or normalized.startswith("week "):
        return None

    if _parse_number(text) is not None and not any(char.isalpha() for char in text):
        return None

    return text


def _read_description(
    df: pd.DataFrame,
    row_idx: int,
    desc_col: int,
    price_col: int,
    span: int = 3,
) -> str | None:
    """Read a description from the same row, or from recent rows when split across lines."""
    current = _read_single_description_cell(df, row_idx, desc_col)
    if current and _read_price(df, row_idx, price_col, span=1) is not None:
        return current

    parts: list[str] = []
    if current:
        parts.append(current)

    if not parts:
        for back in range(1, span):
            previous = _read_single_description_cell(df, row_idx - back, desc_col)
            if previous:
                parts.insert(0, previous)
                break

    for offset in range(1, span):
        if _read_price(df, row_idx, price_col, span=offset + 1) is not None:
            break

        next_part = _read_single_description_cell(df, row_idx + offset, desc_col)
        if not next_part:
            break

        if next_part not in parts:
            parts.append(next_part)

    if not parts:
        return None

    return " ".join(parts)


def _looks_like_type_label(text: str) -> bool:
    """Return True for short section headers, not for named cost lines."""
    if "(" in text or "+" in text or any(char.isdigit() for char in text):
        return False

    normalized = text.strip().lower()
    if not normalized.startswith(("fp ", "sp ", "admin", "handling ", "storage ")):
        return False

    if len(normalized.split()) >= 3:
        return False

    return len(text) < 20


def _looks_like_price_label(text: str) -> bool:
    return bool(re.fullmatch(r"(?:€|eur)?\s*/?\s*unit|price|cost|value|m3|fixed cost", text.strip(), re.I))


def _read_price(
    df: pd.DataFrame,
    row_idx: int,
    price_col: int,
    span: int = 3,
) -> float | None:
    """Read a price that may appear on the same row or up to two rows below."""
    for offset in range(span):
        current_row = row_idx + offset
        if current_row >= len(df) or price_col >= len(df.columns):
            break

        value = _parse_number(df.iloc[current_row, price_col])
        if value is not None:
            return value

    return None


def get_layout_by_id(layout_id: str) -> RateCardLayout:
    for layout in RATE_CARD_LAYOUTS:
        if layout.layout_id == layout_id:
            return layout
    raise KeyError(f"Unknown rate card layout: {layout_id}")


def _cell_matches_layout(cell, layout: RateCardLayout) -> bool:
    if pd.isna(cell):
        return False
    return layout.match_text(str(cell))


def find_price_section(
    df: pd.DataFrame,
    layout: RateCardLayout,
) -> tuple[int, int, int] | None:
    """
    Locate the price section for a layout.

    Returns:
        data_start_row, price_col, description_col
    """
    header_row: int | None = None
    price_col: int | None = None

    for row_idx in range(len(df)):
        row = df.iloc[row_idx]
        for col_idx, cell in enumerate(row):
            if _cell_matches_layout(cell, layout):
                header_row = row_idx
                price_col = col_idx
                break
        if header_row is not None:
            break

    if header_row is None or price_col is None:
        return None

    description_col = _resolve_description_col(df.iloc[header_row], price_col)

    next_row = header_row + 1
    if next_row < len(df):
        for col_idx, cell in enumerate(df.iloc[next_row]):
            if _cell_matches_layout(cell, layout):
                header_row = next_row
                price_col = col_idx
                description_col = _resolve_description_col(df.iloc[header_row], price_col)
                break

    return header_row + 1, price_col, description_col


def _is_price_like_header(text: str) -> bool:
    lowered = text.strip().lower()
    return any(
        token in lowered
        for token in ("unit price", "price", "cost", "tariff", "value", "€", "eur / unit")
    )


def _resolve_description_col(header_row: pd.Series, price_col: int) -> int:
    """Pick the description column for a price column."""
    guessed = _guess_description_col(header_row, price_col)

    if guessed < price_col and guessed >= 0:
        cell = header_row.iloc[guessed] if guessed < len(header_row) else None
        header_text = str(cell).strip() if pd.notna(cell) else ""
        if header_text and not _is_price_like_header(header_text):
            return guessed

    return 0


def _guess_description_col(header_row: pd.Series, price_col: int) -> int:
    skip_headers = {
        "type",
        "um",
        "unit",
        "driver",
        "3pl",
        "control pay / daikin france",
        "english",
        "tarifs 26",
    }
    preferred_headers = ("elements", "description", "service", "finished products")

    best_col = 0 if price_col != 0 else 1
    for col_idx, cell in enumerate(header_row):
        if col_idx >= price_col or pd.isna(cell):
            continue

        text = str(cell).strip().lower()
        if not text or text in skip_headers:
            continue

        if any(token in text for token in preferred_headers):
            return col_idx

        best_col = col_idx

    return best_col


def detect_rate_card_layout(df: pd.DataFrame, filename: str = "") -> RateCardLayout | None:
    """Detect which rate card layout applies to a sheet."""
    normalized_filename = _normalize_key(filename)
    detected: list[tuple[int, RateCardLayout]] = []

    for layout in RATE_CARD_LAYOUTS:
        section = find_price_section(df, layout)
        if section is None:
            continue

        hint_bonus = sum(
            10 for hint in layout.filename_hints if hint in normalized_filename
        )
        detected.append((hint_bonus, layout))

    if not detected:
        return None

    detected.sort(key=lambda item: item[0], reverse=True)
    return detected[0][1]


def sheet_has_processable_layout(df: pd.DataFrame, filename: str = "") -> bool:
    """Return True when a sheet contains a supported rate card layout."""
    return detect_rate_card_layout(df, filename) is not None


def list_processable_sheets(file_path: Path) -> list[str]:
    """Return sheet names that contain a supported rate card layout."""
    processable: list[str] = []

    with pd.ExcelFile(file_path, engine="openpyxl") as workbook:
        for sheet_name in workbook.sheet_names:
            df = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
            if sheet_has_processable_layout(df, file_path.name):
                processable.append(sheet_name)

    return processable


def _is_header_label(text: str, layout: RateCardLayout) -> bool:
    return layout.match_text(text)


def _extract_rate_at_row(
    df: pd.DataFrame,
    row_idx: int,
    desc_col: int,
    price_col: int,
    layout: RateCardLayout,
) -> tuple[str, float] | None:
    """
    Extract one description/price pair from a row.

    Avoid pairing a description from above with a price from a later row when
    blank separator rows sit between cost blocks.
    """
    current_desc = _read_single_description_cell(df, row_idx, desc_col)
    same_row_price = _read_price(df, row_idx, price_col, span=1)

    if current_desc and _is_header_label(current_desc, layout):
        return None

    if current_desc and same_row_price is not None:
        if _is_section_year_placeholder(current_desc, same_row_price):
            return None
        return current_desc, same_row_price

    if not current_desc and same_row_price is not None:
        for back in range(1, 4):
            previous_row = row_idx - back
            if previous_row < 0:
                break

            previous_desc = _read_single_description_cell(df, previous_row, desc_col)
            if not previous_desc or _is_header_label(previous_desc, layout):
                continue

            if _read_price(df, previous_row, price_col, span=1) is not None:
                break

            if _is_section_year_placeholder(previous_desc, same_row_price):
                break
            return previous_desc, same_row_price

    if current_desc and same_row_price is None:
        description = _read_description(df, row_idx, desc_col, price_col)
        if not description or description != current_desc:
            description = current_desc

        for offset in range(1, 4):
            price_row = row_idx + offset
            if price_row >= len(df):
                break

            price = _read_price(df, price_row, price_col, span=1)
            if price is None:
                continue

            price_row_desc = _read_single_description_cell(df, price_row, desc_col)
            if price_row_desc and _read_price(df, price_row, price_col, span=1) is not None:
                break

            return description, price

    return None


def _is_description_header_column(df: pd.DataFrame, col_idx: int, header_row: int) -> bool:
    if header_row < 0 or col_idx >= len(df.columns):
        return False

    cell = df.iloc[header_row, col_idx]
    if pd.isna(cell):
        return False

    return _normalize_key(str(cell)) in _DESCRIPTION_HEADER_SKIP


def _is_section_year_placeholder(description: str, price: float) -> bool:
    """Skip section headers paired with a year value instead of a real rate."""
    if _normalize_key(description) not in _SECTION_YEAR_HEADERS:
        return False

    return 2020 <= price <= 2035 and abs(price - round(price)) < 0.001


def _find_description_col_from_headers(
    df: pd.DataFrame,
    header_row: int,
    first_price_col: int,
) -> int | None:
    """Prefer a column explicitly labelled ELEMENTS/Description beside price columns."""
    preferred_headers = ("elements", "description", "service", "finished products")

    for col_idx in range(first_price_col):
        if col_idx >= len(df.columns):
            continue

        cell = df.iloc[header_row, col_idx]
        if pd.isna(cell):
            continue

        if _normalize_key(str(cell)) in preferred_headers:
            return col_idx

    return None


def _find_description_col_from_data(
    df: pd.DataFrame,
    data_start: int,
    price_cols: list[int],
    scan_rows: int = 40,
) -> int | None:
    """Find the column that most often holds descriptions beside price values."""
    if not price_cols:
        return None

    first_price_col = min(price_cols)
    header_row = max(data_start - 1, 0)
    scores: dict[int, tuple[int, int]] = {}
    end = min(len(df), data_start + scan_rows)

    for row_idx in range(data_start, end):
        if not any(_read_price(df, row_idx, col, span=1) is not None for col in price_cols):
            continue

        for col_idx in range(first_price_col):
            if _is_description_header_column(df, col_idx, header_row):
                continue

            desc = _read_single_description_cell(df, row_idx, col_idx)
            if not desc:
                continue

            count, total_len = scores.get(col_idx, (0, 0))
            scores[col_idx] = (count + 1, total_len + len(desc))

    if not scores:
        return None

    return max(scores, key=lambda item: (scores[item][0], scores[item][1], -item))


_REV_PERIOD_LABEL = re.compile(r"REV\s*(\d{4})", re.IGNORECASE)
_DATE_RANGE_PERIOD_LABEL = re.compile(r"(\d{4})\s*-\s*(\d{4})")
_PREFERRED_REVISION_LABEL = "REV2026"


def _revision_period_label(text: str) -> str | None:
    """Return a normalized revision period label when the cell marks a price period."""
    normalized = re.sub(r"\s+", " ", str(text).strip())
    if not normalized:
        return None

    rev_match = _REV_PERIOD_LABEL.search(normalized)
    if rev_match:
        return f"REV{rev_match.group(1)}"

    if _DATE_RANGE_PERIOD_LABEL.search(normalized):
        return normalized

    return None


def _revision_period_row(df: pd.DataFrame, price_columns: list[PriceColumn]) -> int | None:
    if not price_columns:
        return None

    header_row = min(column.header_row for column in price_columns)
    period_row = header_row - 1
    if period_row < 0:
        return None

    return period_row


def _extend_revision_price_columns(
    df: pd.DataFrame,
    price_columns: list[PriceColumn],
) -> list[PriceColumn]:
    """Add revision-period price columns that lack a COST/price header (e.g. REV2026)."""
    period_row = _revision_period_row(df, price_columns)
    if period_row is None:
        return price_columns

    header_row = min(column.header_row for column in price_columns)
    desc_col = price_columns[0].desc_col
    seen_cols = {column.col for column in price_columns}
    extended = list(price_columns)

    for col_idx in range(len(df.columns)):
        if col_idx in seen_cols:
            continue

        label = _revision_period_label(str(df.iloc[period_row, col_idx]))
        if label is None:
            continue

        extended.append(
            PriceColumn(header_row=header_row, col=col_idx, desc_col=desc_col)
        )
        seen_cols.add(col_idx)

    return sorted(extended, key=lambda column: column.col)


def _revision_column_preference(
    df: pd.DataFrame,
    price_columns: list[PriceColumn],
) -> list[int]:
    """Return revision price columns ordered newest-first, preferring REV2026 when present."""
    period_row = _revision_period_row(df, price_columns)
    if period_row is None:
        return sorted({column.col for column in price_columns}, reverse=True)

    preferred_col: int | None = None
    rev_years: list[tuple[int, int]] = []
    other_cols: list[int] = []

    for column in price_columns:
        label = _revision_period_label(str(df.iloc[period_row, column.col]))
        if label is None:
            other_cols.append(column.col)
            continue

        rev_match = _REV_PERIOD_LABEL.fullmatch(label)
        if rev_match:
            year = int(rev_match.group(1))
            if label.upper() == _PREFERRED_REVISION_LABEL:
                preferred_col = column.col
            rev_years.append((year, column.col))
            continue

        other_cols.append(column.col)

    ordered: list[int] = []
    if preferred_col is not None:
        ordered.append(preferred_col)

    for _, col in sorted(rev_years, key=lambda item: item[0], reverse=True):
        if col not in ordered:
            ordered.append(col)

    for col in sorted(other_cols, reverse=True):
        if col not in ordered:
            ordered.append(col)

    return ordered


def _select_revision_price_col(
    df: pd.DataFrame,
    row_idx: int,
    preferred_cols: list[int],
) -> int | None:
    """Pick the preferred revision column that has a price on this row."""
    for col in preferred_cols:
        if _read_price(df, row_idx, col, span=1) is not None:
            return col

    return None


def _is_revision_period_columns(
    df: pd.DataFrame,
    price_columns: list[PriceColumn],
) -> bool:
    """Return True when multiple price columns are revision periods (REV2021, 2020, etc.)."""
    if len(price_columns) < 2:
        return False

    period_row = _revision_period_row(df, price_columns)
    if period_row is None:
        return False

    for column in price_columns:
        if column.col >= len(df.columns):
            continue
        if _revision_period_label(str(df.iloc[period_row, column.col])) is not None:
            return True

    return False


def _extract_rates_from_sheet(
    df: pd.DataFrame,
    layout: RateCardLayout,
    collector: RateCollector,
    warehouse_price_col: int | None = None,
) -> None:
    """Extract rates from one sheet, including multi-column and multi-row entries."""
    price_columns = _find_all_price_columns(df, layout)
    if not price_columns:
        return

    if warehouse_price_col is not None:
        price_columns = [column for column in price_columns if column.col == warehouse_price_col]
        if not price_columns:
            raise ValueError(
                f"Warehouse price column {warehouse_price_col} not found in sheet."
            )

    if _is_revision_period_columns(df, price_columns):
        price_columns = _extend_revision_price_columns(df, price_columns)

    data_start = min(column.header_row for column in price_columns) + 1
    header_row = min(column.header_row for column in price_columns)
    price_cols = sorted({column.col for column in price_columns})
    desc_col = _find_description_col_from_headers(df, header_row, min(price_cols))
    if desc_col is None:
        desc_col = _find_description_col_from_data(df, data_start, price_cols)
    if desc_col is None:
        desc_col = price_columns[0].desc_col

    use_latest_revision = _is_revision_period_columns(df, price_columns)
    revision_price_cols = (
        _revision_column_preference(df, price_columns)
        if use_latest_revision
        else []
    )
    has_shift_columns = any(_price_column_is_night_shift(df, column) for column in price_columns)

    for row_idx in range(data_start, len(df)):
        if use_latest_revision:
            price_col = _select_revision_price_col(df, row_idx, revision_price_cols)

            if price_col is None:
                continue

            extracted = _extract_rate_at_row(
                df,
                row_idx,
                desc_col,
                price_col,
                layout,
            )
            if extracted is None:
                continue

            description, price = extracted
            collector.add(description, price)
            continue

        row_entries: list[tuple[str, float, bool]] = []
        for column in price_columns:
            extracted = _extract_rate_at_row(
                df,
                row_idx,
                desc_col,
                column.col,
                layout,
            )
            if extracted is None:
                continue

            is_night = _price_column_is_night_shift(df, column)
            row_entries.append((*extracted, is_night))

        if not row_entries:
            continue

        if has_shift_columns:
            for description, price, is_night in row_entries:
                if is_night:
                    description = f"{description}{NIGHT_SHIFT_SUFFIX}"
                collector.add(description, price)
            continue

        for description, price, _ in row_entries:
            collector.add(description, price)


def build_rate_lookup_from_dataframe(
    df: pd.DataFrame,
    filename: str = "",
    warehouse_price_col: int | None = None,
) -> dict[str, float]:
    """Build a lookup dictionary from an in-memory rate card sheet."""
    layout = detect_rate_card_layout(df, filename)
    if layout is None:
        raise ValueError(f"Unsupported rate card layout in '{filename}'")

    collector = RateCollector()
    _extract_rates_from_sheet(df, layout, collector, warehouse_price_col)
    lookup = collector.as_lookup()

    if not lookup:
        raise ValueError(f"No rate values found in '{filename}'")

    return lookup


def validate_rate_card_dataframe(df: pd.DataFrame, filename: str = "") -> tuple[bool, str, int]:
    """Check whether a sheet can be converted into a rate lookup."""
    layout = detect_rate_card_layout(df, filename)
    if layout is None:
        return False, "unsupported layout", 0

    collector = RateCollector()
    _extract_rates_from_sheet(df, layout, collector)
    lookup = collector.as_lookup()
    rate_count = len({key for key in lookup if isinstance(key, str) and key == _normalize_key(key)})

    if rate_count == 0:
        return False, f"{layout.label} detected but no rates found", 0

    return True, f"{layout.label} ({layout.layout_id})", rate_count


def validate_rate_card_file(file_path: Path) -> list[tuple[str, bool, str, int]]:
    """Validate all sheets in one rate card file and return convertible sheets."""
    results: list[tuple[str, bool, str, int]] = []

    with pd.ExcelFile(file_path, engine="openpyxl") as workbook:
        for sheet_name in workbook.sheet_names:
            df = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
            ok, message, rate_count = validate_rate_card_dataframe(df, file_path.name)
            if ok:
                results.append((sheet_name, ok, message, rate_count))

    if not results:
        with pd.ExcelFile(file_path, engine="openpyxl") as workbook:
            sheet_name = workbook.sheet_names[0]
            df = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
            ok, message, rate_count = validate_rate_card_dataframe(df, file_path.name)
            results.append((sheet_name, ok, message, rate_count))

    return results


def build_rate_lookup(
    rate_card_path: Path,
    warehouse: str | int | None = None,
    *,
    warehouse_price_col: int | None = None,
    interactive: bool = True,
) -> dict[str, float]:
    """Build a rate lookup dictionary from a processed rate card file."""
    if warehouse_price_col is None:
        warehouses = list_warehouse_columns_from_file(rate_card_path)
        warehouse_price_col = resolve_warehouse_price_col(
            warehouses,
            warehouse,
            interactive=interactive,
        )

    collector = RateCollector()

    with pd.ExcelFile(rate_card_path, engine="openpyxl") as workbook:
        for sheet_name in workbook.sheet_names:
            df = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
            layout = detect_rate_card_layout(df, rate_card_path.name)
            if layout is None:
                continue

            _extract_rates_from_sheet(df, layout, collector, warehouse_price_col)

    lookup = collector.as_lookup()
    if not lookup:
        raise ValueError(f"No rate values found in rate card file: {rate_card_path.name}")

    return lookup


def describe_detected_layout(rate_card_path: Path) -> str:
    """Return a human-readable description of the detected layout."""
    layouts: list[str] = []

    with pd.ExcelFile(rate_card_path, engine="openpyxl") as workbook:
        for sheet_name in workbook.sheet_names:
            df = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
            layout = detect_rate_card_layout(df, rate_card_path.name)
            if layout is None:
                continue
            label = f"{sheet_name}: {layout.label} ({layout.layout_id})"
            if label not in layouts:
                layouts.append(label)

    if not layouts:
        return "unsupported layout"

    return "; ".join(layouts)
