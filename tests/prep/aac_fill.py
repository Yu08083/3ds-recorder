import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from held_frames import boxes, record


def write_recording(path, active):
    data = bytearray(struct.pack("<4sIQBBBBIQ", b"R3DB", 6, 0, 1, 3, 30, 0, 32728498, 0))
    data += record(b"R3DF", 0, 0x40, 400, bytes(400 * 240 * 2))
    if active:
        for i in range(1200):
            t = round(i * 160 * 1e9 / 32728498)
            frame = bytearray()
            for n in range(i * 160, (i + 1) * 160):
                angle = n * 2 * math.pi / 32728.498
                left = int(16000 * math.sin(440 * angle) + 4000 * math.sin(1600 * angle))
                right = int(5000 * math.sin(659 * angle) + 11000 * math.sin(2300 * angle))
                frame += struct.pack("<hh", left, right)
            data += record(b"R3DA", t, 2, 160, frame)
    data += record(b"R3DE", 8000000, 0, 0, struct.pack("<4I", 1, 0, 0, 0))
    path.write_bytes(data)


def audio_info(mp4):
    moov = dict(boxes(mp4))[b"moov"]
    for tag, payload in boxes(moov):
        if tag != b"trak":
            continue
        track = dict(boxes(payload))
        mdia = dict(boxes(track[b"mdia"]))
        if mdia[b"hdlr"][8:12] != b"soun":
            continue
        table = dict(boxes(dict(boxes(mdia[b"minf"]))[b"stbl"]))
        sizes = [n for n, in struct.iter_unpack(">I", table[b"stsz"][12:])]
        entry = dict(boxes(table[b"stsd"][8:]))[b"mp4a"]
        descriptor = dict(boxes(entry[28:]))[b"esds"]
        assert descriptor[9:11] == bytes([4, 17])
        peak, average = struct.unpack_from(">II", descriptor, 16)
        assert average == sum(sizes) * 8 * 32000 // (len(sizes) * 1024)
        assert peak >= average
        timeline = (track[b"tkhd"], track[b"edts"], mdia[b"mdhd"], table[b"stts"])
        return sum(sizes), timeline
    raise AssertionError("Missing AAC track")


def convert(driver, source, output):
    subprocess.run([driver, source, output], capture_output=True, check=True, timeout=90)
    video = output.with_suffix(".mp4")
    pcm = subprocess.check_output([os.environ.get("FFMPEG", "ffmpeg"), "-v", "error", "-xerror",
                                   "-i", video, "-map", "0:a:0", "-f", "s16le", "-"])
    assert len(pcm) // 4 >= 7.9 * 32000
    size, timing = audio_info(video.read_bytes())
    return pcm, size, timing


if __name__ == "__main__":
    compact, reference = (Path(arg).resolve() for arg in sys.argv[1:3])
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        for active, prefix in [(False, "silence"), (True, "stereo")]:
            source = directory / (prefix + ".r3d")
            write_recording(source, active)
            pcm, size, timeline = convert(compact, source, directory / (prefix + "-mp4"))
            padded, padded_size, padded_timeline = convert(reference, source, directory / (prefix + "-padded"))
            assert pcm == padded and timeline == padded_timeline
            assert any(pcm) == active
            assert size < padded_size
            if not active:
                assert size < padded_size // 8
            print(f"{prefix}: AAC {padded_size} -> {size} bytes, decoded PCM and sample timing match")
