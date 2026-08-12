import os
from pathlib import Path

import pendulum
from kubernetes.client import models as k8s

from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.sdk import dag, get_current_context, task


KUBECONFIG = os.environ.get("KUBECONFIG", str(Path.home() / ".kube" / "config"))
DATA_MOUNT_PATH = "/data"
DATA_PVC_NAME = "feynman-data-pvc"
SPLIT_IMAGE = "feynman-split:latest"
SIMULATE_IMAGE = "feynman-simulate:latest"
CONCAT_IMAGE = "feynman-concat:latest"
MAX_HEXSTRINGS_PER_BATCH = 100
SHARED_POOL = os.environ.get("FEYNMAN_SHARED_POOL", "simulate_pool")
LIGHT_TASK_POOL_SLOTS = int(os.environ.get("FEYNMAN_LIGHT_TASK_POOL_SLOTS", "1"))
SIMULATE_TASK_POOL_SLOTS = int(os.environ.get("FEYNMAN_SIMULATE_TASK_POOL_SLOTS", "1"))
TARGET_NUM_PODS_TEMPLATE = "{{ dag_run.conf.get('target_num_pods', 0) }}"
MAX_HEXSTRINGS_PER_BATCH_TEMPLATE = (
    "{{ dag_run.conf.get('max_hexstrings_per_batch', " + str(MAX_HEXSTRINGS_PER_BATCH) + ") }}"
)
SIMULATE_OMP_NUM_THREADS_TEMPLATE = "{{ dag_run.conf.get('simulate_omp_num_threads', 1) }}"
SIMULATE_FRACTION_TEMPLATE = "{{ dag_run.conf.get('fraction', 1.0) }}"
SIMULATE_THRESHOLD_TEMPLATE = "{{ dag_run.conf.get('threshold', 0.0) }}"
DEFAULT_BENCHMARK_CASE = {
    "experiment_tag": "qft_pod_sweep",
    "circuit_file": f"{DATA_MOUNT_PATH}/generated/circuits/qft/qft_n8_k2.qasm",
    "input_statevector_file": f"{DATA_MOUNT_PATH}/generated/statevectors/ket0_size1.hsv",
    "output_bitstrings_file": (
        f"{DATA_MOUNT_PATH}/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs"
    ),
}
EXPERIMENT_TAG_TEMPLATE = "{{ dag_run.conf.get('benchmark_case', {}).get('experiment_tag', 'qft_pod_sweep') }}"
HEXSTRINGS_FILE_TEMPLATE = (
    "{{ dag_run.conf.get('benchmark_case', {}).get('output_bitstrings_file', '"
    + DEFAULT_BENCHMARK_CASE["output_bitstrings_file"]
    + "') }}"
)
BATCH_DIR_TEMPLATE = f"{DATA_MOUNT_PATH}/generated/batches/" + EXPERIMENT_TAG_TEMPLATE + "/{{ run_id }}"
RUN_OUTPUT_DIR_TEMPLATE = (
    "{% set benchmark_case = dag_run.conf.get('benchmark_case', {}) %}"
    "{% if benchmark_case.get('run_output_dir') %}"
    "{{ benchmark_case.get('run_output_dir') }}"
    "{% else %}"
    f"{DATA_MOUNT_PATH}/outputs/cloud_benchmarks/"
    "{{ benchmark_case.get('experiment_tag', 'qft_pod_sweep') }}/{{ run_id }}"
    "{% endif %}"
)
MERGED_OUTPUT_FILE_TEMPLATE = (
    "{% set benchmark_case = dag_run.conf.get('benchmark_case', {}) %}"
    "{% if benchmark_case.get('merged_output_file') %}"
    "{{ benchmark_case.get('merged_output_file') }}"
    "{% else %}"
    f"{DATA_MOUNT_PATH}/outputs/cloud_benchmarks/"
    "{{ benchmark_case.get('experiment_tag', 'qft_pod_sweep') }}/{{ run_id }}/"
    "{{ benchmark_case.get('experiment_tag', 'qft_pod_sweep') }}_all_batches.hsv"
    "{% endif %}"
)


