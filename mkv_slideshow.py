"""
MKV slideshow maker

Turns a disc photo-gallery rip (an mkv whose images all flash past in quick succession)
into a normal video where each image is held for a set time, with one
chapter per image. Needs ffmpeg and ffprobe. Input files are never changed.

How to run: set the values under USER SETTINGS, save, then double-click this
file or run "python mkv_slideshow.py".

History
- 2026-10-03: First version.
- 2026-10-03: Cover attachment is always named cover.jpg (cover.png for a PNG
  cover) instead of the temporary file path.
- 2026-10-03: The input track's stored statistics (frame count, bit rate,
  size) are no longer copied to the output, where they were wrong.
- 2026-10-03: Image detection: frames are grouped into images either by how
  much of the picture differs (SAME_IMAGE_PERCENT) or by a fixed count
  (KEEP_EVERY_N_FRAMES). These replace DROP_DUPLICATE_FRAMES.
  Added LOSSLESS (HEVC). Default quality 16 changed to 4. H.264 output is
  limited to level 4.1. Keyframes only at the start of each image. Chapter
  numbers padded to the width the file needs. Files that are not 8-bit 4:2:0
  are skipped.
- 2026-10-03: Folder mode leaves out any file with the output suffix anywhere
  in its name, and says how many. Reworded the image-detection report.
  Split the command runner in two so code checkers see the right types.
- 2026-10-03: Lossless (HEVC) output is labelled level 4.1 (up to about
  1920x1080) or 5.1 (up to about 4K) instead of the encoder's level 8.5.
- 2026-10-03: Lossless (HEVC) output uses closed keyframes only.
- 2026-10-03: Fixed wrong pictures when the input's frames are spaced apart
  in time (frame numbers were miscounted during detection). Terminal now
  shows the picture size, the level to apply, and the codec, profile and
  level read back from the output. Level rules made consistent between
  H.264 and HEVC and now take the frame rate into account.
- 2026-10-04: The output's title is the input file name without extension,
  instead of the input's own title.
- 2026-10-10: Solid color (blank) frames are dropped (SOLID_COLOR_PERCENT),
  with a report of which frames and how close the calls were.
- 2026-11-08: 10-bit 4:2:0 sources (for example 4K discs) are converted
  and kept 10-bit, as HEVC: lossless, or with LOSSLESS = False, lossy at
  QUALITY_CRF_10BIT. The source's color labels are copied to the output.
  HDR (PQ, HLG) and Dolby Vision sources are skipped with a message.
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from fractions import Fraction
from pathlib import Path

# ============================ USER SETTINGS ============================

# ---- How to identify individual images (two methods, pick one) ----
# Fixed Frame Count Method: KEEP_EVERY_N_FRAMES > 0: keep every Nth frame and drop the rest.
# Automatic Method: KEEP_EVERY_N_FRAMES = 0. When enabled,
# SAME_IMAGE_PERCENT = frame counts as repeat of image before it when % difference is less
# than this value. 0 = drop only exact copies.
KEEP_EVERY_N_FRAMES = 0
SAME_IMAGE_PERCENT = 5

# ---- Solid color (blank) frames ----
# A frame is dropped as blank when at least this % of the picture is one color.
# 100 = only completely solid frames. 0 = off, keep them.
# Fixed Frame Count Method: the Nth frames are picked first, then blank ones are dropped.
SOLID_COLOR_PERCENT = 95

# True = exact copy of the pictures, forces HEVC/H.265 encoding.
LOSSLESS = True

# Input Files, using full paths. Empty = every .mkv in script parent folder.
INPUT_FILES = [
    # r"H:\Some Folder\00010_Photography.mkv",
]

# Output files. Empty = script parent folder.
OUTPUT_FOLDER = r""

# How long each image stays on screen.
SECONDS_PER_IMAGE = 10

# Carry the cover image over as a file attachment.
KEEP_COVER_IMAGE = True

# ---- Advanced ----
FFMPEG_FOLDER = r""              # Path to ffmpeg.exe & ffprobe.exe. Leave empty if on PATH.
OUTPUT_FPS = "24000/1001"        # 23.976 frames per second
QUALITY_CRF = 4                  # H.264 only: lower = higher quality, larger file
QUALITY_CRF_10BIT = 12           # 10-bit sources, LOSSLESS = False: same scale, HEVC
ENCODER_PRESET = "slow"          # encoder speed preset
OUTPUT_SUFFIX = "_slideshow"     # added to the input name
CHAPTER_NAME = "Chapter {}"      # {} becomes 01, 02, ... (001 if 100 or more)

# Folder mode only: files longer than this are taken to be normal videos and
# skipped. Files listed in INPUT_FILES are not checked against it.
MAX_INPUT_SECONDS = 60

# Any file with more frames than this is skipped.
MAX_FRAMES = 2000

# ========================= END OF USER SETTINGS =========================

SCRIPT_FOLDER = Path(__file__).resolve().parent

# Size of the small copy of each frame used for comparing pictures.
THUMB_W, THUMB_H = 128, 72
# A point of the picture counts as different when its brightness (or, for the
# solid color check, its color) differs by more than this (out of 255). Keeps
# compression noise from counting.
BRIGHTNESS_TOLERANCE = 8


class Skip(Exception):
    """Raised with a plain-language reason when a file cannot be processed."""


def find_tool(name):
    """Return the full path of ffmpeg or ffprobe, or None."""
    exe = name + (".exe" if os.name == "nt" else "")
    folders = [Path(FFMPEG_FOLDER)] if FFMPEG_FOLDER else [SCRIPT_FOLDER]
    for folder in folders:
        if (folder / exe).is_file():
            return str(folder / exe)
    return None if FFMPEG_FOLDER else shutil.which(name)


def run_bytes(cmd) -> bytes:
    """Run a command quietly and return its raw output. Raise Skip on failure."""
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise Skip("{} failed: {}".format(Path(cmd[0]).stem, message[-500:]))
    return result.stdout


def run(cmd) -> str:
    """Run a command quietly and return what it printed, as text."""
    return run_bytes(cmd).decode("utf-8", errors="replace")


def probe(ffprobe, path):
    """Return the file's duration, main video track and cover track."""
    data = json.loads(run([ffprobe, "-v", "error", "-of", "json",
                           "-show_format", "-show_streams", str(path)]))
    video = cover = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        # ffmpeg reports an attached cover image as a video track flagged
        # "attached_pic". It must not be treated as the slideshow video.
        if stream.get("disposition", {}).get("attached_pic"):
            cover = cover or stream
        else:
            video = video or stream
    duration = float(data.get("format", {}).get("duration") or 0)
    return duration, video, cover


