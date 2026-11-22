"""Procedural cartoon renderer for narrated vertical video prototypes.

The imagery is drawn locally; it does not call an image/video generation API.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT, FPS = 720, 1280, 30
CAPTION_Y_RATIO = 0.704
MAX_SCRIPT_CHARS = 6000
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")
_BEAT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class Caption:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Beat:
    text: str
    start: float
    end: float
    kind: str


def validate_script(script: str) -> str:
    """Validate the single English-script input and normalize whitespace."""
    if not isinstance(script, str):
        raise ValueError("Enter the script as text.")
    text = " ".join(script.strip().split())
    if not text:
        raise ValueError("Paste an English script to begin.")
    if len(text) > MAX_SCRIPT_CHARS:
        raise ValueError(f"The script must be at most {MAX_SCRIPT_CHARS} characters.")
    if not re.fullmatch(r"[A-Za-z0-9 .,!?;:'\"()\-]+", text):
        raise ValueError("Use English text and standard punctuation only.")
    if len(_WORD_RE.findall(text)) < 3:
        raise ValueError("The script needs at least three words.")
    return text


def split_beats(script: str) -> list[str]:
    """Split the script into sentence-sized visual and narration beats."""
    text = validate_script(script)
    beats = [part.strip() for part in _BEAT_RE.split(text) if part.strip()]
    return beats or [text]


def _word_weight(word: str) -> float:
    letters = sum(ch.isalpha() for ch in word)
    weight = max(1.0, math.sqrt(letters))
    if word.endswith((",", ";", ":")):
        weight += 0.6
    if word.endswith(('.', '!', '?')):
        weight += 1.1
    return weight


def caption_schedule(script: str, duration: float) -> list[Caption]:
    """Estimate one-word captions across the narration duration.

    This is proportional timing, not forced word alignment.
    """
    text = validate_script(script)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Audio duration must be positive.")
    words = re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*[.,!?;:]?", text)
    weights = [_word_weight(word) for word in words]
    total = sum(weights)
    cursor = 0.0
    captions: list[Caption] = []
    for word, weight in zip(words, weights):
        end = cursor + duration * weight / total
        captions.append(Caption(word, cursor, end))
        cursor = end
    last = captions[-1]
    captions[-1] = Caption(last.text, last.start, duration)
    return captions


def caption_schedule_segments(script: str, segment_durations: list[float], pause_seconds: float = 0.12) -> tuple[list[Caption], float]:
    """Caption sentence-level TTS chunks without timing drift between sentences."""
    sentences=split_beats(script)
    if len(sentences)!=len(segment_durations):
        raise ValueError("Provide one audio duration per sentence.")
    if pause_seconds<0 or any(not math.isfinite(d) or d<=0 for d in segment_durations):
        raise ValueError("Sentence durations must be positive and pauses non-negative.")
    result=[]; cursor=0.0
    for i,(sentence,seconds) in enumerate(zip(sentences,segment_durations)):
        for item in caption_schedule(sentence,seconds):
            result.append(Caption(item.text,item.start+cursor,item.end+cursor))
        cursor += seconds
        if i<len(sentences)-1:
            cursor += pause_seconds
    return result,cursor


def _classify(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("explode", "explosion", "blast", "fireball")):
        return "blast"
    if any(w in t for w in ("launch", "rocket", "arrow", "fly", "shoot")):
        return "launch"
    if any(w in t for w in ("spark", "flame", "fire", "light", "burn")):
        return "fire"
    if any(w in t for w in ("rain", "night", "storm", "dark")):
        return "night"
    if any(w in t for w in ("army", "soldier", "fort", "castle", "siege", "wall")):
        return "siege"
    if any(w in t for w in ("cart", "wood", "hole", "string", "rope", "drill")):
        return "workshop"
    return "day"


def make_beats(script: str, duration: float, segment_durations: list[float] | None = None, pause_seconds: float = 0.0) -> list[Beat]:
    sentences=split_beats(script)
    if segment_durations is not None:
        if len(sentences)!=len(segment_durations):
            raise ValueError("Provide one audio duration per sentence.")
        result=[]; cursor=0.0
        for i,(sentence,seconds) in enumerate(zip(sentences,segment_durations)):
            if seconds<=0: raise ValueError("Sentence durations must be positive.")
            end=cursor+seconds
            result.append(Beat(sentence,cursor,end,_classify(sentence)))
            cursor=end+(pause_seconds if i<len(sentences)-1 else 0.0)
        if cursor>duration+0.02: raise ValueError("Sentence timings exceed the audio duration.")
        return result
    weights=[max(1,len(_WORD_RE.findall(sentence))) for sentence in sentences]
    total=sum(weights); cursor=0.0; result=[]
    for sentence,weight in zip(sentences,weights):
        end=cursor+duration*weight/total
        result.append(Beat(sentence,cursor,end,_classify(sentence))); cursor=end
    last=result[-1]; result[-1]=Beat(last.text,last.start,duration,last.kind)
    return result


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _gradient(draw: ImageDraw.ImageDraw, w: int, h: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    for y in range(h):
        p = y / max(1, h - 1)
        color = tuple(int(top[i] * (1 - p) + bottom[i] * p) for i in range(3))
        draw.line((0, y, w, y), fill=color)


def _palette(kind: str) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    return {
        "night": ((28,31,57),(67,74,103),(64,74,86)),
        "fire": ((77,111,190),(235,190,110),(71,72,58)),
        "launch": ((62,119,205),(155,197,236),(72,104,67)),
        "blast": ((69,117,195),(232,183,104),(67,95,57)),
        "siege": ((71,132,215),(204,221,239),(75,120,63)),
        "workshop": ((74,128,207),(205,223,242),(76,118,61)),
        "day": ((67,126,211),(215,231,245),(75,132,65)),
    }.get(kind, ((67,126,211),(215,231,245),(75,132,65)))


def _draw_person(draw: ImageDraw.ImageDraw, x: int, ground: int, scale: float, time: float, color: tuple[int, int, int], helmet: bool = False) -> None:
    bob = int(3 * math.sin(time * 5 + x * 0.03))
    r = int(24 * scale)
    hy = ground - int(100 * scale) + bob
    top = hy + r - 2
    bottom = ground - int(26 * scale)
    ink = (22, 23, 24)
    width = max(2, int(3 * scale))
    draw.ellipse((x-r,hy-r,x+r,hy+r),fill=(248,246,239),outline=ink,width=width)
    draw.line((x-int(13*scale),hy-4,x-int(4*scale),hy-5),fill=ink,width=width)
    draw.line((x+int(4*scale),hy-5,x+int(13*scale),hy-4),fill=ink,width=width)
    draw.ellipse((x-int(9*scale),hy+int(2*scale),x-int(5*scale),hy+int(8*scale)),fill=ink)
    draw.ellipse((x+int(5*scale),hy+int(2*scale),x+int(9*scale),hy+int(8*scale)),fill=ink)
    draw.arc((x-int(10*scale),hy+int(7*scale),x+int(10*scale),hy+int(18*scale)),5,170,fill=ink,width=max(2,int(2*scale)))
    if helmet:
        draw.pieslice((x-r-2,hy-r-5,x+r+2,hy+3),180,360,fill=(177,184,193),outline=ink,width=width)
        draw.rectangle((x-r-2,hy-2,x+r+2,hy+4),fill=(160,168,178),outline=ink,width=max(1,int(2*scale)))
    draw.rounded_rectangle((x-int(21*scale),top,x+int(21*scale),bottom),radius=max(1,int(7*scale)),fill=color,outline=ink,width=width)
    hip = ground - int(26*scale)
    draw.line((x-int(8*scale),hip,x-int(15*scale),ground),fill=ink,width=width)
    draw.line((x+int(8*scale),hip,x+int(15*scale),ground),fill=ink,width=width)
    swing = int(7*math.sin(time*4+x))
    draw.line((x-int(18*scale),top+int(15*scale),x-int(31*scale)-swing,top+int(38*scale)),fill=ink,width=width)
    draw.line((x+int(18*scale),top+int(15*scale),x+int(31*scale)+swing,top+int(38*scale)),fill=ink,width=width)


def render_frame(script: str, t: float, duration: float, width: int = 360, height: int = 640) -> Image.Image:
    """Render a single stylized vertical frame using local Pillow drawings."""
    text = validate_script(script)
    if width < 180 or height < 320 or t < 0 or duration <= 0:
        raise ValueError("Invalid frame dimensions or time.")
    beats = make_beats(text, duration)
    beat = next((b for b in beats if b.start <= t < b.end), beats[-1])
    kind = beat.kind
    sky_top, sky_bottom, ground = _palette(kind)
    im = Image.new("RGB", (width,height))
    d = ImageDraw.Draw(im)
    _gradient(d,width,height,sky_top,sky_bottom)
    if kind not in ("night","blast"):
        d.ellipse((width*.72,height*.10,width*.86,height*.17),fill=(255,232,166))
    d.polygon([(0,height*.46),(width*.18,height*.31),(width*.38,height*.44),(width*.56,height*.29),(width*.78,height*.43),(width,height*.32),(width,height*.65),(0,height*.65)],fill=(75,112,105))
    d.polygon([(0,height*.52),(width*.23,height*.40),(width*.42,height*.52),(width*.68,height*.38),(width,height*.53),(width,height*.70),(0,height*.70)],fill=(77,139,73))
    d.rectangle((0,int(height*.62),width,height),fill=ground)
    for x in range(-width,width*2,max(24,width//8)):
        y=int(height*.64+((x*13)%max(15,int(height*.05))))
        d.line((x,y,x+width//3,height),fill=(105,139,72),width=max(1,width//240))
    if kind in ("siege","workshop","day","night","fire","launch","blast"):
        base=int(height*.56)
        d.rectangle((width*.05,base-height*.18,width*.43,base),fill=(133,128,112),outline=(40,41,39),width=max(2,width//120))
        for xa in (.10,.31):
            d.rectangle((width*xa,base-height*.23,width*(xa+.07),base-height*.18),fill=(151,146,129),outline=(40,41,39),width=max(1,width//180))
        for wx in (.13,.24,.34):
            d.rectangle((width*wx,base-height*.13,width*(wx+.035),base-height*.075),fill=(52,59,61))
    if kind in ("workshop","fire","launch","blast") or any(k in text.lower() for k in ("cart","wood","hole","rope","string")):
        y=int(height*.73); x0=int(width*.43); x1=int(width*.91)
        d.line((x0,y+height*.09,x1,y+height*.09),fill=(39,35,29),width=max(3,width//70))
        for wx in (x0+width*.11,x1-width*.10):
            d.ellipse((wx-width*.07,y+height*.06,wx+width*.07,y+height*.20),fill=(65,54,38),outline=(25,24,22),width=max(2,width//120))
        d.rectangle((x0,y-height*.16,x1,y),fill=(176,130,68),outline=(40,32,24),width=max(2,width//100))
        for i in range(7):
            px=x0+int((i+1)*(x1-x0)/8)
            d.ellipse((px-width*.012,y-height*.12,px+width*.012,y-height*.08),fill=(53,43,33))
    if kind in ("siege","launch","blast"):
        for i in range(7):
            x=int(width*(.10+i*.105))
            _draw_person(d,x,int(height*.73),.52,t,(181,139,49),helmet=True)
    hero_x=int(width*(.48+.025*math.sin(t*1.7)))
    hero_color=(154,62,55) if kind in ("workshop","night","fire") else (88,99,112)
    _draw_person(d,hero_x,int(height*.88),1.20,t,hero_color,helmet=kind in ("siege","launch","blast"))
    local_t=t-beat.start
    if kind in ("fire","launch","blast"):
        for i in range(12):
            phase=(local_t*1.4+i*.137)%1.0
            x=int(width*(.22+((i*37)%57)/100)); y=int(height*(.72-phase*.45))
            if kind=="fire":
                d.ellipse((x-3,y-3,x+3,y+3),fill=(255,226,137))
            else:
                d.line((x,y+height*.08,x+int(width*.035),y),fill=(255,232,175),width=max(1,width//180))
    if kind=="blast" and local_t<min(1.25,beat.end-beat.start):
        radius=int(width*(.08+.22*min(1,local_t/.75))); cx=int(width*.67); cy=int(height*.50)
        d.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),fill=(244,172,78),outline=(255,226,160),width=max(2,width//90))
        d.ellipse((cx-radius*.55,cy-radius*.55,cx+radius*.55,cy+radius*.55),fill=(255,231,173))
    return im


def caption_at(captions: Iterable[Caption], t: float) -> str:
    for caption in captions:
        if caption.start <= t < caption.end:
            return caption.text
    return ""


def draw_caption(image: Image.Image, text: str) -> Image.Image:
    """Burn one high-contrast word into the lower-center caption band."""
    if not text:
        return image
    im=image.copy(); d=ImageDraw.Draw(im)
    font=_font(max(24,im.width//18),True)
    label=text.strip(); max_w=int(im.width*.90)
    while d.textbbox((0,0),label,font=font,stroke_width=3)[2]>max_w and getattr(font,"size",28)>18:
        font=_font(getattr(font,"size",28)-2,True)
    box=d.textbbox((0,0),label,font=font,stroke_width=3)
    x=(im.width-(box[2]-box[0]))//2-box[0]
    y=int(im.height*CAPTION_Y_RATIO)-(box[3]-box[1])//2-box[1]
    d.text((x,y),label,font=font,fill=(255,255,255),stroke_width=max(2,im.width//120),stroke_fill=(8,8,8))
    return im


def _probe_duration(path: str | Path) -> float:
    ffprobe=shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("FFprobe is required in the Colab runtime.")
    out=subprocess.check_output([ffprobe,"-v","error","-show_entries","format=duration","-of","json",str(path)],text=True)
    duration=float(json.loads(out)["format"]["duration"])
    if duration<=0:
        raise ValueError("Generated narration has no audio duration.")
    return duration


def render_video(script: str, audio_path: str | Path, output_path: str | Path, progress=None, captions: list[Caption] | None = None, segment_durations: list[float] | None = None, pause_seconds: float = 0.0) -> dict:
    """Render frames locally, then mux the narration into a 720x1280 MP4."""
    text=validate_script(script)
    audio_path=Path(audio_path); output_path=Path(output_path)
    if not audio_path.exists():
        raise FileNotFoundError(audio_path)
    ffmpeg=shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required in the Colab runtime.")
    duration=_probe_duration(audio_path)
    captions=list(captions) if captions is not None else caption_schedule(text,duration)
    beats=make_beats(text,duration,segment_durations=segment_durations,pause_seconds=pause_seconds)
    total_frames=max(1,int(math.ceil(duration*FPS)))
    encoders=subprocess.run([ffmpeg,"-hide_banner","-encoders"],capture_output=True,text=True).stdout
    gpu_check=subprocess.run(["nvidia-smi","-L"],capture_output=True,text=True) if shutil.which("nvidia-smi") else None
    has_cuda=gpu_check is not None and gpu_check.returncode==0 and "GPU" in gpu_check.stdout
    use_nvenc=has_cuda and "h264_nvenc" in encoders
    output_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        silent=Path(td)/"picture.mp4"
        encoder="h264_nvenc" if use_nvenc else "libx264"
        args=[ffmpeg,"-y","-v","error","-f","rawvideo","-pix_fmt","rgb24","-s","360x640","-r",str(FPS),"-i","pipe:0","-vf","scale=720:1280:flags=lanczos","-an","-c:v",encoder]
        if encoder=="libx264": args += ["-preset","veryfast","-crf","21"]
        else: args += ["-preset","p4","-cq","23"]
        args += ["-pix_fmt","yuv420p","-movflags","+faststart",str(silent)]
        proc=subprocess.Popen(args,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            for i in range(total_frames):
                t=min(i/FPS,max(0,duration-1/FPS))
                frame=render_frame(text,t,duration,360,640)
                frame=draw_caption(frame,caption_at(captions,t))
                assert proc.stdin is not None
                proc.stdin.write(frame.tobytes())
                if progress and (i%max(1,FPS*5)==0 or i==total_frames-1):
                    progress(i+1,total_frames)
            if proc.stdin: proc.stdin.close()
            stderr=proc.stderr.read() if proc.stderr else b""
            code=proc.wait()
            if code!=0:
                raise RuntimeError(stderr.decode("utf-8","replace")[-2000:])
        except Exception:
            proc.kill()
            raise
        mux=[ffmpeg,"-y","-v","error","-i",str(silent),"-i",str(audio_path),"-c:v","copy","-c:a","aac","-b:a","192k","-shortest","-movflags","+faststart",str(output_path)]
        subprocess.run(mux,check=True,capture_output=True)
    return {"output":str(output_path),"width":WIDTH,"height":HEIGHT,"fps":FPS,"duration_seconds":duration,"frames":total_frames,"caption_count":len(captions),"beat_count":len(beats),"video_encoder":"h264_nvenc" if use_nvenc else "libx264"}
