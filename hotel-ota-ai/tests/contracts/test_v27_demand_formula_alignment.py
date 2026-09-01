from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path

from runtime.algorithms.demand_index import FORMULA_VERSION, WEIGHTS, calculate_demand_index
from runtime.algorithms.run_context import build_run_context


ROOT = Path(__file__).resolve().parents[2]
NEW_FORMULA = (
    "\u9700\u6c42\u6307\u6570=\u65e5\u671f\u73af\u5883\u520620%+"
    "\u533a\u57df\u70ed\u5ea6\u520615%+\u5386\u53f2\u540c\u671f\u520615%+"
    "\u5f53\u524d\u9884\u8ba2\u8fdb\u5ea6\u520620%+\u5f53\u524d\u6d41\u91cf\u520610%+"
    "\u5f53\u524d\u8f6c\u5316\u520610%+\u623f\u578b\u5e93\u5b58\u538b\u529b\u520610%"
)
OLD_FORMULA = (
    "\u9700\u6c42\u6307\u6570=\u5386\u53f2\u9700\u6c42\u520620%+"
    "\u5f53\u524d\u8fdb\u5ea6\u520625%+\u6d41\u91cf15%+\u8f6c\u531615%+"
    "\u5e93\u5b58\u538b\u529b15%+\u65e5\u671f\u5c5e\u602710%"
)


def _bp01_formula_values(payload: object) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        if payload.get("blueprint_id") == "BP01" and payload.get("formula_or_rule"):
            values.append(str(payload["formula_or_rule"]))
        for value in payload.values():
            values.extend(_bp01_formula_values(value))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_bp01_formula_values(item))
    return values


class TestV27DemandFormulaAlignment(unittest.TestCase):
    def test_runtime_contract_rules_and_reference_json_use_revised_formula(self) -> None:
        result = calculate_demand_index(build_run_context())
        self.assertEqual(FORMULA_VERSION, "revised_first_formula_v27")
        self.assertEqual(result["formula_or_rule"], NEW_FORMULA)
        self.assertEqual(set(result["sub_scores"]), set(WEIGHTS))

        field_registry = (ROOT / "contracts" / "v27" / "field_registry.yaml").read_text(encoding="utf-8")
        compatible_field_registry = (ROOT / "contracts" / "field_registry.yaml").read_text(encoding="utf-8")
        rules = json.loads((ROOT / "runtime" / "algorithm_rules" / "demand_rules.yaml").read_text(encoding="utf-8"))
        reference_json = json.loads(
            (
                ROOT
                / "docs"
                / "architecture_reference"
                / "v27"
                / "\u9152\u5e97OTA_AI\u6570\u5b57\u5458\u5de5_\u534f\u4f5c\u5f00\u53d1\u603b\u5730\u56fe_V27_\u9879\u76ee\u4fee\u590d\u53ef\u6267\u884c\u5951\u7ea6\u7248.json"
            ).read_text(encoding="utf-8")
        )
        compiled_contract = json.loads((ROOT / "contracts" / "v27" / "contract.json").read_text(encoding="utf-8"))
        reference_md = (
            ROOT / "docs" / "architecture_reference" / "v27" / "01-\u9700\u6c42\u6307\u6570\u4e0e\u6d41\u91cf\u5cf0\u8c37\u7b97\u6cd5.md"
        ).read_text(encoding="utf-8")

        for label, text in {
            "contracts/v27/field_registry.yaml": field_registry,
            "contracts/field_registry.yaml": compatible_field_registry,
        }.items():
            with self.subTest(label=label):
                self.assertIn(NEW_FORMULA, text)
                self.assertNotIn(OLD_FORMULA, text)

        self.assertEqual(rules["algorithm"]["formula_version"], "revised_first_formula_v27")
        self.assertEqual(rules["algorithm"]["formula_or_rule"], NEW_FORMULA)
        self.assertEqual(rules["algorithm"]["weights"], WEIGHTS)

        for label, payload in {
            "contracts/v27/contract.json": compiled_contract,
            "v27 reference json": reference_json,
        }.items():
            formula_values = _bp01_formula_values(payload)
            with self.subTest(label=label):
                self.assertTrue(formula_values)
                self.assertTrue(all(value == NEW_FORMULA for value in formula_values))

        self.assertIn("formula_version=revised_first_formula_v27", reference_md)
        self.assertIn("当前 active formula", reference_md)
        self.assertIn("deprecated_legacy_formula", reference_md)

    def test_v27_xlsx_and_drawio_do_not_carry_legacy_formula_text(self) -> None:
        reference_dir = ROOT / "docs" / "architecture_reference" / "v27"
        xlsx = next(path for path in reference_dir.iterdir() if path.suffix == ".xlsx" and "V27" in path.name)
        drawio = next(path for path in reference_dir.iterdir() if path.suffix == ".drawio" and "V27" in path.name)
        with zipfile.ZipFile(xlsx) as archive:
            xlsx_text = "".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
                if name.endswith(".xml")
            )
        drawio_text = drawio.read_text(encoding="utf-8", errors="ignore")

        for label, text in {"v27 xlsx": xlsx_text, "v27 drawio": drawio_text}.items():
            with self.subTest(label=label):
                self.assertNotIn(OLD_FORMULA, text)


if __name__ == "__main__":
    unittest.main()
