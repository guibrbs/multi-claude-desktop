"""Bounded ASAR metadata experiment; never executes JavaScript or reads Keychain."""
import copy
import hashlib
import json
import re
import struct


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def leaves(node, prefix=''):
    files = node.get('files')
    if not isinstance(files, dict):
        raise ValueError('invalid ASAR directory')
    for name, entry in files.items():
        if not isinstance(name, str) or name in ('', '.', '..') or any(x in name for x in ('/', '\\', '\0')) or not isinstance(entry, dict):
            raise ValueError('invalid ASAR member name/type')
        path = prefix + name
        if 'files' in entry:
            yield from leaves(entry, path + '/')
        else:
            yield path, entry


def unpack(blob):
    if not 16 <= len(blob) <= 256 * 1024 * 1024:
        raise ValueError('ASAR size outside experiment bounds')
    a, b, c, d = struct.unpack_from('<4I', blob)
    if a != 4 or d > 16 * 1024 * 1024 or b != 8 + ((d + 3) & ~3) or c != b - 4 or 8 + b > len(blob):
        raise ValueError('unsupported ASAR pickle layout')
    raw = blob[16:16 + d]
    if any(blob[16 + d:8 + b]):
        raise ValueError('nonzero ASAR header padding')
    header = json.loads(raw, object_pairs_hook=unique_object)
    payload = blob[8 + b:]
    spans = []
    for path, entry in leaves(header):
        if entry.get('unpacked') or 'link' in entry:
            continue
        offset, size = entry.get('offset'), entry.get('size')
        if not isinstance(offset, str) or not re.fullmatch(r'0|[1-9][0-9]*', offset) or type(size) is not int or size < 0:
            raise ValueError('invalid packed member bounds')
        start = int(offset)
        if start + size > len(payload):
            raise ValueError('packed member escapes payload')
        if size:
            spans.append((start, start + size, path))
    spans.sort()
    # ASAR can deduplicate identical files by sharing an exact payload extent.
    # Partial overlaps remain unsupported; package.json may not have aliases.
    if any(left[1] > right[0] and left[:2] != right[:2] for left, right in zip(spans, spans[1:])):
        raise ValueError('overlapping packed members')
    return header, payload, raw


def package_region(header):
    entries = dict(leaves(header))
    entry = entries.get('package.json')
    if not entry or entry.get('unpacked') or 'link' in entry:
        raise ValueError('missing packed package.json')
    start, size = int(entry['offset']), entry['size']
    for path, other in entries.items():
        if path == 'package.json' or other.get('unpacked') or 'link' in other:
            continue
        offset = int(other['offset'])
        if other['size'] and start < offset + other['size'] and offset < start + size:
            raise ValueError('package.json cannot share its payload region')
    return start, size


def pack(header, payload):
    raw = json.dumps(header, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    padding = bytes((-len(raw)) % 4)
    size = 8 + len(raw) + len(padding)
    return struct.pack('<4I', 4, size, size - 4, len(raw)) + raw + padding + payload


def integrity(data, original):
    if original.get('algorithm') != 'SHA256' or type(original.get('blockSize')) is not int or not 1 <= original['blockSize'] <= 16 * 1024 * 1024:
        raise ValueError('unsupported package integrity format')
    result = dict(original)
    result['hash'] = sha(data)
    size = result['blockSize']
    result['blocks'] = [sha(data[i:i + size]) for i in range(0, len(data), size)]
    return result


def verify_change(before, after, name):
    old, old_payload, _ = unpack(before)
    new, new_payload, raw = unpack(after)
    left, right = dict(leaves(old)), dict(leaves(new))
    if left.keys() != right.keys() or 'package.json' not in left:
        raise ValueError('archive member set changed')
    entry, actual = left['package.json'], right['package.json']
    if entry.get('unpacked') or 'link' in entry or actual.get('offset') != entry.get('offset'):
        raise ValueError('package must remain a packed member at the same payload offset')
    start, size = package_region(old)
    package_region(new)
    old_bytes = old_payload[start:start + size]
    new_bytes = new_payload[start:start + actual['size']]
    expected_package = json.loads(old_bytes, object_pairs_hook=unique_object)
    if expected_package.get('productName') != 'Claude':
        raise ValueError('unreviewed source productName')
    expected_package['productName'] = name
    if json.loads(new_bytes, object_pairs_hook=unique_object) != expected_package:
        raise ValueError('package changed beyond productName')
    if old_payload[:start] != new_payload[:start] or old_payload[start + size:] != new_payload[start + actual['size']:]:
        raise ValueError('payload outside package.json changed')
    expected_header = copy.deepcopy(old)
    delta = actual['size'] - size
    for path, target in leaves(expected_header):
        if path == 'package.json':
            target['size'] = actual['size']
            target['integrity'] = integrity(new_bytes, entry['integrity'])
        elif 'offset' in target and not target.get('unpacked') and 'link' not in target:
            offset = int(target['offset'])
            if offset >= start + size:
                target['offset'] = str(offset + delta)
    if new != expected_header:
        raise ValueError('unexpected ASAR header changes')
    return {'header_sha256': sha(raw), 'members_checked': len(left),
            'changed_member': 'package.json', 'changed_semantic_field': 'productName',
            'javascript_payloads_unchanged': True, 'other_payload_bytes_unchanged': True}


def patch_product_name(blob, name):
    if not re.fullmatch(r'Claude Duo Probe [0-9a-f]{8}', name):
        raise ValueError('experiment requires its generated ASCII product name')
    header, payload, _ = unpack(blob)
    entry = dict(leaves(header)).get('package.json')
    if not entry or entry.get('unpacked') or 'link' in entry:
        raise ValueError('missing packed package.json')
    start, size = package_region(header)
    data = payload[start:start + size]
    if entry.get('integrity') != integrity(data, entry.get('integrity', {})):
        raise ValueError('source package integrity mismatch')
    package = json.loads(data, object_pairs_hook=unique_object)
    if package.get('productName') != 'Claude':
        raise ValueError('unreviewed source productName')
    package['productName'] = name
    replacement = json.dumps(package, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    delta = len(replacement) - size
    for path, target in leaves(header):
        if path == 'package.json':
            target['size'] = len(replacement)
            target['integrity'] = integrity(replacement, entry['integrity'])
        elif 'offset' in target and not target.get('unpacked') and 'link' not in target and int(target['offset']) >= start + size:
            target['offset'] = str(int(target['offset']) + delta)
    result = pack(header, payload[:start] + replacement + payload[start + size:])
    return result, verify_change(blob, result, name)
