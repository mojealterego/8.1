"""Read-only structural sanity check of an AOSP 8.1 generic system image.

SANITY_PASS is NOT build/reproducibility/emulator validation. A fake test image
may pass it: production evidence additionally requires build command exit 0.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

SPARSE_MAGIC = bytes.fromhex('3aff26ed')
EXT4_MAGIC = bytes.fromhex('53ef')
MIN_IMAGE_BYTES = 1024 * 1024


class ImageGateError(RuntimeError):
    pass


def _read_prop(path: Path) -> dict[str, str]:
    d: dict[str, str] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1)
            if k in d:
                raise ImageGateError('duplicate_build_property:' + k)
            d[k]=v
    return d


def inspect_product_image(out_dir: Path) -> dict:
    out_dir=out_dir.resolve(strict=True)
    image=out_dir/'system.img'
    prop=out_dir/'system/build.prop'
    if not image.is_file() or image.is_symlink():
        raise ImageGateError('missing_image')
    if image.stat().st_size < MIN_IMAGE_BYTES:
        raise ImageGateError('image_too_small')
    if not prop.is_file() or prop.is_symlink():
        raise ImageGateError('missing_build_prop')
    properties=_read_prop(prop)
    if (properties.get('ro.build.version.sdk') != '27'
            or properties.get('ro.build.version.release') != '8.1.0'):
        raise ImageGateError('incorrect_android_version')
    with image.open('rb') as handle:
        prefix=handle.read(1082)
    if not (prefix[:4] == SPARSE_MAGIC or prefix[1080:1082] == EXT4_MAGIC):
        raise ImageGateError('invalid_image_format')
    hash_obj=hashlib.sha256()
    with image.open('rb') as handle:
        for buf in iter(lambda: handle.read(4*1024*1024), b''):
            hash_obj.update(buf)
    return {
        'gate':'F1_IMAGE_SANITY', 'result':'SANITY_PASS',
        'sha256':hash_obj.hexdigest(), 'size_bytes':image.stat().st_size,
        'android_api':27, 'emulator_status':'NOT_TESTED',
        'hardware_status':'BLOCKED',
    }


def main(argv: list[str] | None=None) -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--product-out',type=Path,required=True)
    args=p.parse_args(argv)
    try:
        result=inspect_product_image(args.product_out)
    except (OSError, ImageGateError, ValueError) as exc:
        print(json.dumps({'gate':'F1_IMAGE_SANITY','result':'BLOCKED','reason':str(exc)},sort_keys=True))
        return 2
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=='__main__':
    sys.exit(main())