# Both frame readers below use "-fps_mode passthrough". Without it, ffmpeg
# fills gaps between frame timestamps with repeated frames, and the frame
# numbers found here would not match the real file.

def frame_fingerprints(ffmpeg, path, video_index):
    """Return one fingerprint (MD5 of the decoded picture) per frame."""
    out = run([ffmpeg, "-v", "error", "-i", str(path),
               "-map", "0:{}".format(video_index),
               "-fps_mode", "passthrough",
               "-frames:v", str(MAX_FRAMES + 1), "-f", "framemd5", "-"])
    return [line.rsplit(",", 1)[1].strip()
            for line in out.splitlines()
            if line.strip() and not line.startswith("#")]


def frame_thumbnails(ffmpeg, path, video_index, color=False):
    """Return a small copy of each frame, as bytes.

    Normally a grey copy (brightness only). With color=True, the two color
    parts of each frame instead, one after the other.
    """
    points = THUMB_W * THUMB_H
    # yuv444p holds brightness, then the two color parts. Its brightness part
    # is on a different scale from the grey copy, so it is not used.
    size = points * 3 if color else points
    out = run_bytes([ffmpeg, "-v", "error", "-i", str(path),
                     "-map", "0:{}".format(video_index),
                     "-fps_mode", "passthrough",
                     "-frames:v", str(MAX_FRAMES + 1),
                     "-vf", "scale={}:{}:flags=area,format={}".format(
                         THUMB_W, THUMB_H, "yuv444p" if color else "gray"),
                     "-f", "rawvideo", "-"])
    skip = points if color else 0
    return [out[i + skip:i + size] for i in range(0, len(out) - size + 1, size)]


def percent_different(a, b):
    """Return the percentage of the picture that differs between two thumbnails."""
    t = BRIGHTNESS_TOLERANCE
    changed = sum(1 for x, y in zip(a, b) if x - y > t or y - x > t)
    return 100.0 * changed / len(a)


