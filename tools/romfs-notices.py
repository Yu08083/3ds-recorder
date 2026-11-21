from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root / 'app/romfs/licenses'
output.mkdir(parents=True, exist_ok=True)
for source, name in (
    ('LICENSE', '3DS-Recorder-MIT.txt'),
    ('third_party/minih264/LICENSE', 'minih264.txt'),
    ('third_party/vo-aacenc/COPYING', 'vo-aacenc.txt'),
    ('third_party/vo-aacenc/NOTICE', 'vo-aacenc-NOTICE.txt'),
    ('third_party/vo-aacenc/aacenc/NOTICE', 'vo-aacenc-aacenc-NOTICE.txt'),
    ('third_party/vo-aacenc/common/NOTICE', 'vo-aacenc-common-NOTICE.txt'),
    ('web/vendor/mp4-muxer.LICENSE', 'mp4-muxer.txt'),
    ('app/assets/fonts/OFL.txt', 'Inter-OFL.txt'),
    ('app/assets/fonts/OFL-NotoSansCJK.txt', 'NotoSansCJK-OFL.txt'),
):
    (output/name).write_bytes((root/source).read_bytes())
qr = (root/'third_party/qrcodegen/qrcodegen.c').read_bytes()
notice, end, _ = qr.partition(b'*/')
assert end and b'copyright' in notice.lower()
(output/'qrcodegen.txt').write_bytes(notice + end + b'\n')
asm = (root/'app/source/csvc.s').read_bytes().replace(b'\r\n', b'\n')
notice, marker, _ = asm.partition(b'\n.arm\n')
assert marker and b'This notice may not be removed' in notice
(output/'Luma3DS-csvc.txt').write_bytes(notice + b'\n')
