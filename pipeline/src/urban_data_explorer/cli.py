from __future__ import annotations

import argparse

from .config import load_sources
from .build import build_gold
from .ingestion.downloader import download_source
from .validation import validate_gold_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="urban-data-explorer",
        description="Pilote les sources et les builds du projet Urban Data Explorer.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="Affiche les sources configurees.")

    download_parser = subparsers.add_parser("download", help="Telecharge une ou plusieurs sources.")
    download_parser.add_argument(
        "names",
        nargs="*",
        help="Noms des sources a telecharger. Si vide, toutes les sources sont prises.",
    )
    download_parser.add_argument(
        "--force",
        action="store_true",
        help="Retelecharge le fichier meme s'il existe deja.",
    )

    build_parser = subparsers.add_parser("build", help="Construit les zones Silver et Gold.")
    build_parser.add_argument(
        "--skip-noise",
        action="store_true",
        help="Ignore le calcul Bruitparif si vous voulez un build plus rapide.",
    )

    validate_parser = subparsers.add_parser("validate", help="Valide les sorties Gold dans MySQL et MongoDB.")
    validate_parser.add_argument(
        "--quiet",
        action="store_true",
        help="N'affiche que le resultat global.",
    )

    run_parser = subparsers.add_parser("run", help="Execute download, build et validate en une commande planifiable.")
    run_parser.add_argument(
        "sources",
        nargs="*",
        help="Sources a telecharger avant le build. Si vide, toutes les sources sont prises.",
    )
    run_parser.add_argument("--force-download", action="store_true", help="Retelecharge les sources existantes.")
    run_parser.add_argument("--skip-download", action="store_true", help="Ignore l'etape de telechargement.")
    run_parser.add_argument("--skip-build", action="store_true", help="Ignore l'etape de build.")
    run_parser.add_argument("--skip-validate", action="store_true", help="Ignore l'etape de validation.")
    run_parser.add_argument("--skip-noise", action="store_true", help="Ignore le calcul Bruitparif pendant le build.")

    return parser


def cmd_list() -> int:
    sources = load_sources()
    for name, source in sources.items():
        print(f"{name}: {source.label}")
        print(f"  groupe: {source.group}")
        print(f"  cible:  {source.target_path}")
        print(f"  resume: {source.summary}")
    return 0


def cmd_download(names: list[str], force: bool) -> int:
    sources = load_sources()
    selected_names = names or list(sources.keys())

    unknown = [name for name in selected_names if name not in sources]
    if unknown:
        raise SystemExit(f"Sources inconnues: {', '.join(unknown)}")

    for name in selected_names:
        source = sources[name]
        output_path = download_source(source, force=force)
        print(f"{name}: {output_path}")

    return 0


def cmd_build(skip_noise: bool) -> int:
    outputs = build_gold(include_noise=not skip_noise)
    for name, output_path in outputs.items():
        print(f"{name}: {output_path}")
    return 0


def cmd_validate(quiet: bool = False) -> int:
    try:
        issues = validate_gold_outputs()
    except Exception as exc:
        if not quiet:
            print(f"Validation impossible: {exc}")
        return 1

    if issues:
        if not quiet:
            print("Validation echouee:")
            for issue in issues:
                print(f"- {issue}")
        return 1

    if not quiet:
        print("Validation OK: sorties Gold coherentes.")
    return 0


def cmd_run(
    sources: list[str],
    *,
    force_download: bool,
    skip_download: bool,
    skip_build: bool,
    skip_validate: bool,
    skip_noise: bool,
) -> int:
    if not skip_download:
        print("== Download ==")
        code = cmd_download(sources, force_download)
        if code:
            return code

    if not skip_build:
        print("== Build ==")
        code = cmd_build(skip_noise)
        if code:
            return code

    if not skip_validate:
        print("== Validate ==")
        return cmd_validate()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        return cmd_list()
    if args.command == "download":
        return cmd_download(args.names, args.force)
    if args.command == "build":
        return cmd_build(args.skip_noise)
    if args.command == "validate":
        return cmd_validate(args.quiet)
    if args.command == "run":
        return cmd_run(
            args.sources,
            force_download=args.force_download,
            skip_download=args.skip_download,
            skip_build=args.skip_build,
            skip_validate=args.skip_validate,
            skip_noise=args.skip_noise,
        )

    parser.error("Commande non prise en charge.")
    return 1