def percent_one_color(grey, color):
    """Return the percentage of the picture that is its most common color.

    A point counts when its brightness and both color parts are all close to
    the most common value of each.
    """
    points = len(grey)
    t = BRIGHTNESS_TOLERANCE
    matches = -1   # as a whole number, every bit set
    for part in (grey, color[:points], color[points:]):
        common = Counter(part).most_common(1)[0][0]
        # Turn each point into 1 (close to the common value) or 0, then keep
        # only the points that are 1 in all three parts. Done on whole
        # frames at once because point-by-point is slow on long files.
        table = bytes(1 if -t <= value - common <= t else 0 for value in range(256))
        matches &= int.from_bytes(part.translate(table), "big")
    return 100.0 * bin(matches).count("1") / points


def find_solid_frames(thumbs, colors, frames):
    """Find the solid color frames among the given frame numbers.

    Return (set of solid frame numbers, report lines for the terminal).
    """
    solid = set()
    closest_solid = closest_kept = None   # (percent, frame number)
    for i in frames:
        same = percent_one_color(thumbs[i], colors[i])
        if same >= SOLID_COLOR_PERCENT:
            solid.add(i)
            if closest_solid is None or same < closest_solid[0]:
                closest_solid = (same, i + 1)
        elif closest_kept is None or same > closest_kept[0]:
            closest_kept = (same, i + 1)
    # The closest call on each side of the limit, as for repeats below.
    report = ["  A frame is solid when at least {}% of the picture is one "
              "color.".format(SOLID_COLOR_PERCENT)]
    if solid:
        numbers = [str(i + 1) for i in sorted(solid)]
        if len(numbers) > 20:
            numbers = numbers[:20] + ["and {} more".format(len(numbers) - 20)]
        report.append("    Solid frames dropped: {}".format(", ".join(numbers)))
    if closest_solid:
        report.append("    Dropped solid frames were at least {:.2f}% one color "
                      "(frame {})".format(closest_solid[0], closest_solid[1]))
    if closest_kept:
        report.append("    Kept frames were at most {:.2f}% one color "
                      "(frame {})".format(closest_kept[0], closest_kept[1]))
    return solid, report


def choose_frames(ffmpeg, path, video_index):
    """Decide which frames are images. Return (frame count, kept frame numbers).

    Frame numbers start at 0 here; messages show them starting at 1.
    """
    check_solid = SOLID_COLOR_PERCENT > 0
    fixed_count = KEEP_EVERY_N_FRAMES >= 1
    automatic = not fixed_count and SAME_IMAGE_PERCENT > 0

    thumbs, prints, colors = [], [], []
    reads = []
    if automatic or check_solid:
        thumbs = frame_thumbnails(ffmpeg, path, video_index)
        reads.append(thumbs)
    if not automatic:
        prints = frame_fingerprints(ffmpeg, path, video_index)
        reads.append(prints)
    count = len(reads[0])
    if count > MAX_FRAMES:
        return count, []
    if check_solid:
        colors = frame_thumbnails(ffmpeg, path, video_index, color=True)
        reads.append(colors)
    # The separate reads must agree, or frame numbers would not line up.
    if any(len(read) != count for read in reads):
        raise Skip("the frames could not be counted consistently")

    # Fixed count: pick by position first. Otherwise every frame is a candidate.
    frames = list(range(0, count, KEEP_EVERY_N_FRAMES if fixed_count else 1))
    solid, solid_report, solid_note = set(), [], ""
    if check_solid:
        solid, solid_report = find_solid_frames(thumbs, colors, frames)
        solid_note = " {} solid color frame(s) dropped,".format(len(solid))
    # Solid frames go first, so an image repeated on both sides of a blank
    # frame is still seen as a repeat.
    frames = [i for i in frames if i not in solid]

    def show_solid_report():
        for line in solid_report:
            print(line)
        if solid and not frames:
            raise Skip("every frame checked is a solid color")

    if fixed_count:
        print("  {} frames, keeping 1 of every {},{} {} images".format(
            count, KEEP_EVERY_N_FRAMES, solid_note, len(frames)))
        show_solid_report()
        return count, frames

    if not automatic:
        kept = [i for n, i in enumerate(frames)
                if n == 0 or prints[i] != prints[frames[n - 1]]]
        print("  {} frames,{} {} exact repeat(s) dropped, {} images".format(
            count, solid_note, len(frames) - len(kept), len(kept)))
        show_solid_report()
        return count, kept

    kept = frames[:1]
    closest_same = closest_new = None   # (percent, frame number)
    for i in frames[1:]:
        # Compared with the last kept frame, so a run of repeats cannot drift.
        diff = percent_different(thumbs[kept[-1]], thumbs[i])
        if diff < SAME_IMAGE_PERCENT:
            if closest_same is None or diff > closest_same[0]:
                closest_same = (diff, i + 1)
        else:
            kept.append(i)
            if closest_new is None or diff < closest_new[0]:
                closest_new = (diff, i + 1)
    print("  {} frames,{} {} repeat(s) dropped, {} images".format(
        count, solid_note, len(frames) - len(kept), len(kept)))
    show_solid_report()
    # The closest call on each side of the limit, so a badly placed limit is
    # easy to spot: both numbers should be far from it.
    print("  A frame is a new image when {}% or more of the picture "
          "changes.".format(SAME_IMAGE_PERCENT))
    if closest_same:
        print("    Dropped repeats changed by at most {:.1f}% (frame {})".format(
            closest_same[0], closest_same[1]))
    if closest_new:
        print("    New images changed by at least {:.1f}% (frame {})".format(
            closest_new[0], closest_new[1]))
    return count, kept


