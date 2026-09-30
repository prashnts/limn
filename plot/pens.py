# Limn plot - editing the pen library (pens.toml) from the web UI
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# A pen's table is rewritten line by line: the lines of the keys that stay keep
# their comments, the file's other comments and tables stay as they are.
import json
import os
import re
import tomllib
from pathlib import Path

from .tools import REGISTRY, resolve

KEY = re.compile(r'[a-z0-9._-]{1,8}')      # it goes on the tag, tool_holder.py encode_pen
BARE = re.compile(r'[A-Za-z0-9_-]+')
HEX = re.compile(r'#[0-9a-fA-F]{6}')
OWN = ('short', 'name', 'kind')            # the library's own keys go first, then the tool's
NOT_TUNABLE = {'id', 'kind', 'name', 'color', 'macro', 'begin', 'end', 'pen', 'holder', 'source'}


def kinds():
    '''The tool kinds and their number fields with defaults (None: the machine's), for the UI.'''
    out = {}
    for name, cls in REGISTRY.items():
        fields = {}
        for f, info in cls.model_fields.items():
            if f in NOT_TUNABLE:
                continue
            d = info.default
            if isinstance(d, bool) or not (d is None or isinstance(d, (int, float))):
                continue
            fields[f] = d
        out[name] = fields
    return out


def check(key, spec):
    '''-> the pen as it goes into the file, or ValueError.'''
    if not KEY.fullmatch(key or ''):
        raise ValueError(f'pen key {key!r}: up to 8 of a-z 0-9 - _ . (it goes on the tags)')
    spec = {k: v for k, v in spec.items() if v is not None and v != ''}
    name = str(spec.get('name', '')).strip()
    if not name:
        raise ValueError('a pen needs a name')
    spec['name'] = name
    if 'short' in spec:
        spec['short'] = str(spec['short']).strip()
        if len(spec['short']) > 20:
            raise ValueError(f"short {spec['short']!r}: up to 20 characters, it names the tags")
    colors = spec.pop('colors', None) or {}
    if not isinstance(colors, dict):
        raise ValueError('colors: {name: "#rrggbb"}')
    clean = {}
    for n, c in colors.items():
        n = str(n).strip()
        if not n or not HEX.fullmatch(str(c)):
            raise ValueError(f'colour {n!r} = {c!r}: a name and #rrggbb')
        clean[n] = str(c).lower()
    kind = spec.get('kind', 'pen')
    tool = {k: v for k, v in spec.items() if k not in ('name', 'short', 'kind')}
    try:
        resolve(kind)(id='check', kind=kind, **tool)
    except Exception as e:
        raise ValueError(f'pen {key}: {e}')
    if kind == 'pen':
        spec.pop('kind', None)
    if clean:
        spec['colors'] = clean
    return spec


def _key(k):
    return k if BARE.fullmatch(k) else json.dumps(k)


def _value(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return '[' + ', '.join(_value(x) for x in v) + ']'
    if isinstance(v, dict):
        return '{ ' + ', '.join(f'{_key(k)} = {_value(x)}' for k, x in v.items()) + ' }'
    raise ValueError(f'{v!r}: not for pens.toml')


def _line(k, v):
    return f'{_key(k)} = {_value(v)}'


def _parse_line(line):
    '''A `key = value` line -> (key, its trailing comment and where it starts), None: not one.'''
    try:
        data = tomllib.loads(line)
    except tomllib.TOMLDecodeError:
        return None
    if len(data) != 1 or line.lstrip().startswith('['):
        return None
    key = next(iter(data))
    for i, c in enumerate(line):
        if c == '#':
            try:
                if tomllib.loads(line[:i]) == data:
                    return key, line[i:], i
            except tomllib.TOMLDecodeError:
                pass
    return key, '', 0


def _header(line):
    s = line.strip()
    if not s.startswith('[') or s.startswith('[['):
        return None
    try:
        data = tomllib.loads(s)
    except tomllib.TOMLDecodeError:
        return None
    return next(iter(data), None)


def _tables(lines):
    '''-> [(key or None for the head, first line, end line)]'''
    starts = [(i, _header(l)) for i, l in enumerate(lines)]
    starts = [(i, k) for i, k in starts if k is not None]
    out = [(None, 0, starts[0][0] if starts else len(lines))]
    for n, (i, k) in enumerate(starts):
        out.append((k, i, starts[n + 1][0] if n + 1 < len(starts) else len(lines)))
    return out


def _order(spec):
    return [k for k in OWN if k in spec] + [k for k in spec if k not in OWN and k != 'colors'] \
        + (['colors'] if 'colors' in spec else [])


def _body(old, spec):
    '''The table's lines for `spec`, keeping the old lines' comments.'''
    out, done = [], set()
    last = 0
    for line in old:
        parsed = _parse_line(line)
        if parsed is None:
            out.append(line)                        # comments, blank lines
            continue
        key, comment, col = parsed
        if key not in spec:
            continue
        new = _line(key, spec[key])
        out.append(new.ljust(max(len(new) + 1, col)) + comment if comment else new)
        done.add(key)
        last = len(out)
    new = [_line(k, spec[k]) for k in _order(spec) if k not in done]
    # new keys after the last key line, before the blank lines and comments that lead to the next table
    return out[:last] + new + out[last:]


def save(path: Path, key, spec):
    '''Adds or changes the pen `key` -> the pen as saved. ValueError when it is no pen.'''
    spec = check(key, spec)
    text = path.read_text() if path.exists() else ''
    lines = text.splitlines()
    tables = _tables(lines)
    at = next(((a, b) for k, a, b in tables if k == key), None)
    if at:
        a, b = at
        lines[a + 1:b] = _body(lines[a + 1:b], spec)
    else:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ['', f'[{_key(key)}]'] + [_line(k, spec[k]) for k in _order(spec)]
    _write(path, lines, key, spec)
    return spec


def delete(path: Path, key):
    lines = path.read_text().splitlines()
    at = next(((a, b) for k, a, b in _tables(lines) if k == key), None)
    if not at:
        raise KeyError(key)
    a, b = at
    del lines[a:b]
    _write(path, lines, key, None)


def _write(path, lines, key, want):
    text = '\n'.join(lines).rstrip('\n') + '\n'
    got = tomllib.loads(text).get(key)
    if got != want:
        raise ValueError(f'pens.toml would read back {got!r}, not {want!r}')
    tmp = path.with_suffix('.toml.tmp')
    tmp.write_text(text)
    os.replace(tmp, path)
