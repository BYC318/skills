#!/usr/bin/env python3
"""用合成图检验取证门禁，测试产物不能作为 App 验收证据。"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("ui_evidence", Path(__file__).with_name("ui_evidence.py"))
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


def synthetic_png(red):
    """生成带明确测试用途的微型 PNG 字节，不使用真实用户或应用数据。"""
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)
    pixels = b"".join(b"\0" + bytes([red, 80, 100]) * 20 for _ in range(40))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 20, 40, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="evidence-test-", dir=os.environ["UI_EVIDENCE_TEST_ROOT"])
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        self.root = self.base / "evidence"
        self.root.mkdir()
        self.project_patch = patch.object(ui, "PROJECT", self.project)
        self.project_patch.start()
        self.builds = {p: {"commit": "a" * 40, "worktree_digest": "b" * 64, "artifact_sha256": ("c" if p == "ios" else "d") * 64} for p in ("ios", "android")}
        self.build_path = self.json_file("builds.json", self.builds)
        self.image = self.base / "synthetic.png"
        self.image.write_bytes(synthetic_png(110))
        self.support = self.base / "synthetic-layout.txt"
        self.support.write_text("合成测试布局记录，不是 App 证据", encoding="utf-8")
        self.resources = self.json_file("resources.json", {"purpose": "合成测试资源清单，不是设计交付", "assets": []})
        self.ledger = self.project / "任务记录" / "合成测试" / "ui-evidence.json"
        self.assertEqual(self.call("init", "--name", "合成测试", "--scope", "自动化自检，非 App 验收", "--evidence-root", self.root), 0)
        self.assertEqual(self.call("add-page", self.ledger, "--page", "test-1", "--module", "测试", "--title", "合成测试页", "--state-id", "empty", "--state", "空值", "--locale", "en", "--baseline", "B001", "--file-key", "testFile", "--node-id", "1:2"), 0)

    def tearDown(self):
        self.project_patch.stop()
        self.temp.cleanup()

    def json_file(self, name, value):
        path = self.base / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def call(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["ui_evidence.py"] + [str(a) for a in args]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = ui.main()
        self.output = stdout.getvalue() + stderr.getvalue()
        return result

    def start_round(self, bind=True):
        if bind:
            for key in ui.VARIANTS[1:]:
                self.assertEqual(self.call("bind-reference", self.ledger, "--page", "test-1", "--variant", key, "--locale", "ar" if key.endswith("rtl") else "en", "--baseline", "B001", "--file-key", "testFile", "--node-id", "1:2", "--basis-note", "合成测试设计映射"), 0)
        self.assertEqual(self.call("round", self.ledger, "--page", "test-1", "--builds", self.build_path), 0)

    def metadata(self, variant, platform):
        theme, direction = variant.split("-")
        meta = {"page_id": "test-1", "state_id": "empty", "baseline_id": "B001", "theme": theme, "direction": direction, "locale": "ar" if direction == "rtl" else "en", "captured_at": "2026-10-27T17:00:00+08:00"}
        if platform == "figma":
            meta.update(file_key="testFile", node_id="1:2", resources_manifest_path=str(self.resources))
        else:
            meta.update(effective_theme=theme, effective_direction=direction, application_id="test.app", foreground_application_id="test.app", route="合成测试入口", data_source="fixture", debug_only=True, normal_entry_verified=True, raw_screenshot=True, identity_verified=True, stability_verified=True, anchors=["合成测试标题", "合成测试空值状态"], device={"alias": "测试设备", "os": "测试系统", "orientation": "portrait", "width": 20, "height": 40, "scale": 1}, build=self.builds[platform], layout_path=str(self.support))
        return meta

    def capture(self, variant, platform, metadata=None):
        path = self.json_file("capture.json", metadata or self.metadata(variant, platform))
        return self.call("attach", self.ledger, "--page", "test-1", "--variant", variant, "--platform", platform, "--image", self.image, "--metadata", path)

    def review(self, variant, failed=False):
        checks = {k: {"status": "pass", "note": "合成测试检查依据，不是 App 审查"} for k in ui.CHECKS}
        if failed:
            checks["layout"]["status"] = "fail"
        review = {"reviewer": "自动化测试", "reviewed_at": "2026-10-27T17:01:00+08:00", "open_issues": ["合成布局差异"] if failed else [], "checks": checks}
        return self.call("review", self.ledger, "--page", "test-1", "--variant", variant, "--review", self.json_file("review.json", review))

    def stats(self):
        data, root = ui.load(self.ledger)
        return ui.summary(data, root)

    def complete(self):
        self.start_round()
        for variant in ui.VARIANTS:
            for platform in ("figma", "ios", "android"):
                self.assertEqual(self.capture(variant, platform), 0, self.output)
            self.assertEqual(self.review(variant), 0, self.output)
        self.assertEqual(self.call("inventory", self.ledger, "--basis", "合成测试完整节点清单"), 0)

    def test_empty_or_one_combination_cannot_claim_complete(self):
        self.assertFalse(self.stats()["complete"])
        self.start_round()
        for platform in ("figma", "ios", "android"):
            self.assertEqual(self.capture("light-ltr", platform), 0)
        self.assertEqual(self.review("light-ltr"), 0)
        self.assertEqual(self.stats()["captures"], 2)
        self.assertEqual(self.stats()["passed"], 0)
        self.assertEqual(self.call("check", self.ledger, "--require-complete"), 1)

    def test_all_eight_runtime_images_and_four_reviews_required(self):
        self.complete()
        self.assertEqual(self.stats()["captures"], 8)
        self.assertEqual(self.stats()["passed"], 1)
        self.assertEqual(self.call("check", self.ledger, "--require-complete"), 0)
        ledger = ui.read_json(self.ledger)
        ledger["pages"][0]["rounds"][0]["captures"]["dark-rtl"].pop("android")
        ui.write_json(self.ledger, ledger)
        self.assertEqual(self.call("check", self.ledger, "--require-complete"), 1)
        self.assertEqual(self.stats()["captures"], 7)

    def test_wrong_direction_theme_foreground_and_build_rejected(self):
        self.start_round()
        for field, value in [("direction", "rtl"), ("effective_theme", "dark"), ("foreground_application_id", "other.app"), ("debug_only", False)]:
            meta = self.metadata("light-ltr", "ios")
            meta[field] = value
            before = self.ledger.read_bytes()
            self.assertEqual(self.capture("light-ltr", "ios", meta), 2)
            self.assertEqual(self.ledger.read_bytes(), before)
        meta = copy.deepcopy(self.metadata("light-ltr", "ios"))
        meta["build"]["artifact_sha256"] = "e" * 64
        self.assertEqual(self.capture("light-ltr", "ios", meta), 2)
        self.assertFalse(list(self.root.rglob("raw.png")))

    def test_missing_design_basis_still_allows_runtime_archiving(self):
        self.start_round(bind=False)
        for variant in ui.VARIANTS:
            for platform in ("ios", "android"):
                self.assertEqual(self.capture(variant, platform), 0)
        result = self.stats()
        self.assertEqual(result["captures"], 8)
        self.assertEqual(result["pages"][0]["variants"]["dark-rtl"]["status"], "待设计依据")
        self.assertEqual(result["passed"], 0)

    def test_hash_tampering_and_path_escape_block_completion(self):
        self.complete()
        raw = next(self.root.rglob("raw.png"))
        original = raw.read_bytes()
        raw.write_bytes("这不是 PNG 原图".encode())
        self.assertEqual(self.call("check", self.ledger), 1)
        raw.write_bytes(original)
        ledger = ui.read_json(self.ledger)
        ledger["pages"][0]["rounds"][0]["captures"]["light-ltr"]["ios"]["image"]["path"] = "../outside.png"
        ui.write_json(self.ledger, ledger)
        self.assertEqual(self.call("check", self.ledger), 1)

    def test_history_is_not_overwritten_and_invalidated_round_not_passed(self):
        self.complete()
        hashes = {str(p): ui.sha(p.read_bytes()) for p in self.root.rglob("raw.png")}
        self.assertEqual(self.capture("light-ltr", "ios"), 2)
        self.assertEqual(self.call("round", self.ledger, "--page", "test-1", "--builds", self.build_path), 0)
        self.assertEqual(self.capture("light-ltr", "ios"), 0)
        self.assertEqual(self.call("invalidate", self.ledger, "--page", "test-1", "--reason", "测试共享组件变化"), 0)
        self.assertEqual(self.stats()["pages"][0]["status"], "需复验")
        self.assertEqual(len(ui.read_json(self.ledger)["pages"][0]["rounds"]), 2)
        self.assertTrue(all(ui.sha(Path(p).read_bytes()) == value for p, value in hashes.items()))

    def test_unreviewed_or_failed_visual_result_not_passed(self):
        self.start_round()
        for platform in ("figma", "ios", "android"):
            self.assertEqual(self.capture("dark-rtl", platform), 0)
        self.assertEqual(self.stats()["pages"][0]["variants"]["dark-rtl"]["status"], "待验收")
        self.assertEqual(self.review("dark-rtl", failed=True), 0)
        self.assertEqual(self.stats()["pages"][0]["variants"]["dark-rtl"]["status"], "有差异")

    def test_design_or_expected_build_change_marks_old_evidence_stale(self):
        self.complete()
        ledger = ui.read_json(self.ledger)
        ledger["pages"][0]["variants"]["dark-rtl"]["baseline_id"] = "B002"
        ui.write_json(self.ledger, ledger)
        result = self.stats()["pages"][0]
        self.assertEqual(result["variants"]["dark-rtl"]["status"], "需复验")
        self.assertEqual(result["variants"]["light-ltr"]["status"], "已通过")
        ledger["pages"][0]["expected_builds"]["ios"]["artifact_sha256"] = "e" * 64
        ui.write_json(self.ledger, ledger)
        self.assertEqual(self.stats()["pages"][0]["variants"]["light-ltr"]["status"], "需复验")

    def delivery(self):
        self.assertEqual(self.call("deliver", self.ledger), 0, self.output)
        result = json.loads(self.output)
        self.assertTrue(result["completion_allowed"])
        return Path(result["receipt"])

    def test_delivery_blocks_empty_missing_review_and_incomplete_inventory(self):
        self.assertEqual(self.call("deliver", self.ledger), 1)
        self.assertFalse(json.loads(self.output)["completion_allowed"])
        self.complete()
        original = self.ledger.read_bytes()
        for kind in ("empty", "image", "review", "failed-review", "inventory"):
            ledger = json.loads(original)
            run = ledger["pages"][0]["rounds"][0]
            if kind == "empty":
                ledger["pages"] = []
            elif kind == "image":
                run["captures"]["dark-rtl"].pop("android")
            elif kind == "review":
                run["review"].pop("dark-rtl")
            elif kind == "failed-review":
                run["review"]["dark-rtl"]["checks"]["layout"]["status"] = "fail"
            else:
                ledger["task"]["inventory_complete"] = False
            ui.write_json(self.ledger, ledger)
            self.assertEqual(self.call("deliver", self.ledger), 1, kind)
            self.assertFalse(json.loads(self.output)["completion_allowed"])
        self.assertFalse((self.root / "deliveries").exists())

    def test_delivery_receipt_binds_snapshot_reviews_and_archive_links(self):
        self.complete()
        before = self.ledger.read_bytes()
        receipt_path = self.delivery()
        receipt = ui.read_json(receipt_path)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(receipt["ledger"]["sha256"], ui.sha(before))
        self.assertEqual(len(receipt["reviews"]), 4)
        self.assertEqual(receipt["summary"]["captures"], 8)
        self.assertEqual((receipt_path.parent / "台账快照.json").read_bytes(), before)
        self.assertIn('<base href="../../">', (receipt_path.parent / "验收册.html").read_text())
        self.assertEqual(self.call("verify-delivery", self.ledger, "--receipt", receipt_path), 0, self.output)
        archive = {p: p.read_bytes() for p in receipt_path.parent.iterdir()}
        self.assertNotEqual(self.delivery(), receipt_path)
        self.assertTrue(all(p.read_bytes() == data for p, data in archive.items()))

    def test_old_receipt_rejected_after_baseline_build_round_or_scope_change(self):
        self.complete()
        receipt = self.delivery()
        before = self.ledger.read_bytes()
        for kind in ("baseline", "build", "round", "scope"):
            ledger = json.loads(before)
            if kind == "baseline":
                ledger["pages"][0]["variants"]["light-ltr"]["baseline_id"] = "B002"
            elif kind == "build":
                ledger["pages"][0]["expected_builds"]["ios"]["commit"] = "e" * 40
            elif kind == "round":
                ledger["pages"][0]["current_round"] = None
            else:
                ledger["task"]["scope"] = "调整后的范围"
            ui.write_json(self.ledger, ledger)
            self.assertEqual(self.call("verify-delivery", self.ledger, "--receipt", receipt), 2, kind)
        self.ledger.write_bytes(before)
        self.assertEqual(self.call("verify-delivery", self.ledger, "--receipt", receipt), 0, self.output)

    def test_receipt_rechecks_original_files_and_archived_artifacts(self):
        self.complete()
        receipt = self.delivery()
        ledger_bytes = self.ledger.read_bytes()
        for path in (next(self.root.rglob("raw.png")), next(self.root.rglob("layout.txt")), receipt.parent / "验收册.html"):
            before = path.read_bytes()
            path.write_bytes(b"tampered")
            self.assertEqual(self.call("verify-delivery", self.ledger, "--receipt", receipt), 2, path)
            path.unlink()
            self.assertEqual(self.call("verify-delivery", self.ledger, "--receipt", receipt), 2, path)
            path.write_bytes(before)
        self.assertEqual(self.ledger.read_bytes(), ledger_bytes)
        self.assertEqual(self.call("verify-delivery", self.ledger, "--receipt", receipt), 0, self.output)

    def test_receipt_cannot_be_reused_for_another_ledger_or_without_reviews(self):
        self.complete()
        receipt = self.delivery()
        other = self.base / "other-ledger.json"
        other.write_bytes(self.ledger.read_bytes())
        self.assertEqual(self.call("verify-delivery", other, "--receipt", receipt), 2)
        data = ui.read_json(receipt)
        data["reviews"] = []
        ui.write_json(receipt, data)
        self.assertEqual(self.call("verify-delivery", self.ledger, "--receipt", receipt), 2)

    def test_interrupted_snapshot_does_not_publish_receipt(self):
        self.complete()
        render = ui.render_report

        def change_during_render(ledger, root, announce=True):
            render(ledger, root, announce=announce)
            changed = ui.read_json(self.ledger)
            changed["task"]["scope"] = "模拟收尾期间更新"
            ui.write_json(self.ledger, changed)

        with patch.object(ui, "render_report", side_effect=change_during_render):
            self.assertEqual(self.call("deliver", self.ledger), 2)
        self.assertFalse(list(self.root.rglob("交付回执.json")))

    def test_real_cli_delivers_and_verifies_without_changing_ledger(self):
        self.complete()
        before = self.ledger.read_bytes()
        script = str(Path(ui.__file__).resolve())
        result = subprocess.run([sys.executable, "-B", script, "deliver", str(self.ledger)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)["receipt"]
        result = subprocess.run([sys.executable, "-B", script, "verify-delivery", str(self.ledger), "--receipt", receipt], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["completion_allowed"])
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_relocated_cli_uses_shared_resources_without_old_skill(self):
        project = self.base / "relocated-project"
        resources = project / "resources"
        for category in ("assets", "references", "scripts"):
            shutil.copytree(ui.RESOURCE_ROOT / category, resources / category,
                            ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", "*.pyc"))
        self.assertFalse((project / ".agents" / "skills" / "dual-platform-workflow").exists())
        self.assertFalse((project / ".agents" / "scripts").exists())
        evidence = self.base / "relocated-evidence"
        evidence.mkdir()
        script = resources / "scripts" / "ui-alignment" / "ui_evidence.py"
        result = subprocess.run([sys.executable, "-B", str(script), "init", "--name", "子目录工具测试",
                                 "--scope", "工具路径验证，不是 App 验收", "--evidence-root", str(evidence)],
                                cwd=self.base, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger = project / "任务记录" / "子目录工具测试" / "ui-evidence.json"
        self.assertTrue(ledger.is_file())
        note = (project / "任务记录" / "子目录工具测试.md").read_text()
        self.assertIn("../resources/references/ui-alignment/ui-evidence.md", note)
        self.assertNotIn("dual-platform-workflow", note)
        self.assertTrue((evidence / "验收册.html").is_file())
        before = ledger.read_bytes()
        for command, expected in [("check", 0), ("deliver", 1)]:
            result = subprocess.run([sys.executable, "-B", str(script), command, str(ledger)],
                                    cwd=self.base, capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stderr)
            if command == "deliver":
                self.assertFalse(json.loads(result.stdout)["completion_allowed"])
        self.assertEqual(ledger.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