def select_filter(kept, count):
    """Return the ffmpeg filter that keeps only the chosen frames, or None."""
    if len(kept) == count:
        return None

    def runs(numbers):
        # [3, 4, 5, 9] -> [(3, 5), (9, 9)]
        out = []
        for n in numbers:
            if out and n == out[-1][1] + 1:
                out[-1] = (out[-1][0], n)
            else:
                out.append((n, n))
        return out

    def expression(groups):
        return "+".join("eq(n\\,{})".format(a) if a == b
                        else "between(n\\,{}\\,{})".format(a, b)
                        for a, b in groups)

    keep_set = set(kept)
    keep_runs = runs(kept)
    drop_runs = runs([i for i in range(count) if i not in keep_set])
    # Whichever list is shorter, to keep the command line short.
    if len(drop_runs) <= len(keep_runs):
        return "select=not({})".format(expression(drop_runs))
    return "select={}".format(expression(keep_runs))


def extract_cover(ffmpeg, path, cover, folder):
    """Save the cover image to a temporary file. Return (file, mime type)."""
    is_png = cover.get("codec_name") == "png"
    target = Path(folder) / ("cover.png" if is_png else "cover.jpg")
    run([ffmpeg, "-v", "error", "-i", str(path),
         "-map", "0:{}".format(cover["index"]),
         "-c", "copy", "-frames:v", "1", "-f", "image2", str(target)])
    return target, ("image/png" if is_png else "image/jpeg")


def write_chapters(folder, image_count, frames_per_image, fps):
    """Write a chapter list (one chapter per image) for ffmpeg to read."""
    def start_ms(image_number):
        # Rounded up so a chapter never starts just before its image.
        return math.ceil(Fraction(image_number * frames_per_image) / fps * 1000)

    digits = max(2, len(str(image_count)))
    lines = [";FFMETADATA1"]
    for i in range(image_count):
        lines += ["[CHAPTER]", "TIMEBASE=1/1000",
                  "START={}".format(start_ms(i)),
                  "END={}".format(start_ms(i + 1)),
                  "title={}".format(CHAPTER_NAME.format(str(i + 1).zfill(digits)))]
    target = Path(folder) / "chapters.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def stale_statistics_args(video):
    """Return ffmpeg options that remove the input track's stored statistics.

    Rippers store the track's frame count, bit rate and size as tags. ffmpeg
    copies them to the new track, where they are wrong and make MediaInfo
    report a false frame rate and bit rate. Other tags (language, source
    medium, source ID) are left alone.
    """
    names = ("BPS", "DURATION", "NUMBER_OF_FRAMES", "NUMBER_OF_BYTES")
    args = []
    for key in video.get("tags", {}):
        upper = key.upper()
        if (upper.startswith("_STATISTICS_")
                or any(upper == n or upper.startswith(n + "-") for n in names)):
            # An empty value tells ffmpeg to delete the tag.
            args += ["-metadata:s:v:0", key + "="]
    return args


