from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from paths import COST_MAPPINGS_PATH

DEFAULT_MAPPINGS_PATH = COST_MAPPINGS_PATH

AGREEMENT_PREFIXES: tuple[str, ...] = (
    "Fixed Area for Repairing Fee",
    "Handling Fee",
    "Storage Fee",
    "Transport cost",
    "Pallet Fee",
    "Packaging Fee",
    "Administration",
    "HANDLING IN FP",
    "HANDLING OUT FP",
    "HANDLING IN",
    "HANDLING OUT",
    "STORAGE FINISHED UNITS",
    "STORAGE MODIFICATION AREA",
    "STORAGE SPP",
    "STORAGE",
    "Handling in from factory",
    "Handling out",
    "Handling -",
    "storage non ADR",
    "Storage equipments",
    "MBA",
    "Storage spare parts",
    "Inbounds machines",
    "Inbound spare parts",
    "Outbounds machines",
    "Outbounds spare parts",
    "Returns",
    "Unload carton boxes",
    "Full Pallet Picking",
    "Fumigated Pallet",
    "Carton Box for packing",
    "Box / Case Picking",
    "Unit Picking",
)

SEPARATOR_PATTERN = re.compile(r"^=+\s*$")
RATE_BY_PATTERN = re.compile(r"\s\+\s*Rate by:\s*(.+)$", re.IGNORECASE)
OR_SPLIT_PATTERN = re.compile(r"\s+or\s+", re.IGNORECASE)


@dataclass
class CostMappingEntry:
    rate_card_name: str
    agreement_aliases: list[str] = field(default_factory=list)
    rate_by: str | None = None


@dataclass
class CostMappings:
    entries: list[CostMappingEntry] = field(default_factory=list)

    def agreement_candidates(self, header_texts: list[str], lookup_keys: list[str]) -> list[str]:
        """Return rate card names that match the agreement column headers."""
        matched_entries: list[tuple[int, CostMappingEntry]] = []

        for entry in self.entries:
            if _entry_matches_agreement(entry, header_texts, lookup_keys):
                score = _entry_match_score(entry, header_texts, lookup_keys)
                matched_entries.append((score, entry))

        if _header_has_rate_by(header_texts, lookup_keys):
            specific_entries = [
                (score, entry) for score, entry in matched_entries if entry.rate_by
            ]
            if specific_entries:
                matched_entries = specific_entries

        matched_entries.sort(key=lambda item: item[0], reverse=True)

        matched_rate_cards: list[str] = []
        seen: set[str] = set()

        for _, entry in matched_entries:
            normalized = _normalize(entry.rate_card_name)
            if normalized in seen:
                continue

            seen.add(normalized)
            matched_rate_cards.append(entry.rate_card_name)

        return matched_rate_cards


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _combined_blob(header_texts: list[str], lookup_keys: list[str]) -> str:
    return _normalize(" | ".join([*header_texts, *lookup_keys]))


def _primary_category(header_texts: list[str]) -> str:
    if not header_texts:
        return ""

    return str(header_texts[0]).split("|")[0].strip()


def _header_has_rate_by(header_texts: list[str], lookup_keys: list[str]) -> bool:
    return "rate by:" in _combined_blob(header_texts, lookup_keys)


def _category_matches(alias: str, header_texts: list[str], lookup_keys: list[str]) -> bool:
    """Match a mapping alias against agreement header category names only."""
    del lookup_keys  # Fragments like OUT/Outbound must not drive mapping matches.

    alias_norm = _normalize(alias)
    if not alias_norm:
        return False

    primary_norm = _normalize(_primary_category(header_texts))
    if primary_norm and alias_norm == primary_norm:
        return True

    if primary_norm and alias_norm != primary_norm:
        if _are_distinct_category_variants(primary_norm, alias_norm):
            return False
        if primary_norm.startswith(f"{alias_norm} ") and "(" in primary_norm:
            return False

    header_categories = [
        _normalize(str(text).split("|")[0].strip())
        for text in header_texts
        if str(text).strip()
    ]

    for text_norm in header_categories:
        if not text_norm or text_norm == primary_norm:
            continue
        if alias_norm == text_norm:
            return True
        if alias_norm in text_norm:
            return True

    return False