def _resolve_repo_root() -> Path:
    candidates: list[Path] = []

    repo_root_env = os.environ.get("FEYNMAN_REPO_ROOT", "").strip()
    if repo_root_env:
        candidates.append(Path(repo_root_env).expanduser().resolve())

    candidates.append(Path(__file__).resolve().parents[1])
    candidates.append(Path.home() / "projects" / "feynman" / "Feynman")

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / "data").exists() and (resolved / "scripts").exists():
            return resolved

    raise FileNotFoundError(
        "Could not resolve the Feynman repo root. Set FEYNMAN_REPO_ROOT to the repo path."
    )


REPO_ROOT = _resolve_repo_root()
DATA_HOST_ROOT = REPO_ROOT / "data"


def _resolved_benchmark_case_from_context() -> dict[str, str]:
    context = get_current_context()
    dag_run = context["dag_run"]
    conf = dag_run.conf or {}
    raw_case = conf.get("benchmark_case", {})
    if raw_case is None:
        raw_case = {}
    if not isinstance(raw_case, dict):
        raise ValueError("dag_run.conf.benchmark_case must be a JSON object.")

    case = dict(DEFAULT_BENCHMARK_CASE)
    case.update({k: str(v) for k, v in raw_case.items() if v is not None})
    experiment_tag = str(case.get("experiment_tag", DEFAULT_BENCHMARK_CASE["experiment_tag"])).strip()
    if not experiment_tag:
        raise ValueError("benchmark_case.experiment_tag must be non-empty.")
    case["experiment_tag"] = experiment_tag
    run_id = str(dag_run.run_id)
    case["batch_dir"] = f"{DATA_MOUNT_PATH}/generated/batches/{experiment_tag}/{run_id}"
    if not case.get("run_output_dir"):
        case["run_output_dir"] = f"{DATA_MOUNT_PATH}/outputs/cloud_benchmarks/{experiment_tag}/{run_id}"
    if not case.get("merged_output_file"):
        case["merged_output_file"] = f"{case['run_output_dir']}/{experiment_tag}_all_batches.hsv"
    return case


def _resolved_simulate_params_from_context() -> dict[str, str]:
    context = get_current_context()
    dag_run = context["dag_run"]
    conf = dag_run.conf or {}
    fraction = float(conf.get("fraction", 1.0))
    threshold = float(conf.get("threshold", 0.0))
    if fraction <= 0.0 or fraction > 1.0:
        raise ValueError(f"dag_run.conf.fraction must satisfy 0 < fraction <= 1, got {fraction}")
    if threshold < 0.0:
        raise ValueError(f"dag_run.conf.threshold must be >= 0, got {threshold}")
    return {
        "fraction": str(fraction),
        "threshold": str(threshold),
    }


def _mount_path_to_host_path(path_like: str) -> Path:
    path = Path(path_like)
    mount_root = Path(DATA_MOUNT_PATH)
    try:
        relative = path.relative_to(mount_root)
    except ValueError:
        return path
    return DATA_HOST_ROOT / relative

DATA_VOLUME_MOUNT = k8s.V1VolumeMount(
    name="feynman-data",
    mount_path=DATA_MOUNT_PATH,
)

DATA_VOLUME = k8s.V1Volume(
    name="feynman-data",
    persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
        claim_name=DATA_PVC_NAME,
    ),
)

SIMULATE_ENV_VARS = [
    k8s.V1EnvVar(
        name="OMP_NUM_THREADS",
        value=SIMULATE_OMP_NUM_THREADS_TEMPLATE,
    ),
]


