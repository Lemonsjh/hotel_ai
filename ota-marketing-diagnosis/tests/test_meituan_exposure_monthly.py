from marketing_diagnosis.meituan_exposure_monthly import patch_report_html, patch_visual_diagnosis


def _result() -> dict:
    return {
        "visual_diagnosis": {
            "items": [
                {
                    "standard_item_id": 3,
                    "base_score": 4,
                    "participates_in_score": True,
                    "item_score": None,
                }
            ]
        }
    }


def test_item03_uses_one_latest_row_and_database_ratio() -> None:
    result = _result()
    patch_visual_diagnosis(result, {
        "exposure_daily": [
            {
                "business_date": "2026-07-27",
                "snapshot_time": "2026-07-28 08:00:00",
                "total_exposure": 1,
                "non_ad_exposure": 1,
                "ad_exposure": 0,
                "ad_exposure_ratio_pct": 0,
            },
            {
                "business_date": "2026-07-27",
                "snapshot_time": "2026-07-28 09:45:48",
                "total_exposure": 75656,
                "non_ad_exposure": 61638,
                "ad_exposure": 14018,
                "ad_exposure_ratio_pct": 18.5286,
            },
        ]
    })
    item = result["visual_diagnosis"]["items"][0]
    assert [field["value"] for field in item["fields"]] == [75656.0, 61638.0, 14018.0, 0.185286]
    assert item["item_score"] == 2.0
    assert item["records"][0]["snapshot_time"] == "2026-07-28 09:45:48"
    assert item["source_table"].endswith("meituan_ota_exposure_source_monthly")


def test_item03_missing_ratio_does_not_recalculate_it() -> None:
    result = _result()
    patch_visual_diagnosis(result, {
        "exposure_daily": [{
            "business_date": "2026-07-27",
            "total_exposure": 100,
            "non_ad_exposure": 70,
            "ad_exposure": 30,
        }]
    })
    item = result["visual_diagnosis"]["items"][0]
    assert item["fields"][3]["value"] is None
    assert item["item_score"] is None


def test_report_item03_period_is_rolling_30_days_as_of_yesterday() -> None:
    html = """<div>近30天</div><article id='rule-3'><p>展示整体曝光、非广告曝光、广告曝光及每日广告曝光占比。</p><strong>近30天</strong></article>"""
    output = patch_report_html(html)
    assert output.startswith("<div>近30天</div>")
    assert "<strong>近30天</strong>" in output
    assert "展示截至昨日的近30天总曝光" in output


def test_report_item03_rewrites_legacy_metric_lookup_label() -> None:
    html = "<article id='rule-3'><small>整体曝光（近30天）</small><strong>75,656.00</strong></article>"
    output = patch_report_html(html)
    assert "总曝光（近30天）" in output
    assert "75,656.00" in output
