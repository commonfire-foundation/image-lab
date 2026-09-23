"""Build Image Lab only; install/build Imagescope from its separate repository."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdist', action='store_true', help='Also build a source archive')
    args = parser.parse_args()
    output = ROOT / 'dist'
    temporary_root = ROOT / 'results' / 'package-builds'
    output.mkdir(exist_ok=True)
    temporary_root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TMPDIR=str(temporary_root), PIP_DISABLE_PIP_VERSION_CHECK='1')
    subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
                    '--no-cache-dir', '--wheel-dir', str(output), str(ROOT)], env=env, check=True)
    if args.sdist:
        subprocess.run([sys.executable, '-c',
                        'import setuptools.build_meta as b,sys; b.build_sdist(sys.argv[1])', str(output)],
                       cwd=ROOT, env=env, check=True)
    print(f'Image Lab distribution: {output} (Imagescope is a separate dependency)')


if __name__ == '__main__':
    main()
