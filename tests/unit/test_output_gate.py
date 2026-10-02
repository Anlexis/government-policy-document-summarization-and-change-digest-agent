# The output boundary: what may leave, and what happens to a report that may not.
#
# Two properties are load-bearing here and both are easy to get subtly wrong:
#
#   1. The gate's leak rules are the PLATFORM's rules, not a local subset. A
#      local list narrower than the platform's lets a value reach a node whose
#      own gate then raises — and a raising node's whole result is discarded,
#      taking any clearing it did with it.
#   2. Withholding is an error status AND a non-empty replacement AND the other
#      report-bearing fields cleared. The output envelope reads the gated field
#      first and falls back to the ungated one, so a falsy replacement or a
#      populated leftover re-opens the path the gate just closed.

import pytest

from framework.security.credential_detector import detect_credentials_in_value
from src.services.output_gate import (
    DEADLINE_SECTION_HEADING,
    OUTPUT_BEARING_FIELDS,
    WITHHELD_NOTICE,
    carries_deadline_section,
    cleared_output_fields,
    scan_output,
)

# Assembled at run time rather than written inline: a connection string written
# out in full is what the repository's own credential scan exists to reject, and
# it rejects it in a fixture exactly as it would in shipped code.
CONNECTION_STRING = "".join(
    [
        "postgresql://",
        "svc",
        ":",
        "s3cretvalue",
        "@db.internal:5432/policies",
    ]
)

_CREDENTIAL_SHAPES = [
    "AKIAIOSFODNN7EXAMPLE",
    "sk_live_" + "0123456789abcdefghij",
    "sk-abcdefghijklmnopqrstuvwx",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",
    "Bearer aaaaaaaaaaaaaaaaaaaaaaaa",
    CONNECTION_STRING,
]


class TestDetectorParity:
    @pytest.mark.parametrize("value", _CREDENTIAL_SHAPES)
    def test_the_gate_blocks_everything_the_platform_detector_finds(self, value):
        """Pinned as a containment relation, not as a copied list: the gate may
        catch more than the platform does, never less. A local set narrower than
        the platform's is a way around the gate, not a smaller gate — the value
        reaches a node whose own gate then raises, and the raising node's whole
        result is discarded along with any clearing it performed."""
        assert detect_credentials_in_value(value)
        assert scan_output(value)

    def test_the_gate_also_catches_a_secret_written_as_an_assignment(self):
        """The shape a secret usually takes inside a document body, which the
        platform's value-shaped patterns do not recognise."""
        assert "assigned_secret" in scan_output("内部メモ password: hunter2xyz")
        assert not detect_credentials_in_value("内部メモ password: hunter2xyz")

    @pytest.mark.parametrize(
        "prose",
        [
            "本制度のトークン発行手続きについて",
            "The notice describes the access token lifecycle in general terms.",
            "秘密保持契約の締結が必要です。",
        ],
    )
    def test_the_local_addition_does_not_fire_on_ordinary_prose(self, prose):
        assert scan_output(prose) == []

    def test_a_category_name_is_reported_and_never_the_matched_text(self):
        categories = scan_output(f"接続情報 {CONNECTION_STRING}")
        assert "conn_string" in categories
        assert "s3cretvalue" not in "".join(categories)
        assert "db.internal" not in "".join(categories)

    def test_personal_data_is_part_of_the_same_scan(self):
        assert "individual_number" in scan_output("担当者の個人番号1234-5678-9012を確認")

    def test_a_clean_digest_scans_clean(self):
        assert scan_output("# 政策文書週次ダイジェスト — past_week\n\n対象省庁: 厚労省") == []


class TestDigestInvariant:
    def test_the_mandatory_section_is_recognised_in_the_markdown_rendering(self):
        assert carries_deadline_section(f"## {DEADLINE_SECTION_HEADING}\n\n- 今週の期限変更なし")

    def test_the_mandatory_section_is_recognised_after_the_plain_text_rendering(self):
        """The plain-text rendering strips leading markdown markers, so a check
        keyed on the marker would refuse every email digest it just rendered."""
        assert carries_deadline_section(f"{DEADLINE_SECTION_HEADING}\n\n- 今週の期限変更なし")

    def test_a_digest_without_the_section_is_not_releasable(self):
        assert not carries_deadline_section("# 政策文書週次ダイジェスト\n\n## 省庁別サマリー")


class TestWithholdingShape:
    def test_the_replacement_notice_is_non_empty(self):
        """A falsy replacement re-opens the envelope's fallback to the ungated
        field — the exact path the gate exists to close."""
        assert WITHHELD_NOTICE
        assert isinstance(WITHHELD_NOTICE, str)

    def test_the_replacement_notice_does_not_trip_the_gate_itself(self):
        assert scan_output(WITHHELD_NOTICE) == []

    def test_clearing_covers_every_field_that_can_carry_report_text(self):
        cleared = cleared_output_fields()
        assert set(cleared) == set(OUTPUT_BEARING_FIELDS)
        assert all(value is None for value in cleared.values())

    @pytest.mark.parametrize(
        "field",
        ["result", "formatted_output", "assembled_digest", "fetched_documents", "per_ministry_summaries"],
    )
    def test_the_pre_gate_assembly_fields_are_among_them(self, field):
        assert field in OUTPUT_BEARING_FIELDS
