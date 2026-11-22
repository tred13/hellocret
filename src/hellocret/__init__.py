"""Procedural vertical-video prototype for Google Colab."""

from .pipeline import (
    CAPTION_Y_RATIO, FPS, HEIGHT, WIDTH, caption_at, caption_schedule, caption_schedule_segments,
    draw_caption, make_beats, render_frame, render_video, split_beats,
    validate_script,
)

__all__ = [
    "CAPTION_Y_RATIO", "FPS", "HEIGHT", "WIDTH", "caption_at",
    "caption_schedule", "caption_schedule_segments", "draw_caption", "make_beats", "render_frame",
    "render_video", "split_beats", "validate_script",
]
