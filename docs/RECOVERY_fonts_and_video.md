# Recovery Guide — Font Warnings & Missing imageio_ffmpeg

## What you saw

```
WARNING  matplotlib.font_manager  findfont: Font family 'Inter' not found.
WARNING  matplotlib.font_manager  findfont: Font family 'Helvetica' not found.
ERROR    [Video] Write failed: No module named 'imageio_ffmpeg'
INFO     [VIDEO] Done: 0/5 videos generated
```

## Root cause (verified)

**Font warnings (cosmetic):**
matplotlib has its **own** font cache, separate from fontconfig. Even
when `fonts-inter` is installed at the OS level (visible to `fc-list`),
matplotlib can't see it until its cache is rebuilt. Helvetica is not an
open-source font — it's never present in Linux containers — so it must
be replaced with Liberation Sans (the metric-equivalent open-source
counterpart) in the fallback chain.

**imageio_ffmpeg missing (critical):**
The container you ran was built **before** `imageio-ffmpeg` was added
to its layer in the Dockerfile. Docker Compose was reusing a cached
image — your `docker compose up` doesn't trigger a rebuild on its own.

## What's been fixed in the new archive

| File | Change |
|------|--------|
| `cerebro_brand.py` | Drops `Helvetica`, adds `Liberation Sans`. Adds `register_brand_fonts()` helper that bypasses the matplotlib cache by registering fonts via `fontManager.addfont()`. |
| `run.py` | Calls `register_brand_fonts()` **before** `matplotlib_style()` at startup, so Inter is actually used (not just listed) and the warnings disappear. |
| `Dockerfile` | Adds `fonts-liberation` to Layer 1. Adds **build-time smoke tests** that abort the build if `imageio_ffmpeg` can't be imported or if no brand fonts can be registered — preventing this exact bug from ever shipping again. |
| `src/viz/cerebro_video_engine_v2.py` | When `imageio_ffmpeg` is missing, the error message now tells the user how to recover (one-liner) instead of just emitting a cryptic ImportError. |

## Quick recovery for your CURRENT running container

If you don't want to rebuild right now and just want videos working
in the next pipeline pass:

```bash
docker compose exec cerebro-core bash -c "pip install imageio-ffmpeg==0.5.1 && \
  python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'"
```

Then trigger a re-run. Videos should generate. The font warnings will
remain until the image is rebuilt — they're cosmetic.

## Permanent fix — rebuild from the new archive

```bash
# 1. Drop the current image (essential — `up` alone won't pick up the
#    new Dockerfile because Compose tags don't change).
docker compose down
docker rmi cerebro-x:latest 2>/dev/null || true

# 2. Rebuild WITHOUT cache so all layers are reconsidered.
docker compose build --no-cache

# 3. Start.
docker compose up -d
docker compose logs -f cerebro-core
```

You should see in the build log:

```
[BUILD-CHECK] imageio=2.36.1, imageio_ffmpeg=0.5.1
[BUILD-CHECK] bundled ffmpeg: /usr/local/lib/python3.13/site-packages/imageio_ffmpeg/binaries/ffmpeg-...
[BUILD-FONTS] Inter files added: 9, Liberation files added: 4
[BUILD-CHECK] Inter ready: True, Liberation ready: True
```

If any of these checks **fail**, the build aborts — you'll never again
end up with a running container that's missing imageio_ffmpeg or fonts.

## Why the build-time checks matter

Before this patch, the Dockerfile had:

```dockerfile
RUN pip install --no-cache-dir \
        imageio==2.34.0 \
        imageio-ffmpeg==0.4.9 \
        ...
```

If pip silently skipped one package (network blip, version conflict),
the `RUN` returned 0 and the build "succeeded" with a missing package.
Now there's an explicit `RUN python -c "import imageio_ffmpeg"` line —
the build aborts the moment the package isn't importable.

Same principle for fonts: the build now refuses to ship an image where
neither Inter nor Liberation Sans can be registered with matplotlib.

## Sanity check after rebuild

In the running container:

```bash
docker compose exec cerebro-core python -c "
from cerebro_brand import register_brand_fonts
status = register_brand_fonts(verbose=True)
print(status)
import imageio_ffmpeg
print('ffmpeg:', imageio_ffmpeg.get_ffmpeg_exe())
"
```

Expected output:

```
[BRAND-FONTS] Inter files added: 9, Liberation files added: 4
[BRAND-FONTS] Inter detected: True, Liberation detected: True
{'inter': True, 'liberation': True, 'inter_files': 9, 'liberation_files': 4}
ffmpeg: /usr/local/lib/python3.13/site-packages/imageio_ffmpeg/binaries/ffmpeg-...
```

Once you see that, the next `docker compose run` will produce all 5
MP4 videos and zero font warnings.
