import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from report_common import cargo_audit_findings, cargo_clippy_findings


class RustReportParsingTest(unittest.TestCase):
    def test_cargo_clippy_findings_reads_json_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "cargo-clippy.json").write_text(json.dumps([
                {
                    "code": "clippy::needless_return",
                    "level": "warning",
                    "message": "unneeded `return` statement",
                    "file": "src/lib.rs",
                    "line": 5,
                }
            ]))

            self.assertEqual(
                cargo_clippy_findings(out)[0]["code"],
                "clippy::needless_return",
            )

    def test_cargo_audit_findings_extracts_vulnerabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "cargo-audit.json").write_text(json.dumps({
                "runs": [
                    {
                        "source": "Cargo.lock",
                        "report": {
                            "vulnerabilities": {
                                "list": [
                                    {
                                        "advisory": {
                                            "id": "RUSTSEC-0000-0000",
                                            "title": "fixture vulnerability",
                                            "severity": "low",
                                        },
                                        "package": {
                                            "name": "fixture",
                                            "version": "0.1.0",
                                        },
                                    }
                                ]
                            }
                        },
                    }
                ]
            }))

            finding = cargo_audit_findings(out)[0]
            self.assertEqual(finding["id"], "RUSTSEC-0000-0000")
            self.assertEqual(finding["package"], "fixture")
            self.assertEqual(finding["source"], "Cargo.lock")


if __name__ == "__main__":
    unittest.main()
