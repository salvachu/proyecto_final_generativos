import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import h5py
import numpy as np

from sdlpop_recorder import Game, Recorder, SequenceDataset, validate
from sdlpop_recorder.engine import DEFAULT_ENGINE, action_mask

ENGINE = Path(os.getenv("SDLPOP_ENGINE", DEFAULT_ENGINE)).resolve()


class Actions(unittest.TestCase):
    def test_combinations(self):
        self.assertEqual(action_mask(["right", "up", "shift"]), 22)
        self.assertEqual(action_mask({"left": 0, "right": 1}), 2)
        self.assertEqual(action_mask(["right", "left", "down", "up"]), 5)
        self.assertEqual(action_mask(()), 0)
        with self.assertRaises(ValueError):
            action_mask(["pause"])
        with self.assertRaises(ValueError):
            action_mask({"up": 2})


@unittest.skipUnless((ENGINE / "prince").is_file(), "Se requiere el motor preparado")
class Capture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def record(self, n, level=2, seed=42):
        with Recorder(self.root, "test", engine=ENGINE, level=level, seed=seed, max_steps=n) as rec:
            for _ in range(n):
                rec.step(("right",))
                if rec.end_reason:
                    break
        return rec

    def test_next_image_and_boundaries(self):
        first = self.record(11)
        second = self.record(8)
        data = SequenceDataset(self.root, 8, include_state=True)
        self.assertEqual(len(data), (11 - 8 + 1) + 1)
        self.assertEqual({first.episode_id, second.episode_id}, set(data.episode_ids))
        with Game(ENGINE, 2, 42) as game:
            expected = [game.frame.rgb]
            for _ in range(11):
                expected.append(game.step(("right",)).rgb)
        for sample in data:
            i = sample["start"]
            self.assertEqual(sample["observations"]["rgb"].shape, (9, 200, 320, 3))
            np.testing.assert_array_equal(sample["observations"]["rgb"], expected[i:i + 9])
            np.testing.assert_array_equal(sample["actions"]["buttons"][:, 1], np.ones(8))
            n = 11 if sample["episode_id"] == first.episode_id else 8
            self.assertEqual(sample["transitions"]["truncated"][-1], i + 8 == n)
            self.assertFalse(sample["transitions"]["terminated"].any())
        self.assertNotIn("privileged", SequenceDataset(self.root)[0])
        self.assertEqual(validate(self.root)["steps"], 19)
        with self.assertRaises(RuntimeError):
            with first:
                pass
        self.assertEqual(validate(self.root)["invalid"], 0)

    def test_pause_and_effect_of_input(self):
        def trace(delay, buttons):
            with Game(ENGINE, 1, 173) as game:
                for i in range(60):
                    if i == 20:
                        time.sleep(delay)
                    frame = game.step(buttons)
                return frame
        idle = trace(0, ())
        run = trace(0, ("right",))
        paused = trace(0.18, ("right",))
        self.assertNotEqual(idle.state[2], run.state[2])
        self.assertFalse(np.array_equal(idle.rgb, run.rgb))
        self.assertEqual(run.state, paused.state)
        np.testing.assert_array_equal(run.rgb, paused.rgb)

    def test_death(self):
        rec = self.record(50, level=7)
        self.assertEqual(rec.end_reason, "death")
        self.assertGreater(rec.steps, 0)
        self.assertLess(rec.steps, 50)
        sample = SequenceDataset(self.root, 1, include_state=True)[-1]
        self.assertEqual(sample["privileged"]["hp"][-1], 0)
        self.assertTrue(sample["transitions"]["terminated"][-1])
        self.assertFalse(sample["transitions"]["truncated"][-1])
        self.assertEqual(validate(self.root)["invalid"], 0)

    def test_combat_period(self):
        with Recorder(self.root, "combat", engine=ENGINE, level=2, seed=42) as rec:
            for i in range(65):
                buttons = ("left",) if i < 32 else (("shift",) if i % 12 < 4 else ())
                rec.step(buttons)
                if rec.end_reason:
                    break
        sample = SequenceDataset(self.root, rec.steps, include_state=True)[0]
        sword_drawn = sample["privileged"]["sword"][:-1] == 2
        self.assertTrue(sword_drawn.any())
        self.assertTrue((~sword_drawn).any())
        np.testing.assert_array_equal(sample["transitions"]["dt_ticks"], np.where(sword_drawn, 6, 5))

    def test_native_end_conditions(self):
        # Shorten the route to each native ending in a private copy of the settings.
        private = self.root / "engine"
        private.mkdir()
        shutil.copy2(ENGINE / "prince", private / "prince")
        (private / "data").symlink_to(ENGINE / "data", target_is_directory=True)
        original = (ENGINE / "SDLPoP.ini").read_text()
        for reason, settings in (
            ("time_expired", original.replace("start_minutes_left = 60", "start_minutes_left = 1")
                             .replace("start_ticks_left = 719", "start_ticks_left = 4")),
            ("level_complete", original.replace("[Level 2]\n", "[Level 2]\nseamless_exit = 4\n")),
            ("victory", original.replace("win_level = 14", "win_level = 2").replace("win_room = 5", "win_room = 4")),
        ):
            with self.subTest(reason=reason):
                (private / "SDLPoP.ini").write_text(settings)
                with Game(private, 2, 42) as game:
                    for _ in range(60):
                        frame = game.step(("left",))
                        if frame.end != "playing":
                            break
                self.assertEqual(frame.end, reason)

    def test_incomplete_and_corrupt_file(self):
        with Recorder(self.root, "test", engine=ENGINE, seed=1):
            pass
        self.assertEqual(list(self.root.glob("episodes/*")), [])
        rec = self.record(10)
        with h5py.File(rec.path, "r+") as f:
            f["states/rgb"].resize(10, axis=0)
        self.assertGreater(validate(self.root)["invalid"], 0)
        rec.path.rename(rec.path.with_suffix(".h5.partial"))
        self.assertEqual(validate(self.root)["valid"], 0)
        self.assertGreater(validate(self.root)["invalid"], 0)
        self.assertEqual(json.loads(rec.manifest.read_text())["steps"], 10)


if __name__ == "__main__":
    unittest.main()
