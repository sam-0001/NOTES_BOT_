"""
utils/sections.py
~~~~~~~~~~~~~~~~~
Helper for normalising the sections data structure.

Subjects store files as:
    sections: [
        { "name": "Unit 1",      "file_ids": ["111", "222"] },
        { "name": "Short Notes", "file_ids": ["333"] },
    ]

For backward-compatibility, old subjects with a flat `telegram_file_ids`
list are migrated on-the-fly into a single "All Files" section.
"""


def get_sections(subject: dict) -> list[dict]:
    """Return the sections list, migrating legacy flat file_ids if needed."""
    if subject.get("sections"):
        return [normalise_section(sec) for sec in subject["sections"]]

    old_ids = subject.get("telegram_file_ids", [])
    if old_ids:
        return [{"name": "All Files", "file_ids": old_ids, "text_notes": [], "is_free": False, "price": 0}]

    return []


def normalise_section(section: dict) -> dict:
    """Return a section with the access fields newer code expects."""
    section.setdefault("file_ids", [])
    section.setdefault("text_notes", [])
    section.setdefault("is_free", False)
    section.setdefault("price", 0)
    return section


def section_item_count(section: dict) -> int:
    """Total deliverable items in a section: files + text notes."""
    return len(section.get("file_ids", [])) + len(section.get("text_notes", []))


def section_price(subject: dict, section: dict) -> int:
    """Return the section price, falling back to the subject price if needed."""
    price = section.get("price")
    if not section.get("is_free") and not price:
        price = subject.get("price", 0)
    return int(price or 0)


def is_section_free(subject: dict, section: dict) -> bool:
    """Free sections can be downloaded without a purchase."""
    return bool(section.get("is_free")) or section_price(subject, section) == 0


def has_subject_access(orders: list[dict], subject_id: str) -> bool:
    """Legacy/whole-subject orders have no section_idx and unlock every section."""
    return any(
        order.get("subject_id") == subject_id and order.get("section_idx") is None
        for order in orders
    )


def has_section_access(
    orders: list[dict],
    subject_id: str,
    section_idx: int,
    subject: dict,
    section: dict,
) -> bool:
    """Return True when a user can download one section."""
    if is_section_free(subject, section):
        return True
    if has_subject_access(orders, subject_id) and int(subject.get("price", 0) or 0) > 0:
        return True
    return any(
        order.get("subject_id") == subject_id
        and str(order.get("section_idx")) == str(section_idx)
        for order in orders
    )
