import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import trim


class PlanSegmentsTest(unittest.TestCase):
    def test_keep_leftover(self):
        segs = trim.plan_segments(180, 14, "keep")
        self.assertEqual(len(segs), 13)
        self.assertTrue(all(s.duration == 14 for s in segs[:12]))
        self.assertEqual((segs[-1].start, segs[-1].end), (168, 180))

    def test_drop_leftover(self):
        segs = trim.plan_segments(180, 14, "drop")
        self.assertEqual(len(segs), 12)
        self.assertEqual(segs[-1].end, 168)

    def test_exact_multiple(self):
        self.assertEqual(len(trim.plan_segments(168, 14, "keep")), 12)

    def test_rounding_noise_is_not_a_clip(self):
        self.assertEqual(len(trim.plan_segments(168.02, 14, "keep")), 12)
        self.assertEqual(len(trim.plan_segments(167.99, 14, "keep")), 12)

    def test_shorter_than_n_exports_whole_video(self):
        for mode in ("keep", "drop"):
            segs = trim.plan_segments(9.5, 14, mode)
            self.assertEqual([(s.start, s.end) for s in segs], [(0, 9.5)])


class OutputNamesTest(unittest.TestCase):
    def test_suffix_when_existing(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            first = trim.output_names("vacation", 13, out, overwrite=False)
            self.assertEqual(first[0].name, "vacation_01.mp4")
            self.assertEqual(first[-1].name, "vacation_13.mp4")
            first[0].touch()
            self.assertEqual(trim.output_names("vacation", 13, out, False)[0].name, "vacation_01_v2.mp4")
            self.assertEqual(trim.output_names("vacation", 13, out, True)[0].name, "vacation_01.mp4")


@unittest.skipIf(trim.missing_tools(), "ffmpeg/ffprobe not installed")
class SplitVideoTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_180s_at_14s(self):
        src = self.dir / "my source.mp4"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
             "-f", "lavfi", "-i", "sine", "-t", "180", "-g", "30", "-c:v", "libx264",
             "-preset", "ultrafast", "-c:a", "aac", str(src)],
            check=True,
        )
        results = trim.split_video(src, self.dir / "clips", 14, "keep", manifest=True)
        self.assertEqual(len(results), 13)
        for r in results[:12]:
            self.assertAlmostEqual(trim.probe_duration(r.path), 14, delta=0.15)
        self.assertAlmostEqual(trim.probe_duration(results[-1].path), 12, delta=0.15)
        self.assertEqual(results[-1].path.name, "my source_13.mp4")
        lines = (self.dir / "clips" / "my source_manifest.csv").read_text().splitlines()
        self.assertEqual(lines[0], "index,filename,start_sec,end_sec,duration_sec")
        self.assertEqual(lines[-1], "13,my source_13.mp4,168.00,180.00,12.00")

    def test_corrupt_file_raises(self):
        bad = self.dir / "bad.mp4"
        bad.write_bytes(b"not a video")
        with self.assertRaises(trim.TrimError):
            trim.split_video(bad, self.dir / "clips")


if __name__ == "__main__":
    unittest.main()