def _are_distinct_category_variants(left: str, right: str) -> bool:
    """Return True when two similar category names refer to different costs."""
    if left == right:
        return False

    shorter, longer = sorted((left, right), key=len)
    return shorter in longer


def _entry_match_score(
    entry: CostMappingEntry,
    header_texts: list[str],
    lookup_keys: list[str],
) -> int:
    """Prefer longer, more specific agreement alias matches."""
    best = 0

    for alias in entry.agreement_aliases:
        if not _category_matches(alias, header_texts, lookup_keys):
            continue

        best = max(best, len(_normalize(alias)))

    return best


def _rate_by_matches(rate_by: str, header_texts: list[str], lookup_keys: list[str]) -> bool:
    """Match a Rate by value from txt against agreement header rows."""
    rate_by_norm = _normalize(rate_by)
    if not rate_by_norm:
        return False

    prefixed = _normalize(f"Rate by: {rate_by}")

    for text in [*header_texts, *lookup_keys]:
        text_norm = _normalize(str(text))
        if not text_norm:
            continue

        if prefixed in text_norm or text_norm == prefixed:
            return True

        if text_norm.startswith("rate by:") and rate_by_norm in text_norm:
            return True

        if text_norm == rate_by_norm:
            return True

    return False


def _split_mapping_line(line: str) -> tuple[str, str] | None:
    """Split one mapping line into rate card and agreement parts."""
    for prefix in sorted(AGREEMENT_PREFIXES, key=len, reverse=True):
        pattern = rf"\s-\s({re.escape(prefix)}.*)$"
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            return line[: match.start()].strip(), match.group(1).strip()

    return None


def _parse_agreement_side(agreement_part: str) -> tuple[list[str], str | None]:
    """
    Split agreement aliases and optional Rate by suffix.

    Agreement aliases separated by `` or `` are alternative header names for the
    same rate card cost (either name may appear in the agreement), for example::

        Handling Fee (OUT, End customer) or Handling Fee (HANDLING OUT FP - ...)
    """
    rate_by_match = RATE_BY_PATTERN.search(agreement_part)
    rate_by = rate_by_match.group(1).strip() if rate_by_match else None

    agreement_text = RATE_BY_PATTERN.sub("", agreement_part).strip()
    aliases = [part.strip() for part in OR_SPLIT_PATTERN.split(agreement_text) if part.strip()]
    return aliases, rate_by


def load_cost_mappings(path: Path | None = None) -> CostMappings:
    """Load cost name mappings from the txt file."""
    mappings_path = path or DEFAULT_MAPPINGS_PATH
    if not mappings_path.exists():
        return CostMappings()

    entries: list[CostMappingEntry] = []

    for raw_line in mappings_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or SEPARATOR_PATTERN.match(line):
            continue

        split = _split_mapping_line(line)
        if split is None:
            continue

        rate_card_name, agreement_part = split
        agreement_aliases, rate_by = _parse_agreement_side(agreement_part)
        if not agreement_aliases:
            continue

        entries.append(
            CostMappingEntry(
                rate_card_name=rate_card_name,
                agreement_aliases=agreement_aliases,
                rate_by=rate_by,
            )
        )

    return CostMappings(entries=entries)


def _entry_matches_agreement(
    entry: CostMappingEntry,
    header_texts: list[str],
    lookup_keys: list[str],
) -> bool:
    """
    Return True when an agreement column matches a mapping entry.

    Any one agreement alias may match (OR semantics from the txt file).
    Entries with ``+ Rate by: ...`` require BOTH the cost name and Rate by value.
    """
    for alias in entry.agreement_aliases:
        if not _category_matches(alias, header_texts, lookup_keys):
            continue

        if entry.rate_by:
            if not _rate_by_matches(entry.rate_by, header_texts, lookup_keys):
                continue

        return True

    return False
