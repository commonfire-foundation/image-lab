import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import image_lab as lab


class ImageLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "red.png"
        Image.new("RGB", (120, 60), "red").save(self.image)

    def run_cli(self, *args):
        with contextlib.redirect_stderr(io.StringIO()):
            return lab.main(list(args))

    def test_pixel_measurements(self):
        info, image = lab.inspect_image(self.image)
        self.assertEqual(image.size, (120, 60))
        self.assertEqual(info["aspect_ratio"], 2)
        self.assertAlmostEqual(info["mean_luminance"], 0.2126)
        self.assertAlmostEqual(info["luminance_std"], 0)
        swatch = info["palette"][0]
        self.assertEqual(swatch["hex"], "#ff0000")
        self.assertEqual(swatch["fraction"], 1.0)
        self.assertEqual(swatch["rgb"], [255, 0, 0])
        self.assertEqual(swatch["hsl"], [0.0, 100.0, 50.0])
        self.assertEqual(info["dhash64"], "0000000000000000")
        self.assertEqual(info["edge_density_3x3"], [[0.0] * 3] * 3)

    def test_transparency(self):
        path = self.root / "transparent.png"
        Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(path)
        info, _ = lab.inspect_image(path)
        self.assertTrue(info["has_alpha_channel"])
        self.assertAlmostEqual(info["mean_luminance"], 1)

    def test_orientation(self):
        path = self.root / "oriented.jpg"
        image = Image.new("RGB", (120, 60))
        exif = Image.Exif()
        exif[274] = 6
        image.save(path, exif=exif)
        info, _ = lab.inspect_image(path)
        self.assertEqual((info["width"], info["height"]), (60, 120))

    def test_analysis_preserves_original_and_refuses_overwrite(self):
        original = self.image.read_bytes()
        output = self.root / "output.jsonl"
        with patch.object(lab, "api", side_effect=AssertionError("Unexpected network call")):
            self.assertEqual(self.run_cli("analyze", str(self.image), "--output", str(output)), 0)
        record = json.loads(output.read_text())
        self.assertEqual(record["status"], "ok")
        self.assertIsNone(record["vision"])
        saved = output.read_bytes()
        self.assertEqual(self.run_cli("analyze", str(self.image), "--output", str(output)), 1)
        self.assertEqual(output.read_bytes(), saved)
        self.assertEqual(self.run_cli("analyze", str(self.image), "--output", str(self.image)), 1)
        self.assertEqual(self.image.read_bytes(), original)

    def test_corrupt_image_recorded(self):
        path = self.root / "broken.png"
        path.write_text("not an image")
        output = self.root / "output.jsonl"
        self.assertEqual(self.run_cli("analyze", str(self.root), "--output", str(output)), 1)
        records = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual([r["status"] for r in records], ["error", "ok"])

    def test_missing_model_does_not_create_output(self):
        output = self.root / "output.jsonl"
        with patch.object(lab, "api", return_value={"models": []}):
            self.assertEqual(self.run_cli("analyze", str(self.image), "--vision", "--output", str(output)), 1)
        self.assertFalse(output.exists())

    def test_description_schema(self):
        value = {"caption": "Red", "subjects": [], "medium": "abstract", "mood": [],
                 "lighting": [], "composition": [], "tags": ["red"],
                 "text_present": False, "watermark_present": False}
        self.assertEqual(lab.validate_description(value), value)
        with self.assertRaises(ValueError):
            lab.validate_description({**value, "text_present": "false"})
        with self.assertRaises(ValueError):
            lab.validate_description({**value, "tags": ["x"] * 13})
        with patch.object(lab, "api", return_value={"message": {"content": json.dumps(value)}}) as api:
            description, _ = lab.describe_image(Image.new("RGB", (1500, 1000)), lab.MODEL)
            self.assertEqual(description, value)
            payload = api.call_args.args[1]
            self.assertFalse(payload["think"])
            self.assertEqual(payload["options"]["num_ctx"], 4096)
            self.assertEqual(len(payload["messages"][0]["images"]), 1)

    def test_vision_continuation_and_preview(self):
        value = {"caption": "Red", "subjects": [], "medium": "abstract", "mood": [],
                 "lighting": [], "composition": [], "tags": ["red"],
                 "text_present": False, "watermark_present": False}
        continuation = json.dumps(value)[len(lab.JSON_PREFIX):]
        with patch.object(lab, "api", return_value={"message": {"content": continuation}, "done_reason": "stop"}) as api:
            description, details = lab.describe_image(Image.new("RGB", (1500, 1000)), lab.MODEL)
        self.assertEqual(description, value)
        self.assertEqual(details["vision_response"]["preview_width"], 768)
        self.assertLessEqual(details["vision_response"]["preview_height"], 768)
        payload = api.call_args.args[1]
        self.assertEqual(payload["messages"][-1]["content"], lab.JSON_PREFIX)
        self.assertIn('"boolean"', payload["messages"][0]["content"])

    def test_vision_failures_preserve_diagnostics(self):
        for content, reason, expected in [("", "length", "token budget"),
                                          ("", "stop", "no final JSON"),
                                          ("not json", "stop", "Expecting"),
                                          ('{"caption":"only"}', "stop", "missing")]:
            with self.subTest(content=content, reason=reason):
                response = {"message": {"content": content, "thinking": "internal"},
                            "done_reason": reason, "eval_count": 1024, "total_duration": 100}
                with patch.object(lab, "api", return_value=response):
                    with self.assertRaises(lab.VisionResponseError) as error:
                        lab.describe_image(Image.new("RGB", (20, 20)), lab.MODEL)
                self.assertIn(expected, str(error.exception))
                self.assertEqual(error.exception.details["ollama_timing_ns"]["eval_count"], 1024)
                self.assertEqual(error.exception.details["vision_response"]["thinking_chars"], 8)
                self.assertNotIn("internal", json.dumps(error.exception.details))

    def test_cli_vision_failure_keeps_timing(self):
        output = self.root / "failure.jsonl"
        responses = [{"models": [{"name": lab.MODEL}]}, {"version": "test"},
                     {"message": {"content": ""}, "done_reason": "length", "eval_count": 1024}]
        with patch.object(lab, "api", side_effect=responses):
            self.assertEqual(self.run_cli("analyze", str(self.image), "--vision", "--output", str(output)), 1)
        record = json.loads(output.read_text())
        self.assertEqual(record["status"], "error")
        self.assertEqual(record["ollama_timing_ns"]["eval_count"], 1024)
        self.assertEqual(record["vision_settings"]["preview_size"], 768)
        self.assertEqual(record["prompt_version"], lab.PROMPT_VERSION)

    def test_label_cleanup_preserves_raw_output(self):
        raw = {"caption": " Moon and bats ", "subjects": ["Moon", "bat", "BAT", " "],
               "medium": "illustration", "mood": ["dark"], "lighting": [], "composition": [],
               "tags": [" NIGHT ", "night", "moon  light", "nighttime"],
               "text_present": False, "watermark_present": False}
        with patch.object(lab, "api", return_value={"message": {"content": json.dumps(raw)}}):
            cleaned, details = lab.describe_image(Image.new("RGB", (30, 20)), lab.MODEL, 256)
        self.assertEqual(cleaned["subjects"], ["moon", "bat"])
        self.assertEqual(cleaned["tags"], ["night", "moon light", "nighttime"])
        self.assertEqual(cleaned["caption"], "Moon and bats")
        self.assertEqual(details["vision_raw"], raw)
        self.assertEqual(details["vision_response"]["preview_width"], 30)
        self.assertEqual(raw["subjects"], ["Moon", "bat", "BAT", " "])

    def test_discovery_deduplicates_and_limit(self):
        self.assertEqual(lab.discover([str(self.root), str(self.image)]), [self.image.resolve()])
        output = self.root / "output.jsonl"
        self.assertEqual(self.run_cli("analyze", str(self.image), "--limit", "0", "--output", str(output)), 1)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
