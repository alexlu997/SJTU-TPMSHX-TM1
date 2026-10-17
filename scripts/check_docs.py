"""Check repository document links and concrete project module commands."""
import re
from pathlib import Path
import subprocess
from urllib.parse import unquote, urlsplit

_LINK = re.compile(r'!?\[([^\]\n]*)\]\((<[^>\n]+>|[^\s)]+)(?:\s+"[^"]*")?\)')
_FENCE = re.compile(r'^\s*(`{3,}|~{3,})')
_INLINE_CODE = re.compile(r'(?P<ticks>`+).*?(?P=ticks)')


def prose(text):
    lines, fence = [], ''
    for line in text.splitlines():
        match = _FENCE.match(line)
        if match:
            marker = match[1]
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = ''
        elif not fence:
            lines.append(line)
    return '\n'.join(lines)


def anchors(text):
    text = prose(text)
    found = set(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)["\']', text))
    counts = {}
    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*\s*$', text, re.MULTILINE):
        heading = _LINK.sub(lambda match: match[1], heading)
        heading = re.sub(r'<[^>]+>', '', heading)
        slug = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        found.add(slug + (f'-{count}' if count else ''))
    return found


def check(root, paths):
    root = Path(root)
    failures, links, commands = [], 0, 0
    for name in paths:
        path = root / name
        text = path.read_text(encoding='utf-8')
        for match in _LINK.finditer(_INLINE_CODE.sub('', prose(text))):
            target = urlsplit(match[2].strip('<>'))
            if target.scheme or target.netloc:
                continue
            links += 1
            destination = path.parent / unquote(target.path) if target.path else path
            if not destination.exists():
                failures.append(f'{name}: missing link target {match[2]}')
            elif (target.fragment and destination.suffix == '.md'
                  and unquote(target.fragment) not in anchors(destination.read_text(encoding='utf-8'))):
                failures.append(f'{name}: missing anchor {match[2]}')
        for module in re.findall(r'(?:^|\s)-m\s+(sjtu_tpmshx[\w.<>\-…]*)', text):
            if any(marker in module for marker in ('<', '>', '...', '…')):
                continue
            module = module.rstrip('.')
            location = root.joinpath(*module.split('.'))
            if not (location.with_suffix('.py').is_file() or (location / '__main__.py').is_file()):
                failures.append(f'{name}: missing module command {module}')
            commands += 1
    if failures:
        raise ValueError('\n'.join(failures))
    return links, commands


def main():
    root = Path(__file__).resolve().parents[1]
    paths = subprocess.check_output(
        ['git', 'ls-files', '-z', '--', '*.md'], cwd=root, text=True).split('\0')
    links, commands = check(root, [path for path in paths if path])
    print(f'Documents checked: {links} local links and {commands} module commands')


if __name__ == '__main__':
    main()
