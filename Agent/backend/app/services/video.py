"""Video assembly service — combines video clips with voiceover using FFmpeg."""

import asyncio
import os
import random
import tempfile
from pathlib import Path
from uuid import uuid4

from app.services.storage import download_file, upload_file, get_public_url


async def assemble_video(
    video_keys: list[str],
    audio_path: str,
    shuffle: bool = True,
) -> str:
    """Assemble a video from clips + voiceover audio.

    1. Downloads all video clips from S3
    2. Shuffles them randomly
    3. Concatenates them with FFmpeg
    4. Overlays the voiceover audio
    5. Uploads result to S3

    Args:
        video_keys: S3 keys of video clips to combine.
        audio_path: Local path to the voiceover audio file.
        shuffle: Whether to randomize clip order.

    Returns:
        Public URL of the assembled video.
    """
    if not video_keys:
        raise ValueError("No video clips provided.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # 1. Download clips
        clip_paths = []
        for i, key in enumerate(video_keys):
            ext = Path(key).suffix or ".mp4"
            local_path = tmpdir / f"clip_{i:03d}{ext}"
            data = download_file(key)
            local_path.write_bytes(data)
            clip_paths.append(local_path)

        # 2. Shuffle
        if shuffle:
            random.shuffle(clip_paths)

        # 3. Create FFmpeg concat file
        concat_file = tmpdir / "concat.txt"
        with open(concat_file, "w") as f:
            for clip in clip_paths:
                f.write(f"file '{clip}'\n")

        # 4. Concatenate clips
        concat_output = tmpdir / "concat.mp4"
        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(concat_output),
        ]
        proc = await asyncio.create_subprocess_exec(
            *concat_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            # Fallback: re-encode if copy fails (different codecs)
            concat_cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_file),
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac",
                str(concat_output),
            ]
            proc = await asyncio.create_subprocess_exec(
                *concat_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"FFmpeg concat failed: {stderr.decode()[-500:]}")

        # 5. Overlay voiceover audio
        final_output = tmpdir / "final.mp4"
        overlay_cmd = [
            "ffmpeg", "-y",
            "-i", str(concat_output),
            "-i", audio_path,
            "-filter_complex",
            # Mix original audio (quieter) + voiceover
            "[0:a]volume=0.15[bg];[1:a]volume=1.0[vo];[bg][vo]amix=inputs=2:duration=shortest[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            str(final_output),
        ]
        proc = await asyncio.create_subprocess_exec(
            *overlay_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            # If clip has no audio, just add voiceover as sole audio
            overlay_cmd = [
                "ffmpeg", "-y",
                "-i", str(concat_output),
                "-i", audio_path,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                str(final_output),
            ]
            proc = await asyncio.create_subprocess_exec(
                *overlay_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"FFmpeg overlay failed: {stderr.decode()[-500:]}")

        # 6. Upload to S3
        result_data = final_output.read_bytes()
        result_key = upload_file(result_data, f"video_{uuid4().hex[:8]}.mp4", "video/mp4")

        return get_public_url(result_key)