def encoding_plan(video):
    """Decide how a source is encoded. Return a dict describing it.

    8-bit sources: HEVC lossless, or H.264 with LOSSLESS = False.
    10-bit sources: always HEVC, kept 10-bit, lossless or lossy. H.264 is not
    used for 10-bit because few devices play 10-bit H.264.
    """
    ten_bit = video.get("pix_fmt") == "yuv420p10le"
    hevc = LOSSLESS or ten_bit
    name = "HEVC lossless" if LOSSLESS else ("HEVC" if hevc else "H.264")
    return {"hevc": hevc, "lossless": LOSSLESS, "ten_bit": ten_bit,
            "pix_fmt": "yuv420p10le" if ten_bit else "yuv420p",
            "encoder": "libx265" if hevc else "libx264",
            "name": name + (", 10-bit" if ten_bit else "")}


# Standard limits used for HEVC levels: largest picture (points) and points
# per second.
HEVC_LEVELS = (("4.1", 2228224, 133693440),
               ("5.1", 8912896, 534773760))


def choose_level(video, fps, plan):
    """Return (level or None, plain description) for the output video.

    A level is a label telling players how demanding the video is. The limits
    below are the standards' own limits on picture size and on picture size
    times frame rate.
    """
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    pixels = width * height
    if plan["hevc"]:
        for level, max_pixels, max_rate in HEVC_LEVELS:
            if 0 < pixels <= max_pixels and pixels * fps <= max_rate:
                # The encoder labels lossless streams "level 8.5"
                # (unrestricted), and lossy ones by their size alone. Some
                # players refuse an unusual label, so it is rewritten
                # afterwards to the usual level for the picture size. Only
                # the label changes; the video data stays the same. The
                # first frame of each image can be larger than the level
                # strictly allows, so the label is nominal.
                return level, level + " (label rewritten after encoding)"
        return None, ("encoder's own label kept (picture or frame rate beyond "
                      "level 5.1)")
    # H.264 limits are counted in 16x16 blocks. Level 4.1 is what most
    # hardware players accept; it covers 1920x1080 up to 30 frames a second.
    blocks = math.ceil(width / 16) * math.ceil(height / 16)
    if 0 < blocks <= 8704 and blocks * fps <= 245760:
        return "4.1", "4.1 (set in the H.264 encoder)"
    return None, "chosen by the encoder (picture or frame rate beyond level 4.1)"


def color_label_args(video):
    """Return ffmpeg options that copy the source's color labels.

    The labels tell players which colors and chroma position (where the color
    points sit relative to the picture points) the video uses. Without them,
    players guess, and colors can shift slightly.
    """
    labels = (("color_primaries", "-color_primaries"),
              ("color_transfer", "-color_trc"),
              ("color_space", "-colorspace"),
              ("color_range", "-color_range"),
              ("chroma_location", "-chroma_sample_location"))
    args = []
    for key, option in labels:
        value = video.get(key)
        if value and value not in ("unknown", "unspecified", "reserved"):
            args += [option, value]
    return args


def encoder_args(level, frames_per_image, plan):
    """Return the ffmpeg video encoder options."""
    # One keyframe per image, at its first frame, and none in between. An
    # extra keyframe mid-image would redraw the picture slightly differently.
    keyframes = ["-force_key_frames", "expr:eq(mod(n,{}),0)".format(frames_per_image)]
    if plan["hevc"]:
        # open-gop=0 makes every keyframe a closed one, so each image is
        # self-contained. -forced-idr alone did not achieve this in testing.
        params = ("keyint={0}:min-keyint={0}:scenecut=0:open-gop=0:"
                  "log-level=error").format(frames_per_image)
        if plan["lossless"]:
            params = "lossless=1:" + params
        else:
            # No data rate cap: in testing, a cap at the level's rate made the
            # first frame of each image soft, sharpening over the next second.
            params = "crf={}:".format(QUALITY_CRF_10BIT) + params
        args = ["-c:v", "libx265", "-preset", ENCODER_PRESET, "-pix_fmt", plan["pix_fmt"],
                "-x265-params", params, "-forced-idr", "1"]
        if level:
            args += ["-bsf:v", "hevc_metadata=level=" + level]
        return args + keyframes
    args = ["-c:v", "libx264", "-crf", str(QUALITY_CRF), "-preset", ENCODER_PRESET,
            "-pix_fmt", "yuv420p", "-g", str(frames_per_image)]
    if level:
        args += ["-level", level]
    return args + keyframes


def is_own_output(path):
    """True if the file name contains the output suffix, e.g. "_slideshow"."""
    return bool(OUTPUT_SUFFIX) and OUTPUT_SUFFIX.lower() in path.stem.lower()