@dag(
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["feynman"],
    default_args={
        "retries": 1,
        "retry_delay": pendulum.duration(minutes=1),
    },
)
def feynman():
    """
    ### Feynman DAG
    Orchestrates simulation over batched hexstrings with one PVC-backed pod per
    pipeline stage.
    """

    @task(pool=SHARED_POOL, pool_slots=LIGHT_TASK_POOL_SLOTS)
    def build_batch_arguments(num_batches: int) -> list[list[str]]:
        benchmark_case = _resolved_benchmark_case_from_context()
        simulate_params = _resolved_simulate_params_from_context()
        batch_arguments = []

        for batch_id in range(num_batches):
            hexstrings_batch_file = f"{benchmark_case['batch_dir']}/batch_{batch_id}.hs"
            simulator_output_file = (
                f"{benchmark_case['run_output_dir']}/{benchmark_case['experiment_tag']}_batch_{batch_id}.hsv"
            )
            batch_arguments.append(
                [
                    "-c",
                    benchmark_case["circuit_file"],
                    "-i",
                    benchmark_case["input_statevector_file"],
                    "-b",
                    hexstrings_batch_file,
                    "-o",
                    simulator_output_file,
                    "-f",
                    simulate_params["fraction"],
                    "-t",
                    simulate_params["threshold"],
                    "-v",
                    "1",
                ]
            )

        print(f"Prepared {num_batches} simulation argument lists from batch files.")
        return batch_arguments

    split_hexstrings = KubernetesPodOperator(
        task_id="split_hexstrings",
        name="split-hexstrings",
        image=SPLIT_IMAGE,
        image_pull_policy="Never",
        config_file=KUBECONFIG,
        pool=SHARED_POOL,
        pool_slots=LIGHT_TASK_POOL_SLOTS,
        do_xcom_push=True,
        get_logs=True,
        on_finish_action="delete_succeeded_pod",
        volume_mounts=[DATA_VOLUME_MOUNT],
        volumes=[DATA_VOLUME],
        arguments=[
            "-h",
            HEXSTRINGS_FILE_TEMPLATE,
            "-o",
            BATCH_DIR_TEMPLATE,
            "{% if dag_run.conf.get('target_num_pods', 0) | int > 0 %}-k{% else %}-n{% endif %}",
            "{% if dag_run.conf.get('target_num_pods', 0) | int > 0 %}"
            + TARGET_NUM_PODS_TEMPLATE
            + "{% else %}"
            + MAX_HEXSTRINGS_PER_BATCH_TEMPLATE
            + "{% endif %}",
            "-x",
            "/airflow/xcom/return.json",
            "-v",
            "1",
        ],
    )

    batch_arguments = build_batch_arguments(split_hexstrings.output)

    simulate_batches = KubernetesPodOperator.partial(
        task_id="simulate_batch",
        name="simulate-batch",
        image=SIMULATE_IMAGE,
        image_pull_policy="Never",
        config_file=KUBECONFIG,
        pool=SHARED_POOL,
        pool_slots=SIMULATE_TASK_POOL_SLOTS,
        get_logs=True,
        on_finish_action="delete_succeeded_pod",
        env_vars=SIMULATE_ENV_VARS,
        volume_mounts=[DATA_VOLUME_MOUNT],
        volumes=[DATA_VOLUME],
    ).expand(arguments=batch_arguments)

    concatenate_batches = KubernetesPodOperator(
        task_id="concatenate_batches",
        name="concatenate-batches",
        image=CONCAT_IMAGE,
        image_pull_policy="Never",
        config_file=KUBECONFIG,
        pool=SHARED_POOL,
        pool_slots=LIGHT_TASK_POOL_SLOTS,
        get_logs=True,
        on_finish_action="delete_succeeded_pod",
        volume_mounts=[DATA_VOLUME_MOUNT],
        volumes=[DATA_VOLUME],
        arguments=[
            "-i",
            RUN_OUTPUT_DIR_TEMPLATE,
            "-o",
            MERGED_OUTPUT_FILE_TEMPLATE,
            "-n",
            "{{ ti.xcom_pull(task_ids='split_hexstrings') }}",
            "-p",
            EXPERIMENT_TAG_TEMPLATE + "_batch_",
            "-v",
            "1",
        ],
    )

    @task(pool=SHARED_POOL, pool_slots=LIGHT_TASK_POOL_SLOTS)
    def postprocessing() -> bool:
        merged_simulator_output_file = _mount_path_to_host_path(
            _resolved_benchmark_case_from_context()["merged_output_file"]
        )
        if not merged_simulator_output_file.exists():
            raise FileNotFoundError(
                f"Merged simulator output file not found: {merged_simulator_output_file}"
            )
        file_size = merged_simulator_output_file.stat().st_size
        if file_size <= 0:
            raise ValueError(
                f"Merged simulator output file is empty: {merged_simulator_output_file}"
            )
        print(
            "Post-processing verified merged output "
            f"{merged_simulator_output_file} ({file_size} bytes)."
        )
        return True

    split_hexstrings >> batch_arguments
    batch_arguments >> simulate_batches
    simulate_batches >> concatenate_batches
    concatenate_batches >> postprocessing()


feynman()
