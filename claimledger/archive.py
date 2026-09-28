"""Bounded canonical ZIP transport. Never extract paths supplied by an archive."""
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import tempfile
import zipfile

from . import core as c
from .report import render

MAX_ARCHIVE = 20 * 1024 * 1024
MAX_EXPANDED = 18 * 1024 * 1024
MAX_FILES = 1002
MAX_MANIFEST = 256 * 1024
MAX_DIRECTORY = 160 * 1024
SNAPSHOT = re.compile(r'snapshots/[0-9a-f]{64}\.txt\Z')


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def parse(payload):
    return json.loads(payload.decode('utf-8'), object_pairs_hook=c.pairs,
                      parse_constant=lambda x: c.require(False, 'invalid JSON constant'))


def payloads(data):
    c.valid(data)
    ledger = c.encoded(data)
    c.require(len(ledger) <= c.MAX_LEDGER, 'ledger byte limit exceeded')
    # Restoration promises a reportable ledger, so enforce its existing output limit.
    render(data)
    files = {'ledger.json': ledger}
    for source in data['sources']:
        files['snapshots/'+source['sha256']+'.txt'] = source['text'].encode('utf-8')
    return files


def pack(files):
    """Canonical transport metadata, independent of filesystem and clock."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.create_version = info.extract_version = 20
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, content)
    return output.getvalue()


def manifest(files):
    return c.encoded({'format': 'claim-source-ledger', 'version': 1,
                      'files': {name: {'bytes': len(content), 'sha256': sha(content)}
                                for name, content in sorted(files.items())}})


def build(data):
    files = payloads(data)
    files['manifest.json'] = manifest(files)
    c.require(len(files) <= MAX_FILES, 'archive file-count limit exceeded')
    c.require(sum(map(len, files.values())) <= MAX_EXPANDED, 'expanded-byte limit exceeded')
    result = pack(files)
    c.require(len(result) <= MAX_ARCHIVE, 'archive byte limit exceeded')
    return result


def inspect_bytes(raw):
    """Validate before returning any bytes eligible for restoration."""
    c.require(len(raw) <= MAX_ARCHIVE, 'archive byte limit exceeded')
    # Bound central-directory allocation before ZipFile creates per-entry objects.
    c.require(len(raw) >= 22, 'truncated ZIP')
    end = struct.unpack('<4s4H2IH', raw[-22:])
    magic, disk, directory_disk, disk_count, count, size, offset, comment = end
    c.require(magic == b'PK\x05\x06' and disk == directory_disk == comment == 0,
              'unsupported ZIP envelope')
    c.require(disk_count == count and 2 <= count <= MAX_FILES, 'archive file-count limit exceeded')
    c.require(size <= MAX_DIRECTORY and offset + size == len(raw)-22, 'invalid ZIP directory')
    # Count actual directory headers independently of the untrusted EOCD count.
    cursor = offset
    actual = 0
    while cursor < offset + size:
        c.require(cursor + 46 <= offset + size and raw[cursor:cursor+4] == b'PK\x01\x02', 'invalid ZIP directory header')
        name_size, extra_size, comment_size = struct.unpack_from('<3H', raw, cursor+28)
        c.require(extra_size == comment_size == 0, 'ZIP extras and comments are unsupported')
        name_end = cursor + 46 + name_size
        c.require(name_end <= offset+size, 'truncated ZIP filename')
        name = raw[cursor+46:name_end].decode('ascii')
        c.require(name in ('ledger.json', 'manifest.json') or SNAPSHOT.fullmatch(name), 'unexpected archive path')
        # Reject extras/comments and arbitrary names before ZipFile can interpret
        # a fake ZIP64 locator embedded just before the end record.
        cursor = name_end
        actual += 1
        c.require(actual <= MAX_FILES, 'archive file-count limit exceeded')
    c.require(cursor == offset+size and actual == count, 'ZIP directory count mismatch')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            files = {}
            total = 0
            for info in infos:
                name = info.filename
                c.require(name == info.orig_filename and (name in ('ledger.json', 'manifest.json') or SNAPSHOT.fullmatch(name)), 'unexpected archive path')
                c.require(name not in files, 'duplicate archive entry')
                c.require(info.compress_type == zipfile.ZIP_STORED and info.flag_bits == 0,
                          'only unencrypted stored ZIP entries are supported')
                c.require(info.create_system == 3 and info.external_attr == (stat.S_IFREG | 0o600) << 16,
                          'non-regular entry or unsupported permissions')
                limit = MAX_MANIFEST if name == 'manifest.json' else c.MAX_LEDGER if name == 'ledger.json' else c.MAX_SOURCE
                c.require(0 <= info.file_size <= limit and info.compress_size == info.file_size, 'entry byte limit exceeded')
                total += info.file_size
                c.require(total <= MAX_EXPANDED, 'expanded-byte limit exceeded')
                with archive.open(info) as stream:
                    content = stream.read(limit+1)
                c.require(len(content) == info.file_size, 'entry size mismatch')
                files[name] = content
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        raise c.LedgerError('invalid ZIP: '+str(exc)) from exc
    c.require('manifest.json' in files and 'ledger.json' in files, 'missing required file')
    metadata = parse(files.pop('manifest.json'))
    c.require(isinstance(metadata, dict) and set(metadata) == {'format','version','files'}, 'invalid manifest fields')
    c.require(metadata['format'] == 'claim-source-ledger' and type(metadata['version']) is int and metadata['version'] == 1,
              'unsupported archive version')
    c.require(isinstance(metadata['files'], dict) and set(metadata['files']) == set(files), 'manifest file set mismatch')
    for name, content in files.items():
        record = metadata['files'][name]
        c.require(isinstance(record, dict) and set(record) == {'bytes','sha256'} and type(record['bytes']) is int
                  and record['bytes'] == len(content) and record['sha256'] == sha(content), 'manifest hash or size mismatch')
    data = parse(files['ledger.json'])
    expected = payloads(data)
    c.require(files == expected, 'snapshot set or canonical ledger mismatch')
    expected['manifest.json'] = manifest(expected)
    # Also rejects hidden local entries, prepended/trailing bytes, extras, links,
    # comments, alternate headers and discrepancies between local and central headers.
    c.require(raw == pack(expected), 'noncanonical ZIP structure or manifest')
    return data, files


def verify(path):
    raw = c.read_bytes(path, MAX_ARCHIVE)
    data, files = inspect_bytes(raw)
    return {'ok': True, 'version': 1, 'sha256': sha(raw), 'archive_bytes': len(raw),
            'expanded_bytes': sum(map(len, files.values())) + len(manifest(files)),
            'files': len(files)+1, 'sources': len(data['sources']),
            'claims': len(data['claims']), 'citations': len(data['citations'])}


def export(path, output):
    path, output = Path(path).absolute(), Path(output).absolute()
    # Lock the same persistent inode as every cooperating ledger mutation.
    with c.locked(path):
        before = c.read_bytes(path, c.MAX_LEDGER)
        raw = build(parse(before))
        c.require(c.read_bytes(path, c.MAX_LEDGER) == before, 'ledger changed during export')
        c.atomic_write(output, raw)
    return {'archive': str(output), 'sha256': sha(raw), 'archive_bytes': len(raw)}


def commit_directory(staging, destination):
    """Linux no-replace directory rename; no unsafe check-then-rename fallback."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    c.require(rename is not None, 'restore requires Linux renameat2(RENAME_NOREPLACE)')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(staging), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def restore(path, destination):
    # Input is completely verified in memory before creating a destination or stage.
    raw = c.read_bytes(path, MAX_ARCHIVE)
    data, files = inspect_bytes(raw)
    destination = Path(destination).absolute()
    c.require(not os.path.lexists(destination), 'restore destination already exists')
    staging = Path(tempfile.mkdtemp(prefix='.'+destination.name+'.restore-', dir=destination.parent))
    try:
        (staging/'snapshots').mkdir(mode=0o700)
        for name, content in sorted(files.items()):
            c.atomic_write(staging/name, content)
        # Sync staged directories before publication. Parent directory is deliberately
        # not fsynced after commit: a failure there cannot roll back a visible ledger.
        for folder in (staging/'snapshots', staging):
            fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        result = {'ledger': str(destination/'ledger.json'), 'sha256': sha(raw), 'restored': True}
        commit_directory(staging, destination)  # sole commit point, atomic and no-clobber
        return result
    finally:
        # Handles KeyboardInterrupt/SystemExit as well as write/validation failures.
        # SIGKILL/power loss may leave a private stage; never mistake it for a ledger.
        shutil.rmtree(staging, ignore_errors=True)
