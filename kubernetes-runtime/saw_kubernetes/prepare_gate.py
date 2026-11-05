"""Publish the shared tool-gate tree on its dedicated PVC before workspace startup."""
import argparse
import os
from pathlib import Path
import tempfile

from .core import shared


def verify(directory, files):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("invalid gate directory")
    dirs = {p for item in files for p in Path(item).parents} - {Path(".")}
    for path in directory.rglob("*"):
        rel = path.relative_to(directory)
        if path.is_symlink() or (rel not in dirs if path.is_dir() else rel.as_posix() not in files):
            raise ValueError("unexpected entry in the trusted gate")
    for rel, (data, _) in files.items():
        path = directory / rel
        if not path.is_file() or path.read_bytes() != data:
            raise ValueError("existing gate differs from the requested policy or owner")


def publish(root, identity, receipt_key=None):
    assets = Path(shared.__file__).parent
    files, _, digest, _ = shared.tool_gate_bundle(assets, identity, receipt_key)
    target = root / "bundle"
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=root) as scratch:
            tmp = Path(scratch) / "bundle"
            tmp.mkdir(mode=0o755)
            for rel, (data, _) in files.items():
                path = tmp / rel
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(data)
                path.chmod(0o444)
            # The final nonempty tree is never overwritten, including concurrent publishers.
            try:
                tmp.rename(target)
            except FileExistsError:
                pass
            except OSError:
                if not target.is_dir():
                    raise
    verify(target, files)
    return digest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("owner", "subject", "workspace", "sandbox"):
        parser.add_argument("--" + key, required=True)
    receipt = parser.add_mutually_exclusive_group()
    receipt.add_argument("--receipt-key")
    receipt.add_argument("--writer-service")
    parser.add_argument("--writer-namespace")
    parser.add_argument("--writer-ca")
    args = parser.parse_args()
    if args.writer_service:
        from .receipt import receipt_key
        args.receipt_key = receipt_key(args.writer_service, args.writer_namespace, args.writer_ca)
    os.umask(0o022)
    print(publish(Path("/volume"), shared.tool_gate_identity(args.owner, args.subject, args.workspace, args.sandbox), args.receipt_key))
