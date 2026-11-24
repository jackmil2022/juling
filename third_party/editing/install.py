"""Install the pinned editing skill checkouts without rewriting their trees."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import file_digest
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
PROBE_URL = "https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-essentials_build.zip"
PROBE_SHA256 = "fa7d4d7e795db0e2503f49f105f46ed5852386f0cfdd819899be3b65ebde24fc"


def fetch(url, destination):
    with urlopen(url, timeout=90) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def install_source(item):
    name, source = item
    destination = ROOT / name
    marker = ROOT / 'installed' / name
    if destination.is_dir() and marker.is_file() and marker.read_text().strip() == source['commit']:
        return
    with TemporaryDirectory(dir=ROOT) as temporary:
        stage = Path(temporary)
        archive = stage / 'source.zip'
        fetch(f"https://codeload.github.com/{source['repo']}/zip/{source['commit']}", archive)
        with ZipFile(archive) as bundle:
            bundle.extractall(stage)
        checkout, = (path for path in stage.iterdir() if path.is_dir())
        if destination.exists():
            for original in checkout.rglob('*'):
                if original.is_file():
                    installed = destination / original.relative_to(checkout)
                    if not installed.is_file() or installed.read_bytes() != original.read_bytes():
                        raise RuntimeError(f"Local upstream checkout differs from pinned source: {installed}")
        else:
            checkout.rename(destination)
        marker.parent.mkdir(exist_ok=True)
        marker.write_text(source['commit'] + '\n')


def install_probe(cache: Path | None):
    destination = ROOT / 'runtime'
    marker = destination / '.ffprobe-version'
    if marker.is_file() and marker.read_text().strip() == PROBE_SHA256 and all(
        (destination / name).is_file() for name in ('ffprobe.exe', 'LICENSE')
    ):
        return
    with TemporaryDirectory(dir=ROOT) as temporary:
        archive = cache or Path(temporary) / 'ffmpeg.zip'
        if cache is None:
            fetch(PROBE_URL, archive)
        with archive.open('rb') as stream:
            if file_digest(stream, 'sha256').hexdigest() != PROBE_SHA256:
                raise RuntimeError('FFmpeg archive SHA-256 differs from the pinned value')
        destination.mkdir(exist_ok=True)
        with ZipFile(archive) as bundle:
            for suffix, name in (('/bin/ffprobe.exe', 'ffprobe.exe'), ('/LICENSE', 'LICENSE')):
                member, = (member for member in bundle.namelist() if member.endswith(suffix))
                with bundle.open(member) as source, (destination / name).open('wb') as output:
                    shutil.copyfileobj(source, output)
        marker.write_text(PROBE_SHA256 + '\n')


if __name__ == '__main__':
    sources = json.loads((ROOT / 'sources.json').read_text(encoding='utf-8'))
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(install_source, sources.items()))
    install_probe(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    sys.path.insert(0, str(ROOT.parents[1]))
    from lib.infra.ffmpeg import ffmpeg_executable

    executable = Path(ffmpeg_executable())
    destination = ROOT / 'runtime' / 'ffmpeg.exe'
    if not destination.exists() or destination.stat().st_size != executable.stat().st_size:
        with TemporaryDirectory(dir=ROOT) as temporary:
            staged = Path(temporary) / destination.name
            shutil.copyfile(executable, staged)
            staged.replace(destination)
