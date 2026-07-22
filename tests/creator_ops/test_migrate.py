from datetime import date

from creator_ops.domain import Platform
from creator_ops.migrate import eligible_legacy_creator_row, legacy_row_to_snapshot


def test_legacy_external_creator_is_not_eligible():
    assert not eligible_legacy_creator_row(
        {"user_id": "external"}, owned_user_ids={"owned"}
    )
    assert eligible_legacy_creator_row(
        {"user_id": "owned"}, owned_user_ids={"owned"}
    )


def test_legacy_snapshot_drops_profile_fields_and_hashes_identity():
    snapshot = legacy_row_to_snapshot(
        Platform.DOUYIN,
        {
            "user_id": "owned",
            "record_date": "2026-07-21",
            "nickname": "private name",
            "avatar": "https://private",
            "ip_location": "北京",
            "desc": "private description",
            "fans": "100",
            "follows": "2",
            "interaction": "300",
            "videos_count": "4",
        },
        owned_user_ids={"owned"},
    )

    assert snapshot is not None
    assert snapshot.snapshot_date == date(2026, 7, 21)
    assert "owned" not in snapshot.profile_key
    assert snapshot.metrics == {
        "follows": 2,
        "fans": 100,
        "interaction": 300,
        "videos_count": 4,
    }
