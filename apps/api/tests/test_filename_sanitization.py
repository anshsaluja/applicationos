"""Filename sanitization must not turn untrusted upload metadata into paths or misleading labels."""

from app.documents import _safe_filename


def test_upload_filename_is_display_only_basename():
    assert _safe_filename(r"C:\\Users\\alice\\secret.txt") == "secret.txt"
    assert _safe_filename("../../private/evidence.txt") == "evidence.txt"
    assert _safe_filename("folder/subfolder/") == "document"


def test_upload_filename_strips_invisible_and_control_characters():
    assert _safe_filename("proof\u202eexe.txt") == "proofexe.txt"
    assert _safe_filename("proof\u200b.txt") == "proof.txt"
    assert _safe_filename("proof\n\t.txt") == "proof.txt"


def test_upload_filename_is_bounded_and_has_safe_fallback():
    assert _safe_filename(None) == "document"
    assert _safe_filename("\u200b\u202e") == "document"
    assert len(_safe_filename("a" * 1000)) == 240


def test_upload_filename_normalizes_equivalent_unicode():
    assert _safe_filename("re\u0301sume\u0301.txt") == "résumé.txt"
