#!/usr/bin/env python3
import argparse
from pathlib import Path

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "data/generated/circuits/qaoa_maxcut"
)

# (n, p, graph, gammas, betas)
PRESETS = [
    (4, 1, "ring", [0.8], [0.4]),
    (8, 1, "ring", [0.8], [0.4]),
    (8, 2, "ring", [0.8, 0.6], [0.4, 0.25]),
    (12, 1, "path", [0.7], [0.35]),
    (6, 1, "complete", [0.5], [0.3]),
]


def _format_angle(theta: float) -> str:
    return f"{theta:.16g}"


def build_edges(n: int, graph: str) -> list[tuple[int, int, float]]:
    if graph == "ring":
        return [(i, (i + 1) % n, 1.0) for i in range(n)]
    if graph == "path":
        return [(i, i + 1, 1.0) for i in range(n - 1)]
    if graph == "complete":
        return [(i, j, 1.0) for i in range(n) for j in range(i + 1, n)]
    raise ValueError(f"Unknown graph type: {graph}")


def parse_edges(edges_str: str, n: int) -> list[tuple[int, int, float]]:
    edges: list[tuple[int, int, float]] = []
    seen: set[tuple[int, int]] = set()

    for token in edges_str.split(","):
        part = token.strip()
        if not part:
            continue

        if ":" in part:
            edge_part, weight_part = part.split(":", 1)
            weight = float(weight_part.strip())
        else:
            edge_part = part
            weight = 1.0

        if "-" not in edge_part:
            raise ValueError(
                f"Invalid edge token '{part}'. Expected 'u-v' or 'u-v:w'."
            )

        u_str, v_str = edge_part.split("-", 1)
        u = int(u_str.strip())
        v = int(v_str.strip())

        if u == v:
            raise ValueError(f"Self-loop edge '{part}' is not supported.")
        if u < 0 or v < 0 or u >= n or v >= n:
            raise ValueError(f"Edge '{part}' has vertex outside [0, {n - 1}].")

        a, b = (u, v) if u < v else (v, u)
        if (a, b) in seen:
            raise ValueError(f"Duplicate undirected edge '{part}'.")

        seen.add((a, b))
        edges.append((a, b, weight))

    if not edges:
        raise ValueError("No valid edges parsed from --edges.")

    return edges


def parse_angle_list(values: str | None, p: int, default: float) -> list[float]:
    if values is None:
        return [default for _ in range(p)]

    parsed = [float(x.strip()) for x in values.split(",") if x.strip()]
    if len(parsed) != p:
        raise ValueError(f"Expected {p} values, got {len(parsed)}.")
    return parsed


def write_qaoa_maxcut(
    f,
    n: int,
    p: int,
    edges: list[tuple[int, int, float]],
    gammas: list[float],
    betas: list[float],
) -> None:
    # Header
    f.write("OPENQASM 3.0;\n")
    f.write('include "stdgates.inc";\n')
    f.write(f"qreg q[{n}];\n")

    # |+>^n initialization
    for q in range(n):
        f.write(f"h q[{q}];\n")

    # p QAOA layers
    for layer in range(p):
        gamma = gammas[layer]
        beta = betas[layer]

        # Cost unitary for Max-Cut:
        # exp(-i * gamma * w_ij * Z_i Z_j), up to global phase.
        for u, v, weight in edges:
            phi = gamma * weight
            f.write(f"p({_format_angle(2.0 * phi)}) q[{u}];\n")
            f.write(f"p({_format_angle(2.0 * phi)}) q[{v}];\n")
            f.write(f"cp({_format_angle(-4.0 * phi)}) q[{u}],q[{v}];\n")

        # Mixer unitary:
        # exp(-i * beta * X_q) = RX(2 * beta)
        for q in range(n):
            f.write(f"rx({_format_angle(2.0 * beta)}) q[{q}];\n")


def generate_qaoa_maxcut(
    n: int,
    p: int,
    out_dir: Path,
    graph: str = "ring",
    edges_str: str | None = None,
    gammas: list[float] | None = None,
    betas: list[float] | None = None,
    name: str | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    edges = (
        parse_edges(edges_str=edges_str, n=n)
        if edges_str
        else build_edges(n=n, graph=graph)
    )
    gammas = gammas if gammas is not None else [0.7 for _ in range(p)]
    betas = betas if betas is not None else [0.3 for _ in range(p)]

    if len(gammas) != p:
        raise ValueError(f"Expected p={p} gamma values, got {len(gammas)}.")
    if len(betas) != p:
        raise ValueError(f"Expected p={p} beta values, got {len(betas)}.")

    if name is None:
        graph_label = "custom" if edges_str else graph
        filename = f"qaoa_maxcut_{graph_label}_n{n}_p{p}.qasm"
    else:
        filename = name if name.endswith(".qasm") else f"{name}.qasm"

    out_path = out_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        write_qaoa_maxcut(f=f, n=n, p=p, edges=edges, gammas=gammas, betas=betas)

    return out_path


def bulk_generate(out_dir: Path) -> list[Path]:
    created: list[Path] = []
    for n, p, graph, gammas, betas in PRESETS:
        created.append(
            generate_qaoa_maxcut(
                n=n,
                p=p,
                out_dir=out_dir,
                graph=graph,
                gammas=gammas,
                betas=betas,
            )
        )
    return created


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate QAOA Max-Cut circuits in OpenQASM 3.0."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--single",
        action="store_true",
        help="Generate one circuit instead of full preset bulk set.",
    )
    parser.add_argument("--n", type=int, help="Number of qubits / graph vertices.")
    parser.add_argument("--p", type=int, help="Number of QAOA layers.")
    parser.add_argument(
        "--graph",
        choices=["ring", "path", "complete"],
        default="ring",
        help="Built-in graph family (ignored if --edges is provided).",
    )
    parser.add_argument(
        "--edges",
        type=str,
        help="Custom edge list: 'u-v,u-v' or weighted 'u-v:w,...'.",
    )
    parser.add_argument(
        "--gammas",
        type=str,
        help="Comma-separated gamma values, one per layer.",
    )
    parser.add_argument(
        "--betas",
        type=str,
        help="Comma-separated beta values, one per layer.",
    )
    parser.add_argument(
        "--name", type=str, help="Output filename stem or explicit .qasm filename."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.single:
        if args.n is None or args.p is None:
            raise SystemExit("--single requires both --n and --p.")
        if args.n < 2:
            raise SystemExit("--n must be at least 2.")
        if args.p < 1:
            raise SystemExit("--p must be at least 1.")

        gammas = parse_angle_list(args.gammas, args.p, default=0.7)
        betas = parse_angle_list(args.betas, args.p, default=0.3)
        out_path = generate_qaoa_maxcut(
            n=args.n,
            p=args.p,
            out_dir=args.output_dir,
            graph=args.graph,
            edges_str=args.edges,
            gammas=gammas,
            betas=betas,
            name=args.name,
        )
        print(out_path)
        return

    for out_path in bulk_generate(out_dir=args.output_dir):
        print(out_path)


if __name__ == "__main__":
    main()
