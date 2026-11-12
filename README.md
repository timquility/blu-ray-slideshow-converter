# Blu-ray Slideshow Converter

Turns a photo-gallery rip from a Blu-ray disc into a normal video file.

MakeMKV can extract photo galleries from a Blu-ray disc as an .mkv in which every image flashes past in quick succession. This script finds the individual images and generates a new .mkv where each image stays on screen for a time you choose, with one chapter per image. Your original files are never changed.

## Output

- Output file names match the input file name with `_slideshow` appended. If that name exists, `_2`, `_3`, and so on are used. Nothing is overwritten.
- One video track. Each image is held for the time you set (default 10 seconds).
- One chapter per image, named "Chapter 01", "Chapter 02", and so on.
- No audio track.
- Input file MKV cover image carried over as an attachment in the output (optional).
- The output file MKV header title set to the input file name without its extension.
- The source's color labels copied to the output, so players show the same colors as the original.
- 8-bit sources stay 8-bit. 10-bit sources (for example from 4K discs) stay 10-bit.

## Requirements

- **Python 3** (no extra Python packages needed).
- **A recent ffmpeg and ffprobe.** ffmpeg must include the HEVC encoder (`libx265`) for lossless output and for all 10-bit sources, or the H.264 encoder (`libx264`) for normal output from 8-bit sources. Most full builds include both.

Download ffmpeg from [ffmpeg.org](https://ffmpeg.org/download.html). ffmpeg is not included in this repository.

If ffmpeg and ffprobe are on your system PATH, nothing more is needed. Otherwise, either put them in the same folder as the script or set `FFMPEG_FOLDER` (see Settings).

## How to use

1. Open the script in a text editor and change values under `USER SETTINGS` if desired, then save.
2. Run it. Either double-click the file, or run this from a terminal in the script's folder:

   ```
   python mkv_slideshow.py
   ```
3. If the `INPUT_FILES` list is left empty, every .mkv in the script's folder is processed by default. Files that already have `_slideshow` in the name, and files longer than 60 seconds (taken to be normal videos), are excluded.
4. The terminal reports what it found for each file: frame and image counts, which solid-color frames were dropped, the picture size, and the codec, profile and level of the result. Read the report to confirm the image count looks right.

## Settings

All settings are at the top of the script.

| Setting | What it does | Default |
|---|---|---|
| `KEEP_EVERY_N_FRAMES` | Fixed Frame Count method: keep every Nth frame and drop the rest. Use this if each image on the disc is shown for a known, equal number of frames. `0` turns it off. | `0` |
| `SAME_IMAGE_PERCENT` | Automatic method (used when the setting above is `0`): a frame counts as a repeat of the image before it when less than this percent of the picture differs. `0` drops only exact copies. | `5` |
| `SOLID_COLOR_PERCENT` | Drops solid-color frames. A frame is dropped when at least this percent of the picture is one color. `100` means completely solid frames only. `0` keeps them. | `95` |
| `LOSSLESS` | `True` gives an exact copy of the pictures (HEVC/H.265). `False` gives H.264 for 8-bit sources (quality set by `QUALITY_CRF`) and HEVC for 10-bit sources (quality set by `QUALITY_CRF_10BIT`). | `True` |
| `INPUT_FILES` | Full paths of the files to convert. Empty means every .mkv in the script's folder. | empty |
| `OUTPUT_FOLDER` | Where to save the results. Empty means the script's folder. | empty |
| `SECONDS_PER_IMAGE` | How long each image stays on screen. | `10` |
| `KEEP_COVER_IMAGE` | Carry the cover image over as an attachment. | `True` |
| `FFMPEG_FOLDER` | Folder holding ffmpeg and ffprobe. Leave empty if they are on PATH. | empty |
| `OUTPUT_FPS` | Output frame rate. | `24000/1001` (23.976) |
| `QUALITY_CRF` | 8-bit sources with `LOSSLESS = False` (H.264). Lower means higher quality and a larger file. | `4` |
| `QUALITY_CRF_10BIT` | 10-bit sources with `LOSSLESS = False` (HEVC). Lower means higher quality and a larger file. | `12` |
| `ENCODER_PRESET` | Encoder speed preset. Slower presets give smaller files and take longer. | `slow` |
| `OUTPUT_SUFFIX` | Added to the input file name. | `_slideshow` |
| `CHAPTER_NAME` | Chapter title. `{}` becomes the number. | `Chapter {}` |
| `MAX_INPUT_SECONDS` | Folder mode only: files longer than this are skipped. | `60` |
| `MAX_FRAMES` | Files with more frames than this are skipped. | `2000` |

## Notes and limits

- **Each image lasts a whole number of video frames.** At the default settings, 10 seconds becomes 10.01 seconds.
- **Only 8-bit and 10-bit 4:2:0 video is supported.** Other formats (12-bit, 4:2:2 and so on) are skipped with a message, because converting them would lose quality.
- **HDR and Dolby Vision are not supported yet.** HDR (PQ or HLG) and Dolby Vision sources are skipped with a message, because their brightness information is not carried over reliably and the pictures would look wrong.
- **Lossless output is large.** Lossless HEVC keeps every pixel, so files can be much bigger than normal video. Set `LOSSLESS = False` for smaller files.
- **Level label.** A level is a label telling players how demanding a video is. The HEVC encoder labels lossless output with an unrestricted level, and lossy output by picture size alone. Some players refuse an unusual label, so the script rewrites only the label to level 4.1 (up to about 1920x1080) or 5.1 (up to about 4K). The video data is unchanged. The first frame of each image can be larger than the level strictly allows, so the label is nominal.
- **If the image count looks wrong,** adjust `SAME_IMAGE_PERCENT`. The report shows the smallest change among frames kept as new images and the largest change among frames dropped as repeats. Both numbers should be well away from your setting. The solid-color report works the same way for `SOLID_COLOR_PERCENT`.
- **Tested on Windows.** The script is plain Python and should work on macOS and Linux, but that has not been tested.

## Changes

The change history is at the top of the script file.

## License

Copyright is held by the author. This program is free software, licensed under the **GNU General Public License, version 3**. See the [LICENSE](LICENSE) file for the full text.

You may use, copy and change it. If you distribute it or a modified version, you must do so under the same license and provide the source code.

This program comes with no warranty.

## Credits

Written with the help of Claude.
