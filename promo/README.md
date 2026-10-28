# Hotstreak Hub — promo material

Everything here is generated from the disc's own artwork by
`tools/make_promo.py` (the 16:9 clip) and `tools/make_promo_kit.py` (the social
set). No external images, no stock footage.

| file | what it is |
|---|---|
| `promo.mp4` | 32 s, 1280x720, H.264 + AAC — the long clip |
| `reel.mp4` | 14 s, 1080x1920, H.264 + AAC — vertical, for Reels / Shorts / TikTok |
| `instagram/01-random-cast.png` | 1080x1080 post: the random cast |
| `instagram/02-stats.png` | 1080x1080 post: per-figure stat spreads (read from the patched pkz) |
| `instagram/03-bot-speed.png` | 1080x1080 post: the uniform bot speed per difficulty |
| `instagram/04-cups.png` | 1080x1080 post: the rolled cup line-up |
| `instagram/05-netplay.png` | 1080x1080 post: two machines, one session code |
| `instagram/story.png` | 1080x1920 story / swipe-up card |
| `flyer.png`, `flyer.pdf` | A4 at 300 dpi — printable flyer |

```sh
python3 tools/make_promo_kit.py              # the whole social set
python3 tools/make_promo_kit.py --posts      # just the square cards
python3 tools/make_promo_kit.py --reel       # just the vertical clip
python3 tools/make_promo.py --audio bed.wav  # the 16:9 clip (needs a music bed)
```

The numbers on the cards are not typed in: the stat bars come out of the patched
`BaseSkylander.pkz`, the bot speeds out of the `AIPersonality` records in
`BaseGameplay.pkz`, and the cup names out of `Common.pkz` — so a re-render after
a rebuild shows what the mod actually does.

## The five scenes

| | |
|---|---|
| 0–5 s | the game's logo, dimmed front-screen art behind it, "ROSTER MOD" |
| 5–11 s | `71 RACER SLOTS` — 56 drivers + 12 villains + 3 test dummies, 224 figures |
| 11–17 s | the four edits: random cast, balanced stats, random cups, your Skylander |
| 17–25 s | the field rolling: twelve cards spin and lock one by one |
| 25–32 s | the repo, and `python3 setup.py your-disc.iso` |

## The soundtrack

SSCR-Audio-Tool (Windows GUI, stdlib only) extracts and organizes everything in
`Streams2.dat`. The stream tables list **10144 unique streams / 384 MB** on this
disc; the cue used here is the longest one:

```sh
git clone https://github.com/Gopooo/SSRC-Audio-Tool /tmp/ssrc-audio
python3 - <<'PY'
import sys; sys.path.insert(0, "/tmp/ssrc-audio")
import SSCR_AudioTool as T
# jobs are (Streams2.dat, output_path, stream_offset, pad, byte_length)
jobs = T.build_extraction_jobs("disc/files/Data/Streams2.dat", "/tmp/audio")[3]
for job in sorted(jobs, key=lambda j: -j[4])[:10]:      # the ten longest cues
    print(T.extract_one_stream(job))
PY
```

That gives ten music-length cues in `neutral/` (75–170 s, 32 kHz stereo, decoded
from DSP-ADPCM to WAV). The clip uses `neutral/0010_v1_00afdb16.wav` — 170.3 s,
the same cue the language tables carry as `0010_v69_26772b56`. Its SoundBank is
`Col_SndBnkEventsSfx_BaseAudio`, which is how the media id was tied to a bank;
the tool's `stream_names.csv` gives that mapping for every stream.

Which 32 seconds: the loudest stretch of the track starts at 80 s, and the
quietest point in the 70–81 s window is **71.05 s**, so the excerpt starts there
and the fade-in hides the entry. It is normalised to −16 LUFS:

```sh
ffmpeg -y -ss 71.05 -t 32 -i neutral/0010_v1_00afdb16.wav \
       -af "loudnorm=I=-16:TP=-1.5:LRA=11" -ar 48000 -ac 2 /tmp/promo/audio.wav
```

Picked by measurement, not by ear: the cue never drops to silence (minimum RMS
over the excerpt is 0.066 against a 0.344 peak), so it is continuous music rather
than a cutscene with dialogue over it. If you want a different track, any WAV
works — `--audio` takes it directly.

## Re-render

```sh
python3 tools/make_promo.py --audio /tmp/promo/audio.wav     # promo/promo.mp4
python3 tools/make_promo.py --audio /tmp/promo/audio.wav --gif docs/promo.gif
python3 tools/make_promo.py --stills /tmp/frames             # one PNG per scene
```

Frames are rendered with Pillow and piped straight into ffmpeg, so a full render
is about 20 s. Needs the extracted art (`python3 tools/extract_art.py`) and
`ffmpeg` on `PATH`; `--seed` changes which figures are drawn.

Scenes are cut through black (0.3 s each side) rather than cross-faded, because
two text layouts dissolving into each other is unreadable.

## Rights

The artwork and the music are Activision's, and the clip is included only to show
what the mod does — it is not covered by this repo's MIT license.
