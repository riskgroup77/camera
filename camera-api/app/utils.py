def compute_initials(full_name: str) -> str:
    """Mirrors the frontend's initials() helper (see
    src/components/admin/AddUserModal.tsx): first letter of the first two
    whitespace-separated words, uppercased."""
    words = full_name.split()
    return "".join(w[0].upper() for w in words[:2])
