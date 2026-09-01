from marketing_diagnosis.ctrip_report import overview_html


def test_ctrip_overview_matches_compact_meituan_structure():
    output = overview_html(
        {
            "period_start": "2026-06-22",
            "period_end": "2026-07-21",
            "ctrip_summary": {"total_score": 13.8},
        }
    )

    assert "携程渠道经营与服务质量诊断" in output
    assert "覆盖经营趋势、流量、客群、推广、口碑及平台配置等22项诊断内容" in output
    assert "2026-06-22 至 2026-07-21" in output
    assert "携程综合得分" in output
    assert ">13.8</strong>" in output
    assert "满分100分" in output

    assert "计分模块" not in output
    assert "展示模块" not in output
    assert "已接入模块" not in output
    assert "01、02数据" not in output
    assert "03以后数据" not in output
    assert "两个页面中的01、02" not in output
