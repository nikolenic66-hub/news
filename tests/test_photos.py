from app.photos import _license_is_redistributable


def test_accepts_reusable_commons_licenses():
    assert _license_is_redistributable("CC BY 4.0")
    assert _license_is_redistributable("CC BY-SA 4.0")
    assert _license_is_redistributable("CC0 1.0")
    assert _license_is_redistributable("Public domain")
    assert _license_is_redistributable("PD-old-100")


def test_rejects_noncommercial_and_all_rights_reserved():
    assert not _license_is_redistributable("CC BY-NC 4.0")
    assert not _license_is_redistributable("CC BY-NC-SA 4.0")
    assert not _license_is_redistributable("All rights reserved")
    assert not _license_is_redistributable("")
