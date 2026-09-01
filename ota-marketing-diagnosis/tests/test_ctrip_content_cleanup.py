from marketing_diagnosis.dual_channel_report import (
    CTRIP_CONTENT_CLEANUP_SCRIPT,
    _strip_hidden_source_details,
)


def test_known_ctrip_source_blocks_are_removed_from_generated_html():
    source = """
    <div class='ctrip-source-v55'><b>携程数据来源：</b>携程 eBooking</div>
    <div class='ctrip-competition-source'><b>数据口径：</b>近30天</div>
    <div class='psi-source-v53'>
      <div><b>页面数据来源</b>携程 eBooking</div>
      <div><b>数据库来源与计分口径</b>ctrip_ota_psi_score</div>
    </div>
    """

    output = _strip_hidden_source_details(source)

    assert "携程数据来源" not in output
    assert "数据口径" not in output
    assert "页面数据来源" not in output
    assert "数据库来源与计分口径" not in output


def test_runtime_cleanup_covers_summary_source_column_and_key_conclusion():
    assert "数据来源" in CTRIP_CONTENT_CLEANUP_SCRIPT
    assert "重点结论" in CTRIP_CONTENT_CLEANUP_SCRIPT
    assert "removeSummarySourceColumn" in CTRIP_CONTENT_CLEANUP_SCRIPT
    assert ".page[data-channel-view=\"ctrip\"]" in CTRIP_CONTENT_CLEANUP_SCRIPT
