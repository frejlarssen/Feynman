import pendulum
from kubernetes.client import models as k8s

from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.sdk import dag, get_current_context, task


KUBECONFIG = "/home/frej/.kube/config"
DATA_MOUNT_PATH = "/data"
DATA_PVC_NAME = "feynman-data-pvc"
SPLIT_IMAGE = "feynman-split:latest"
SIMULATE_IMAGE = "feynman-simulate:latest"
CONCAT_IMAGE = "feynman-concat:latest"
MAX_HEXSTRINGS_PER_BATCH = 100
TARGET_NUM_PODS_TEMPLATE = "{{ dag_run.conf.get('target_num_pods', 0) }}"
MAX_HEXSTRINGS_PER_BATCH_TEMPLATE = (
    "{{ dag_run.conf.get('max_hexstrings_per_batch', " + str(MAX_HEXSTRINGS_PER_BATCH) + ") }}"
)
SIMULATE_OMP_NUM_THREADS_TEMPLATE = "{{ dag_run.conf.get('simulate_omp_num_threads', 1) }}"
DEFAULT_BENCHMARK_CASE = {
    "experiment_name": "qft_n8_k2",
    "circuit_file": f"{DATA_MOUNT_PATH}/generated/circuits/qft/qft_n8_k2.qasm",
    "input_statevector_file": f"{DATA_MOUNT_PATH}/generated/statevectors/ket0_size1.hsv",
    "output_bitstrings_file": (
        f"{DATA_MOUNT_PATH}/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs"
    ),
}
EXPERIMENT_NAME_TEMPLATE = "{{ dag_run.conf.get('benchmark_case', {}).get('experiment_name', 'qft_n8_k2') }}"
HEXSTRINGS_FILE_TEMPLATE = (
    "{{ dag_run.conf.get('benchmark_case', {}).get('output_bitstrings_file', '"
    + DEFAULT_BENCHMARK_CASE["output_bitstrings_file"]
    + "') }}"
)
BATCH_DIR_TEMPLATE = (
    f"{DATA_MOUNT_PATH}/generated/batches/" + EXPERIMENT_NAME_TEMPLATE + "/{{ run_id }}"
)
RUN_OUTPUT_DIR_TEMPLATE = (
    f"{DATA_MOUNT_PATH}/outputs/cloud_benchmarks/" + EXPERIMENT_NAME_TEMPLATE + "/{{ run_id }}"
)
MERGED_OUTPUT_FILE_TEMPLATE = (
    RUN_OUTPUT_DIR_TEMPLATE + "/" + EXPERIMENT_NAME_TEMPLATE + "_all_batches.hsv"
)


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
    experiment_name = str(case.get("experiment_name", DEFAULT_BENCHMARK_CASE["experiment_name"])).strip()
    if not experiment_name:
        raise ValueError("benchmark_case.experiment_name must be non-empty.")
    case["experiment_name"] = experiment_name
    run_id = str(dag_run.run_id)
    case["batch_dir"] = f"{DATA_MOUNT_PATH}/generated/batches/{experiment_name}/{run_id}"
    case["run_output_dir"] = f"{DATA_MOUNT_PATH}/outputs/cloud_benchmarks/{experiment_name}/{run_id}"
    case["merged_output_file"] = f"{case['run_output_dir']}/{experiment_name}_all_batches.hsv"
    return case

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
)
def feynman():
    """
    ### Feynman DAG
    Orchestrates simulation over batched hexstrings with one PVC-backed pod per
    pipeline stage.
    """

    @task()
    def build_batch_arguments(num_batches: int) -> list[list[str]]:
        benchmark_case = _resolved_benchmark_case_from_context()
        batch_arguments = []

        for batch_id in range(num_batches):
            hexstrings_batch_file = f"{benchmark_case['batch_dir']}/batch_{batch_id}.hs"
            simulator_output_file = (
                f"{benchmark_case['run_output_dir']}/{benchmark_case['experiment_name']}_batch_{batch_id}.hsv"
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
                    "-t",
                    "0.0",
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
        get_logs=True,
        on_finish_action="delete_pod",
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
        get_logs=True,
        on_finish_action="delete_pod",
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
            EXPERIMENT_NAME_TEMPLATE + "_batch_",
            "-v",
            "1",
        ],
    )

    @task()
    def postprocessing() -> bool:
        merged_simulator_output_file = _resolved_benchmark_case_from_context()[
            "merged_output_file"
        ]
        print(f"Post-processing succeeded for {merged_simulator_output_file}.")
        return True

    split_hexstrings >> batch_arguments
    batch_arguments >> simulate_batches
    simulate_batches >> concatenate_batches
    concatenate_batches >> postprocessing()


feynman()
