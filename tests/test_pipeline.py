import unittest
from hellocret.pipeline import (
    CAPTION_Y_RATIO, HEIGHT, WIDTH, caption_at, caption_schedule,
    caption_schedule_segments, draw_caption, make_beats, render_frame, split_beats, validate_script,
)

class PipelineTests(unittest.TestCase):
    def test_normalizes_script(self):
        self.assertEqual(validate_script("  A short   English story.  "), "A short English story.")

    def test_rejects_empty_and_non_ascii_input(self):
        with self.assertRaises(ValueError): validate_script("  ")
        with self.assertRaises(ValueError): validate_script("Hola mundo y acción")

    def test_splits_sentence_beats(self):
        self.assertEqual(len(split_beats("He waits. The army arrives! Then he runs?")), 3)

    def test_captions_cover_audio_without_gaps(self):
        captions=caption_schedule("He waits. The army arrives!",4.25)
        self.assertGreater(len(captions),3)
        self.assertAlmostEqual(captions[0].start,0.0)
        self.assertAlmostEqual(captions[-1].end,4.25)
        for left,right in zip(captions,captions[1:]): self.assertAlmostEqual(left.end,right.start)
        self.assertEqual(caption_at(captions,0.0),"He")

    def test_sentence_chunk_timings_include_only_inserted_pauses(self):
        captions,duration=caption_schedule_segments("The night falls. A spark appears.",[1.4,1.8],0.12)
        self.assertAlmostEqual(duration,3.32)
        self.assertAlmostEqual(captions[0].start,0.0)
        self.assertAlmostEqual(captions[-1].end,3.32)
        beats=make_beats("The night falls. A spark appears.",duration,[1.4,1.8],0.12)
        self.assertAlmostEqual(beats[1].start,1.52)

    def test_beats_cover_full_duration(self):
        beats=make_beats("The night falls. A spark appears.",5.0)
        self.assertEqual(len(beats),2)
        self.assertAlmostEqual(beats[0].start,0.0)
        self.assertAlmostEqual(beats[-1].end,5.0)

    def test_renderer_returns_vertical_rgb_frame(self):
        frame=render_frame("A cart waits by the castle.",0.2,2.0)
        self.assertEqual(frame.size,(360,640)); self.assertEqual(frame.mode,"RGB")
        self.assertEqual(draw_caption(frame,"castle").size,frame.size)
        self.assertEqual(CAPTION_Y_RATIO,0.704)
        self.assertEqual((WIDTH,HEIGHT),(720,1280))

if __name__=="__main__": unittest.main()
