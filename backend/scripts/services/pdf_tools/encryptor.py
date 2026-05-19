from pathlib import Path

import fitz


def encrypt_pdf(
    input_path: Path,
    output_path: Path,
    user_pw: str = "",
    owner_pw: str = "",
    permissions: int = -1,
) -> dict:
    """
    Encrypt PDF with AES-256.
    permissions: -1 = all allowed, or bitwise OR of fitz.PDF_PERM_* flags.
    """
    doc = fitz.open(input_path)
    encrypt_kw = {
        "encryption": fitz.PDF_ENCRYPT_AES_256,
        "owner_pw": owner_pw or user_pw or "default",
        "permissions": permissions,
    }
    if user_pw:
        encrypt_kw["user_pw"] = user_pw
    doc.save(output_path, **encrypt_kw)
    doc.close()
    return {"encrypted": True, "has_user_pw": bool(user_pw)}


def decrypt_pdf(input_path: Path, output_path: Path, password: str = "") -> dict:
    """Decrypt password-protected PDF."""
    doc = fitz.open(input_path)
    if doc.is_encrypted:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("Incorrect password")
    doc.save(output_path, deflate=True, garbage=4)
    doc.close()
    return {"decrypted": True}


def is_encrypted(input_path: Path) -> bool:
    """Check if PDF is encrypted."""
    doc = fitz.open(input_path)
    encrypted = doc.is_encrypted
    doc.close()
    return encrypted