def free_output_path(folder, stem):
    """Return an output name that does not exist yet (adds _2, _3, ...)."""
    candidate = folder / (stem + OUTPUT_SUFFIX + ".mkv")
    number = 2
    while candidate.exists():
        candidate = folder / "{}{}_{}.mkv".format(stem, OUTPUT_SUFFIX, number)
        number += 1
    return candidate


def level_text(codec, number):
    """Turn ffprobe's level number into the usual form, e.g. 123 -> "4.1"."""
    if not isinstance(number, int) or number <= 0:
        return "unknown"
    # ffprobe stores H.264 levels times 10 and HEVC levels times 30.
    text = "{:.1f}".format(number / (30 if codec == "hevc" else 10))
    return text[:-2] if text.endswith(".0") else text


def check_output(ffprobe, path, image_count, want_cover, want_level, want_title,
                 want_pix_fmt):
    """Re-read the new file. Return (problems, duration, video description)."""
    data = json.loads(run([ffprobe, "-v", "error", "-of", "json", "-show_format",
                           "-show_streams", "-show_chapters", str(path)]))
    streams = data.get("streams", [])
    real_video = [s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")]
    covers = [s for s in streams if s.get("disposition", {}).get("attached_pic")]
    problems = []
    if len(real_video) != 1:
        problems.append("{} video tracks (expected 1)".format(len(real_video)))
    if len(data.get("chapters", [])) != image_count:
        problems.append("{} chapters (expected {})".format(
            len(data.get("chapters", [])), image_count))
    if want_cover and len(covers) != 1:
        problems.append("cover image not attached")
    tags = data.get("format", {}).get("tags", {})
    title = next((v for k, v in tags.items() if k.lower() == "title"), None)
    if title != want_title:
        problems.append("title is {!r} (expected {!r})".format(title, want_title))
    described = "no video track"
    if real_video:
        codec = real_video[0].get("codec_name", "")
        level = level_text(codec, real_video[0].get("level"))
        described = "{}, {} profile, level {}".format(
            {"hevc": "HEVC", "h264": "H.264"}.get(codec, codec),
            real_video[0].get("profile", "unknown"), level)
        if want_level and level != want_level:
            problems.append("level {} (expected {})".format(level, want_level))
        if real_video[0].get("pix_fmt") != want_pix_fmt:
            problems.append("picture format {} (expected {})".format(
                real_video[0].get("pix_fmt"), want_pix_fmt))
    return problems, float(data.get("format", {}).get("duration") or 0), described


def process(ffmpeg, ffprobe, path, out_folder, folder_mode, encoders):
    duration, video, cover = probe(ffprobe, path)
    if video is None:
        raise Skip("no video track found")
    if folder_mode and duration > MAX_INPUT_SECONDS:
        raise Skip("{:.0f} s long, looks like a normal video".format(duration))
    pix_fmt = video.get("pix_fmt")
    formats = {"yuv420p": "8-bit 4:2:0", "yuv420p10le": "10-bit 4:2:0"}
    print("  Picture: {}x{}, {}".format(
        video.get("width"), video.get("height"), formats.get(pix_fmt, pix_fmt)))
    # Other formats (12-bit, 4:2:2 ...) would lose quality in conversion.
    if pix_fmt not in formats:
        raise Skip("video format is {}, only 8-bit or 10-bit 4:2:0 is "
                   "supported".format(pix_fmt))
    # HDR brightness information and Dolby Vision data are not carried over
    # reliably yet, and pictures without them would look wrong.
    transfer = video.get("color_transfer")
    if transfer in ("smpte2084", "arib-std-b67"):
        raise Skip("HDR video ({}) is not supported yet".format(
            "PQ" if transfer == "smpte2084" else "HLG"))
    if any("dovi" in str(item.get("side_data_type", "")).lower()
           or "dolby" in str(item.get("side_data_type", "")).lower()
           for item in video.get("side_data_list", [])):
        raise Skip("Dolby Vision video is not supported yet")
    plan = encoding_plan(video)
    if plan["encoder"] not in encoders:
        raise Skip("this ffmpeg has no {} encoder, which this file "
                   "needs".format(plan["encoder"]))

    count, kept = choose_frames(ffmpeg, path, video["index"])
    if count > MAX_FRAMES:
        raise Skip("more than {} frames".format(MAX_FRAMES))
    if not kept:
        raise Skip("no frames could be read")
    image_count = len(kept)

    fps = Fraction(OUTPUT_FPS)
    # Each image lasts a whole number of video frames, so the real time per
    # image can differ slightly from the setting (10 s becomes 10.01 s).
    frames_per_image = max(1, round(SECONDS_PER_IMAGE * fps))
    total_frames = image_count * frames_per_image
    level, level_description = choose_level(video, fps, plan)
    print("  Level to apply: {}".format(level_description))

    filters = []
    chosen = select_filter(kept, count)
    if chosen:
        filters.append(chosen)
    # Space the images out, fill the gaps with repeats, and keep repeating
    # the last image; -frames:v below cuts it off at the right length.
    filters.append("setpts=N*{}/({})/TB".format(frames_per_image, fps))
    filters.append("fps={}".format(fps))
    filters.append("tpad=stop_mode=clone:stop=-1")

    out_path = free_output_path(out_folder, path.stem)

    with tempfile.TemporaryDirectory() as temp:
        chapters = write_chapters(temp, image_count, frames_per_image, fps)

        cover_args = []
        if KEEP_COVER_IMAGE and cover is not None:
            try:
                cover_file, mime = extract_cover(ffmpeg, path, cover, temp)
                # -attach stores it as a true attachment, not a video track.
                # The name is set here because ffmpeg on Windows would
                # otherwise record the full temporary path as the name.
                cover_args = ["-attach", str(cover_file),
                              "-metadata:s:t", "mimetype=" + mime,
                              "-metadata:s:t", "filename=" + cover_file.name]
            except Skip as problem:
                print("  Cover image left out ({})".format(problem))

        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-n",
               "-i", str(path),
               "-f", "ffmetadata", "-i", str(chapters)]
        cmd += cover_args
        cmd += ["-map", "0:{}".format(video["index"]),  # main video only; no audio
                "-map_metadata", "0",                   # file-level tags, e.g. encoded date
                "-map_chapters", "1",
                # Title = input file name without extension, replacing the
                # input's own title (rips usually carry the disc name there).
                "-metadata", "title=" + path.stem]
        cmd += stale_statistics_args(video)
        cmd += color_label_args(video)
        cmd += ["-vf", ",".join(filters), "-frames:v", str(total_frames)]
        cmd += encoder_args(level, frames_per_image, plan)
        cmd += [str(out_path)]
        print("  Encoding {} ({}) ...".format(out_path.name, plan["name"]))
        if subprocess.run(cmd).returncode != 0:
            raise Skip("ffmpeg could not write the output (see message above)")

    problems, new_duration, described = check_output(
        ffprobe, out_path, image_count, bool(cover_args), level, path.stem,
        plan["pix_fmt"])
    print("  Output: {}".format(described))
    print("  Done: {} images, {:.1f} s, saved as {}".format(
        image_count, new_duration, out_path))
    for problem in problems:
        print("  WARNING: output check found {}".format(problem))


