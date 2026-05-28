"""Shared ffmpeg args for MP4 output with subtitle preservation."""
from __future__ import annotations


def _maps_and_codecs(
    *,
    reencode: bool,
    include_embedded_subs: bool,
    extra_sub_count: int,
) -> list[str]:
    cmd: list[str] = ["-map", "0:v:0?", "-map", "0:a?"]
    if include_embedded_subs:
        cmd.extend(["-map", "0:s?"])
    for idx in range(extra_sub_count):
        cmd.extend(["-map", f"{idx + 1}:0"])
    if reencode:
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
            ]
        )
    else:
        cmd.extend(["-c:v", "copy", "-c:a", "copy"])
    if include_embedded_subs or extra_sub_count:
        cmd.extend(["-c:s", "mov_text"])
    return cmd


def ffmpeg_mp4_command(
    *,
    input_path: str,
    output_path: str,
    reencode: bool,
    include_embedded_subs: bool = True,
    extra_subtitle_paths: list[str] | None = None,
    streaming: bool = False,
) -> list[str]:
    """
    Build ffmpeg CLI for MKV/AVI → MP4.

    Embedded subs are mapped and converted to mov_text (MP4-safe).
    Optional extra inputs are sidecar .srt/.vtt files from the library.
    """
    extras = [p for p in (extra_subtitle_paths or []) if p]
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-probesize",
        "50M",
        "-analyzeduration",
        "100M",
        "-i",
        input_path,
    ]
    for p in extras:
        cmd.extend(["-i", p])
    cmd.extend(
        _maps_and_codecs(
            reencode=reencode,
            include_embedded_subs=include_embedded_subs,
            extra_sub_count=len(extras),
        )
    )
    if streaming:
        cmd.extend(
            [
                "-movflags",
                "frag_keyframe+empty_moov+default_base_moof",
                "-f",
                "mp4",
            ]
        )
    else:
        cmd.extend(["-movflags", "+faststart", "-f", "mp4"])
    cmd.append(output_path)
    return cmd


def ffmpeg_mp4_pipe_command(
    *,
    reencode: bool,
    include_subtitles: bool = True,
) -> list[str]:
    """ffmpeg reading stdin, writing fragmented MP4 to stdout."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-probesize",
        "50M",
        "-analyzeduration",
        "100M",
        "-i",
        "pipe:0",
    ]
    cmd.extend(
        _maps_and_codecs(
            reencode=reencode,
            include_embedded_subs=include_subtitles,
            extra_sub_count=0,
        )
    )
    cmd.extend(
        [
            "-movflags",
            "frag_keyframe+empty_moov+default_base_moof",
            "-f",
            "mp4",
            "pipe:1",
        ]
    )
    return cmd
