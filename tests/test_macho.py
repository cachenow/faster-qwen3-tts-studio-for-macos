import pytest

from scripts.build.check_macho import supports_macos_14


@pytest.mark.parametrize(("fields", "expected"), [
    ("cmd LC_BUILD_VERSION\n platform MACOS\n minos 14.0\n sdk 15.5\n tool LD\n version 1167.5", True),
    ("cmd LC_BUILD_VERSION\n platform MACOS\n minos 14.0.1", False),
    ("cmd LC_BUILD_VERSION\n platform MACOS\n tool LD\n version 12.0", False),
    ("cmd LC_BUILD_VERSION\n platform IOS\n minos 13.0", False),
    ("cmd LC_VERSION_MIN_MACOSX\n version 13.0\n sdk 15.5", True),
    ("cmd LC_VERSION_MIN_MACOSX\n version 15.0", False),
])
def test_deployment_target(fields, expected):
    assert supports_macos_14(f"binary (architecture arm64):\nLoad command 11\n {fields}\n") is expected
