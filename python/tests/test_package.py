from thoth_control_plane import CONTRACT_VERSION


def test_package_exposes_the_v1_contract_version() -> None:
    assert CONTRACT_VERSION == 1