def main():
    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        print("ffmpeg and/or ffprobe not found. Set FFMPEG_FOLDER at the top of "
              "this script to the folder that holds them.")
        return
    # Which encoder a file needs depends on the file, so it is checked per file.
    encoders = run([ffmpeg, "-hide_banner", "-encoders"])

    out_folder = Path(OUTPUT_FOLDER) if OUTPUT_FOLDER else SCRIPT_FOLDER
    out_folder.mkdir(parents=True, exist_ok=True)

    folder_mode = not INPUT_FILES
    if folder_mode:
        found = sorted(SCRIPT_FOLDER.glob("*.mkv"))
        files = [p for p in found if not is_own_output(p)]
        print("Processing the .mkv files in {}".format(SCRIPT_FOLDER))
        if len(files) != len(found):
            print('Left out {} file(s) with "{}" in the name.'.format(
                len(found) - len(files), OUTPUT_SUFFIX))
    else:
        files = [Path(p) for p in INPUT_FILES]
    if not files:
        print("No input files found.")

    done = 0
    for path in files:
        print("\n{}".format(path.name))
        try:
            if not path.is_file():
                raise Skip("file not found: {}".format(path))
            process(ffmpeg, ffprobe, path, out_folder, folder_mode, encoders)
            done += 1
        except Skip as reason:
            print("  Skipped: {}".format(reason))

    print("\nFinished. {} of {} file(s) converted.".format(done, len(files)))


if __name__ == "__main__":
    try:
        main()
    finally:
        # Keeps the window open when the script is started by double-click.
        try:
            input("\nPress Enter to close.")
        except EOFError:
            pass
    sys.exit(0)
