import hashlib
import itertools
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


def record(tag, time_us, screen, width, data):
    header = struct.pack("<4sIIBBH", tag, len(data), time_us, screen, 2, width)
    return header + data + bytes(-len(data) % 16)


def zero_pairs(count):
    result = bytearray()
    while count:
        size = min(32768, count)
        result += struct.pack("<H", size - 1)
        count -= size
    return result


def write_fixture(path, pictures, repeats):
    cols = (400, 320)
    data = bytearray(struct.pack("<4sIQBBBBIQ", b"R3DB", 6, 0, 1, 4, 25, 0, 32728498, 0))
    audio = struct.pack("<hh", 1200, -1200) * 160
    previous = None
    counts = [0, 0]
    for i, pixels in enumerate(pictures):
        t = i * 40000
        for sc, width in enumerate(cols):
            if previous is None:
                assert pixels[sc] == 0
                data += record(b"R3DF", t, 0x40 | sc, width, bytes(width * 480))
            elif pixels[sc] != previous[sc]:
                payload = struct.pack("<HHH", 0x8000, 0xffff, 0)
                data += record(b"R3DY", t, sc, width, payload + zero_pairs(width * 120 - 1))
            elif repeats:
                data += record(b"R3DY", t, sc, width, zero_pairs(width * 120))
            else:
                continue
            counts[sc] += 1
        previous = pixels
        data += record(b"R3DA", t, 2, 160, audio)
    data += record(b"R3DE", len(pictures) * 40000, 0, 0, struct.pack("<4I", *counts, 0, 0))
    path.write_bytes(data)


def boxes(data):
    offset = 0
    while offset < len(data):
        size, tag = struct.unpack_from(">I4s", data, offset)
        assert 8 <= size <= len(data) - offset
        yield tag, data[offset + 8:offset + size]
        offset += size


def samples(mp4):
    moov = dict(boxes(mp4))[b"moov"]
    tracks = {}
    for tag, track in boxes(moov):
        if tag != b"trak":
            continue
        mdia = dict(boxes(dict(boxes(track))[b"mdia"]))
        kind = mdia[b"hdlr"][8:12]
        scale = struct.unpack_from(">I", mdia[b"mdhd"], 12)[0]
        stbl = dict(boxes(dict(boxes(mdia[b"minf"]))[b"stbl"]))
        stts = stbl[b"stts"]
        ranges = list(struct.iter_unpack(">II", stts[8:]))
        assert len(ranges) == struct.unpack_from(">I", stts, 4)[0]
        durations = [duration for count, duration in ranges for _ in range(count)]
        assert len(durations) == struct.unpack_from(">I", stbl[b"stsz"], 8)[0]
        keys = [key for key, in struct.iter_unpack(">I", stbl.get(b"stss", b"")[8:])]
        sizes = [n for n, in struct.iter_unpack(">I", stbl[b"stsz"][12:])]
        offsets = [n for n, in struct.iter_unpack(">I", stbl[b"stco"][8:])]
        assert len(sizes) == len(offsets) == len(durations)
        digest = hashlib.sha256()
        for offset, size in zip(offsets, sizes):
            digest.update(mp4[offset:offset + size])
        tracks[kind] = (scale, durations, keys, digest.digest())
    return tracks


def test(driver, directory, name, pictures, repeats, resume_at=0, resume_frame=0):
    source = directory / (name + ".r3d")
    write_fixture(source, pictures, repeats)
    output = directory / name
    args = [driver, source, output, "--threads", "2"]
    if resume_at:
        args.extend(["--resume-at-permille", str(resume_at)])
    run = subprocess.run(args, capture_output=True, text=True, check=True, timeout=90)
    if resume_at:
        assert f"resumed at frame {resume_frame} " in run.stderr, run.stderr
    mp4 = output.with_suffix(".mp4").read_bytes()
    tracks = samples(mp4)
    scale, durations, keys, _ = tracks[b"vide"]
    expected = [sum(1 for _ in group) * 40 for _, group in itertools.groupby(pictures)]
    assert scale == 1000 and durations == expected, (name, durations, expected)
    assert keys and keys[0] == 1
    assert all(i in keys for i, duration in enumerate(durations, 1) if duration >= 400)
    if resume_at:
        assert resume_frame + 1 in keys
    audio_rate, audio_durations, _, _ = tracks[b"soun"]
    assert audio_rate == 32000 and len(audio_durations) > 0
    assert abs(sum(audio_durations) / audio_rate - len(pictures) * 0.04) < 0.15
    return len(mp4), tracks


if __name__ == "__main__":
    exe = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        black = [(0, 0)] * 150
        assert test(exe, directory, "black", black, True) == test(exe, directory, "held", black, False)
        pictures = [(n % 2, 0) for n in range(120)] + [(1, 0)] * 300 + [(1, 1), (1, 0), (0, 0)]
        regular = test(exe, directory, "regular", pictures, True)
        sparse = test(exe, directory, "sparse", pictures, False)
        assert regular == sparse
        _, resumed_tracks = test(exe, directory, "resumed", pictures, True, 825, 120)
        assert resumed_tracks[b"soun"][1] == regular[1][b"soun"][1]
        mid_gop = [(n % 2, 0) for n in range(37)] + [(0, 0)] * 300 + [(0, 1)]
        test(exe, directory, "mid-gop", mid_gop, True, 650, 37)
        moving = [(n % 2, 0) for n in range(180)]
        test(exe, directory, "moving", moving, True, 50, 120)
    print("Held pictures: both screens, first black frame, single-pixel changes, audio and resumed MP4 timings passed.")
