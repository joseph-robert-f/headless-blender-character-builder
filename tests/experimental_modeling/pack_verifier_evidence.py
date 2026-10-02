"""Keep a bounded copy of verifier evidence for independent review."""
import argparse
from itertools import chain
from pathlib import Path
import zipfile

MAX_ARCHIVE = 24 * 1024 * 1024  # Below the 32 MiB transfer limit after outer ZIP.
MAX_INPUT = 512 * 1024 * 1024
MAX_FILES = 4096


def pack(root, output, *, max_archive=MAX_ARCHIVE):
    root, output = Path(root), Path(output)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Evidence root must be a regular directory.')
    inputs = root / 'modeling-verifier-validation'
    if inputs.is_symlink() or not inputs.is_dir():
        raise ValueError('Verifier evidence is unavailable.')
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(inputs.resolve()):
        raise ValueError('Use a new output outside verifier evidence.')
    files, total = [], 0
    ui = root / 'modeling-review-ui'
    if ui.is_symlink():
        raise ValueError('Linked evidence is not supported.')
    candidates = chain(inputs.rglob('*'), ui.glob('verifier-*') if ui.is_dir() else ())
    for entry_count, path in enumerate(candidates, 1):
        if entry_count > MAX_FILES:
            raise ValueError('Evidence exceeds the entry limit.')
        if path.is_symlink():
            raise ValueError('Linked evidence is not supported.')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('Evidence must be a regular file.')
        total += path.stat().st_size
        files.append(path)
        if total > MAX_INPUT:
            raise ValueError('Evidence exceeds the input limit.')
    partial = output.with_name(output.name + '.partial')
    with zipfile.ZipFile(partial, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(root).as_posix())
    if partial.stat().st_size > max_archive:
        raise ValueError('Evidence exceeds the archive limit. The complete CI artifact remains separate.')
    partial.rename(output)
    return {'files': len(files), 'input_bytes': total, 'archive_bytes': output.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(pack(args.root, args.output))


if __name__ == '__main__':
    main()
